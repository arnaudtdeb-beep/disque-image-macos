"""Client de l'API Judilibre (Cour de cassation), exposee via PISTE.

Base : {api_url}/cassation/judilibre/v1.0

Points d'entree utilises :
  GET /search     recherche structuree (chambre, periode, niveau de publication)
  GET /decision   texte integral + zones structurees (expose, moyens,
                  motivations, dispositif, annexes)
  GET /taxonomy   libelles des cles de reference (chambre, publication, ...)

La recherche renvoie deja, pour chaque resultat, les metadonnees.determinantes
pour notre besoin : niveau de publication (b = bulletin), solution, ECLI,
sommaire officiel de la Cour, et nomenclature des matieres.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from .config import Config
from .piste import PisteClient

# Cles de la nomenclature Judilibre retenues pour le suivi de la chambre criminelle.
CHAMBER_CRIM = "crim"
PUBLICATION_BULLETIN = "b"
PUBLICATION_RAPPORT = "r"


class JudilibreClient:
    def __init__(self, config: Config, client: PisteClient):
        self.config = config
        self.http = client
        self._taxonomy_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ utils
    def _get(self, path: str, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        url = f"{self.config.judilibre_base}{path}"
        result = self.http.get(url, params=params, **kwargs)
        if self.config.sleep_between_calls:
            time.sleep(self.config.sleep_between_calls)
        return result

    # ----------------------------------------------------------------- search
    def search(
        self,
        date_start: str,
        date_end: str,
        chambers: Iterable[str] | None = None,
        publication: Iterable[str] | None = None,
        types: Iterable[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Récupère toutes les décisions d'une periode, en paginant.

        date_start / date_end : format ISO court (AAAA-MM-JJ).
        """
        params: dict[str, Any] = {
            "jurisdiction": self.config.jurisdiction,
            "date_start": date_start,
            "date_end": date_end,
            "sort": "date",
            "order": "desc",
            "page_size": self.config.page_size,
            "resolve_references": True,
            "chamber": list(chambers if chambers is not None else self.config.chambers),
        }
        if publication:
            params["publication"] = list(publication)
        if types or self.config.types:
            params["type"] = list(types or self.config.types)
        if self.config.formations:
            params["formation"] = list(self.config.formations)
        params.update(extra or {})

        results: list[dict[str, Any]] = []
        page = 0
        total: int | None = None
        while page < self.config.max_pages:
            params["page"] = page
            payload = self._get("/search", params)
            if not isinstance(payload, dict):
                break
            page_results = payload.get("results") or []
            if total is None:
                total = payload.get("total")
            for item in page_results:
                results.append(_flatten_result(item))
            if not page_results:
                break
            if total is not None and len(results) >= int(total):
                break
            if payload.get("next_page") is None:
                break
            page += 1
        return results

    # --------------------------------------------------------------- decision
    def decision(self, decision_id: str) -> dict[str, Any]:
        """Texte integral et zones structurees d'une decision."""
        payload = self._get("/decision", {"id": decision_id, "resolve_references": True})
        return payload if isinstance(payload, dict) else {}

    def decisions(self, decision_ids: Iterable[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for decision_id in decision_ids:
            try:
                full = self.decision(decision_id)
            except Exception:  # une decision indisponible ne doit pas stopper le lot
                continue
            if full:
                out.append(full)
        return out

    # --------------------------------------------------------------- taxonomy
    def taxonomy(self, kind: str, **params: Any) -> list[dict[str, Any]]:
        cache_key = f"{kind}:{sorted(params.items())}"
        if cache_key in self._taxonomy_cache:
            return self._taxonomy_cache[cache_key]
        payload = self._get("/taxonomy", {"id": kind, **params})
        items = payload.get("results") if isinstance(payload, dict) else None
        items = items or []
        self._taxonomy_cache[cache_key] = items
        return items


def _flatten_result(item: dict[str, Any]) -> dict[str, Any]:
    """Le score et les highlights sont hors du modele utile : on les isole."""
    result = {k: v for k, v in item.items() if k not in ("score", "highlights")}
    if isinstance(item.get("publication"), list):
        result["publication"] = [str(p) for p in item["publication"]]
    return result
