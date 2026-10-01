"""Serveur web local (bibliothèque standard uniquement).

Il n'expose que sur la boucle locale (127.0.0.1) : les arrêts sont des
documents publics, mais rien ne doit être exposé sur le réseau sans décision
délibérée. Les identifiants PISTE ne quittent jamais le processus : le
navigateur ne parle qu'à ce serveur local.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .analysis import publication_labels
from .config import Config, load_config
from .piste import PisteError
from .store import Store
from .summarize import solution_label
from .weekly import last_week, run_update

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


class AppState:
    """Etat partage entre les requetes (la base est ouverte en lecture)."""

    def __init__(self, config: Config):
        self.config = config
        self.store = Store(config.data_dir)
        self.lock = threading.Lock()
        self.busy = False
        self.last_error: str | None = None

    def close(self) -> None:
        self.store.close()


def _project(row: dict[str, Any]) -> dict[str, Any]:
    """Ligne de base → objet affiche dans l'interface."""
    meta = dict((row.get("analysis") or {}).get("meta") or {})
    analysis = row.get("analysis") or {}
    publication = [str(p).lower() for p in (row.get("publication") or [])]
    meta.update(
        {
            "id": row.get("id"),
            "ecli": row.get("ecli"),
            "number": row.get("number"),
            "chamber": row.get("chamber"),
            "formation": row.get("formation"),
            "decision_date": row.get("decision_date"),
            "publication": publication,
            "publication_labels": publication_labels(publication),
            "au_bulletin": meta.get("au_bulletin", "b" in publication),
            "au_rapport": meta.get("au_rapport", "r" in publication),
            "solution": row.get("solution"),
            "solution_label": solution_label(row.get("solution")),
            "summary": row.get("summary"),
            "url": row.get("url"),
            "url_legifrance": meta.get("url_legifrance"),
            "bulletin_numero": meta.get("bulletin_numero"),
            "themes_officiels": meta.get("themes_officiels") or [],
            "particulier_interet": meta.get("particulier_interet"),
            "extrait_partiel": meta.get("extrait_partiel"),
        }
    )
    raw = row.get("raw") or {}
    return {
        "meta": meta,
        "themes": analysis.get("themes") or [],
        "attendu": analysis.get("attendu") or [],
        "solution_texte": analysis.get("solution_texte") or [],
        "motifs": analysis.get("motifs") or [],
        "portee": analysis.get("portee") or [],
        "moyens": analysis.get("moyens") or [],
        "textes_appliques": analysis.get("textes_appliques") or [],
        "citations": analysis.get("citations") or [],
        "fiabilite": analysis.get("fiabilite"),
        "llm_utilise": analysis.get("llm_utilise"),
        "text": raw.get("text") or "",
    }


