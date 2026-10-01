"""Stockage local (SQLite) des arrêts collectés et des analyses.

Objectif : permettre une actualisation hebdomadaire incrémentale sans
re-télécharger ni re-analyser les arrêts déjà connus (on se base sur l'ECLI
et l'identifiant Judilibre, tous deux stables).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id             TEXT PRIMARY KEY,
    ecli           TEXT,
    number         TEXT,
    chamber        TEXT,
    formation      TEXT,
    decision_date  TEXT,
    publication    TEXT,
    solution       TEXT,
    summary        TEXT,
    url            TEXT,
    source         TEXT,
    fetched_at     TEXT,
    update_date    TEXT,
    analysis_json  TEXT,
    raw_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_date ON decisions(decision_date);
CREATE INDEX IF NOT EXISTS idx_decisions_ecli ON decisions(ecli);

CREATE TABLE IF NOT EXISTS themes (
    decision_id TEXT NOT NULL,
    theme       TEXT NOT NULL,
    label       TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 0,
    evidence    TEXT,
    PRIMARY KEY (decision_id, theme)
);
CREATE INDEX IF NOT EXISTS idx_themes_theme ON themes(theme);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    date_start TEXT,
    date_end   TEXT,
    found      INTEGER DEFAULT 0,
    new        INTEGER DEFAULT 0,
    bulletin   INTEGER DEFAULT 0,
    status     TEXT,
    message    TEXT
);

-- Fichiers d'appoint DILA déjà traités (évite de retélécharger une semaine).
CREATE TABLE IF NOT EXISTS releases (
    name         TEXT PRIMARY KEY,
    published    TEXT,
    size_bytes   INTEGER,
    url          TEXT,
    processed_at TEXT,
    decisions    INTEGER DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except ValueError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


class Store:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "crim_hebdo.sqlite3"
        # Le serveur web est multi-thread : la connexion est partagée sous verrou.
        # Le journal WAL autorise un lecteur concurrent pendant l'écriture
        # de l'actualisation, qui se fait dans un Store distinct.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------- decisions
    def known_keys(self) -> set[str]:
        rows = self.conn.execute("SELECT id, ecli, number FROM decisions").fetchall()
        keys: set[str] = set()
        for row in rows:
            if row["id"]:
                keys.add(f"id:{row['id']}")
            if row["ecli"]:
                keys.add(f"ecli:{row['ecli']}")
            if row["number"]:
                keys.add(f"num:{row['number']}")
        return keys

    def identity_index(self) -> list[tuple[str, str, str]]:
        """(id, ecli, numéro) de chaque décision, pour le dédoublonnage."""
        rows = self.conn.execute("SELECT id, ecli, number FROM decisions").fetchall()
        return [(row["id"] or "", row["ecli"] or "", row["number"] or "") for row in rows]

    def upsert_decision(
        self,
        meta: dict[str, Any],
        raw: dict[str, Any],
        analysis: dict[str, Any],
    ) -> bool:
        """Insere ou met a jour une decision. Retourne True si nouvelle."""
        existing = self.conn.execute(
            "SELECT id FROM decisions WHERE id = ?", (meta["id"],)
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO decisions (id, ecli, number, chamber, formation, decision_date,
                                   publication, solution, summary, url, source,
                                   fetched_at, update_date, analysis_json, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                update_date = excluded.update_date,
                publication = excluded.publication,
                summary = excluded.summary,
                url = excluded.url,
                source = excluded.source,
                analysis_json = excluded.analysis_json,
                raw_json = excluded.raw_json
            """,
            (
                meta.get("id"),
                meta.get("ecli"),
                meta.get("number"),
                meta.get("chamber"),
                meta.get("formation"),
                meta.get("decision_date"),
                _json(meta.get("publication")),
                meta.get("solution"),
                meta.get("summary"),
                meta.get("url"),
                meta.get("source", "judilibre"),
                _now(),
                meta.get("update_date"),
                _json(analysis),
                _json(raw),
            ),
        )
        self.conn.execute("DELETE FROM themes WHERE decision_id = ?", (meta["id"],))
        for theme in analysis.get("themes", []):
            self.conn.execute(
                "INSERT OR REPLACE INTO themes (decision_id, theme, label, score, evidence)"
                " VALUES (?,?,?,?,?)",
                (
                    meta["id"],
                    theme.get("code"),
                    theme.get("label"),
                    float(theme.get("score") or 0),
                    _json(theme.get("evidence")),
                ),
            )
        self.conn.commit()
        return existing is None

    def decisions_between(self, date_start: str, date_end: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE decision_date BETWEEN ? AND ?"
            " ORDER BY decision_date DESC, number DESC",
            (date_start, date_end),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def all_decisions(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM decisions ORDER BY decision_date DESC, number DESC"
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def theme_counts(self, date_start: str | None = None, date_end: str | None = None) -> dict[str, int]:
        if date_start and date_end:
            rows = self.conn.execute(
                """
                SELECT t.theme AS theme, t.label AS label, COUNT(*) AS n
                FROM themes t JOIN decisions d ON d.id = t.decision_id
                WHERE d.decision_date BETWEEN ? AND ?
                GROUP BY t.theme ORDER BY n DESC
                """,
                (date_start, date_end),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT theme, label, COUNT(*) AS n FROM themes GROUP BY theme ORDER BY n DESC"
            ).fetchall()
        return {row["label"] or row["theme"]: row["n"] for row in rows}

    # ------------------------------------------------------------------ runs
    def daily_counts(self) -> dict[str, dict[str, int]]:
        """Nombre d'arrêts et de publications au bulletin, par jour de décision."""
        rows = self.conn.execute(
            "SELECT decision_date AS d, publication AS p FROM decisions"
            " WHERE decision_date IS NOT NULL ORDER BY decision_date DESC"
        ).fetchall()
        buckets: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = buckets.setdefault(row["d"], {"total": 0, "bulletin": 0})
            bucket["total"] += 1
            if any(str(code).lower() == "b" for code in _json_list(row["p"])):
                bucket["bulletin"] += 1
        return buckets

    def start_run(self, date_start: str, date_end: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO runs (started_at, date_start, date_end, status) VALUES (?,?,?,?)",
            (_now(), date_start, date_end, "running"),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        found: int,
        new: int,
        bulletin: int,
        status: str,
        message: str = "",
    ) -> None:
        self.conn.execute(
            "UPDATE runs SET ended_at=?, found=?, new=?, bulletin=?, status=?, message=? WHERE id=?",
            (_now(), found, new, bulletin, status, message, run_id),
        )
        self.conn.commit()

    def recent_runs(self, limit: int = 15) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------- releases
    def processed_releases(self) -> list[str]:
        rows = self.conn.execute("SELECT name FROM releases ORDER BY published DESC").fetchall()
        return [row["name"] for row in rows]

    def mark_release(self, release_name: str, published: str, url: str, decisions: int) -> None:
        self.conn.execute(
            "INSERT INTO releases (name, published, url, processed_at, decisions, size_bytes)"
            " VALUES (?,?,?,?,?,NULL)"
            " ON CONFLICT(name) DO UPDATE SET published=excluded.published,"
            " processed_at=excluded.processed_at, decisions=excluded.decisions",
            (release_name, published, url, _now(), decisions),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ demo
    def import_json(self, decisions: Iterable[dict[str, Any]]) -> int:
        count = 0
        for item in decisions:
            meta = item.get("meta", {})
            self.upsert_decision(meta, item.get("raw", {}), item.get("analysis", {}))
            count += 1
        return count

    def is_empty(self) -> bool:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()
        return not row or row["n"] == 0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["publication"] = _load(out.get("publication"), [])
    out["analysis"] = _load(out.get("analysis_json"), {})
    out["raw"] = _load(out.get("raw_json"), {})
    return out


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
