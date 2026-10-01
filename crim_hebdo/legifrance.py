"""Enrichissement Legifrance facultatif.

Judilibre fournit deja le niveau de publication (b = publie au bulletin).
Legifrance ajoute deux informations utiles en pratique :

  * le numero du bulletin dans lequel l'arret est reproduit (ex. "B. 12") ;
  * l'URL officielle de la decision sur legifrance.gouv.fr.

Si l'API Legifrance n'est pas activee sur le compte PISTE, l'enrichissement
echoue silencieusement : le tableau de bord reste complet.
"""

from __future__ import annotations

import time
from typing import Any

from .config import Config
from .piste import PisteClient, PisteError

SEARCH_CC_PATH = "/search/cc"


class LegifranceClient:
    def __init__(self, config: Config, client: PisteClient):
        self.config = config
        self.http = client
        self.available = True
        self.last_error: str | None = None

    def search_by_number(self, pourvoi_number: str) -> dict[str, Any] | None:
        """Retrouve une decision de cassation par son numero de pourvoi."""
        if not self.available or not pourvoi_number:
            return None
        body = {
            "query": f"numero:{pourvoi_number}",
            "dateStart": None,
            "dateEnd": None,
            "pageSize": 5,
            "pageNumber": 1,
            "sort": "date",
        }
        url = f"{self.config.legifrance_base}/search/all"
        try:
            payload = self.http.request("POST", url, json_body=body, retries=2)
        except PisteError as exc:
            self.available = False
            self.last_error = str(exc)
            return None
        time.sleep(self.config.sleep_between_calls)
        hits = payload.get("results") or [] if isinstance(payload, dict) else []
        for hit in hits:
            if str(hit.get("numeroPourvois", "")).strip() == pourvoi_number.strip():
                return hit
        return hits[0] if hits else None


def publication_details(hit: dict[str, Any] | None) -> dict[str, Any]:
    """Extrait les mentions de publication d'un resultat Legifrance."""
    if not hit:
        return {}
    details: dict[str, Any] = {}
    mentions = hit.get("publications") or []
    for mention in mentions:
        for entry in mention.get("publicationBulletins", []) or []:
            kind = str(entry.get("type", "")).upper()
            details.setdefault(kind, []).append(
                {
                    "numero": entry.get("numero"),
                    "date": entry.get("datePublication"),
                    "intitule": entry.get("intitule"),
                }
            )
    if hit.get("url"):
        details["url"] = hit["url"]
    if hit.get("textVersion"):
        details["text_url"] = hit["textVersion"]
    return details