class Handler(BaseHTTPRequestHandler):
    state: AppState
    server_version = "crim-hebdo/1.0"

    # ------------------------------------------------------------------ utils
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        print(f"  [serveur] {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _file(self, path: Path) -> None:
        if not path.is_file() or WEB_ROOT.resolve() not in path.resolve().parents:
            self._json({"error": "introuvable"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, path.read_bytes(), content_type)

    # -------------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            self._file(WEB_ROOT / "index.html")
        elif route.startswith("/static/"):
            self._file(WEB_ROOT / route.replace("/static/", "", 1))
        elif route == "/api/config":
            self._json(
                {
                    "chambers": self.state.config.chambers,
                    "jurisdiction": self.state.config.jurisdiction,
                    "source": self.state.config.source,
                    "piste_configured": self.state.config.has_piste_credentials,
                    "dila_configured": self.state.config.source == "dila",
                    "llm": self.state.config.llm.provider if self.state.config.llm.enabled else "none",
                    "llm_model": self.state.config.llm.model if self.state.config.llm.enabled else "",
                    "legifrance": self.state.config.enrich_legifrance,
                    "last_week": list(last_week()),
                }
            )
        elif route == "/api/periods":
            self._json(self._periods())
        elif route == "/api/decisions":
            self._json(self._decisions(query))
        elif route == "/api/decision":
            self._json(self._decision(query))
        elif route == "/api/themes":
            start = query.get("debut", [None])[0]
            end = query.get("fin", [None])[0]
            with self.state.lock:
                counts = self.state.store.theme_counts(start, end)
            self._json(counts)
        elif route == "/api/runs":
            with self.state.lock:
                runs = self.state.store.recent_runs()
            self._json(runs)
        else:
            self._json({"error": "route inconnue"}, HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    # ------------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/update":
            self._json({"error": "route inconnue"}, HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
        date_start = payload.get("debut") or None
        date_end = payload.get("fin") or None

        if self.state.busy:
            self._json({"error": "une actualisation est déjà en cours"}, HTTPStatus.CONFLICT)
            return
        if self.state.config.source == "piste" and not self.state.config.has_piste_credentials:
            self._json(
                {
                    "error": "Identifiants PISTE absents : renseignez client_id / client_secret "
                    "dans config.json, ou basculez sur la source gratuite « dila »."
                },
                HTTPStatus.PRECONDITION_FAILED,
            )
            return

        self.state.busy = True
        self.state.last_error = None

        def worker() -> None:
            # connexion dédiée : l'actualisation écrit pendant que l'interface
            # continue de lire la base (journal WAL).
            store = Store(self.state.config.data_dir)
            try:
                run_update(
                    self.state.config,
                    date_start=date_start,
                    date_end=date_end,
                    store=store,
                    log=lambda message: print(f"  [veille] {message}"),
                    force=bool(payload.get("force")),
                )
            except PisteError as exc:
                self.state.last_error = str(exc)
                print(f"  [veille] ERREUR : {exc}")
            except Exception as exc:  # noqa: BLE001
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                print(f"  [veille] ERREUR inattendue : {self.state.last_error}")
            finally:
                store.close()
                self.state.busy = False

        threading.Thread(target=worker, daemon=True).start()
        self._json({"status": "lancé", "debut": date_start, "fin": date_end})

    # ------------------------------------------------------------------ data
    def _periods(self) -> dict[str, Any]:
        with self.state.lock:
            buckets = self.state.store.daily_counts()
            runs = self.state.store.recent_runs()
        return {
            "periods": [{"date": day, **counts} for day, counts in sorted(buckets.items(), reverse=True)],
            "runs": runs,
            "busy": self.state.busy,
            "last_error": self.state.last_error,
        }

    def _decisions(self, query: dict[str, list[str]]) -> dict[str, Any]:
        start = query.get("debut", [None])[0]
        end = query.get("fin", [None])[0]
        with self.state.lock:
            rows = (
                self.state.store.decisions_between(start, end)
                if start and end
                else self.state.store.all_decisions()
            )
        limit = int(query.get("limit", ["400"])[0] or 400)
        items = [_project(row) for row in rows][:limit]
        return {
            "debut": start,
            "fin": end,
            "total": len(items),
            "au_bulletin": sum(1 for i in items if i["meta"]["au_bulletin"]),
            "arrets": items,
            "busy": self.state.busy,
            "last_error": self.state.last_error,
        }

    def _decision(self, query: dict[str, list[str]]) -> dict[str, Any]:
        decision_id = query.get("id", [""])[0]
        with self.state.lock:
            row = self.state.store.get_decision(decision_id)
        if not row:
            self._json({"error": "arrêt introuvable"}, HTTPStatus.NOT_FOUND)
            return
        self._json(_project(row))


def serve(
    config: Config | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> ThreadingHTTPServer:
    config = config or load_config()
    state = AppState(config)
    handler = type("BoundHandler", (Handler,), {"state": state})
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print("Veille chambre criminelle — interface ouverte sur " + url)
    print("Ctrl+C pour arrêter.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")
    finally:
        httpd.server_close()
        state.close()
    return httpd


main = serve
