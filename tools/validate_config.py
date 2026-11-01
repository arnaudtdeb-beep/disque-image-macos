"""Valide un config.json destiné à être embarqué dans l'image disque.

Utilisé par le workflow de construction AVANT de créer le .dmg, pour ne pas
livrer une image dont l'application retomberait silencieusement sur la source
DILA faute de clés lisibles (secret mal collé, JSON tronqué, préfixe parasite).

Usage :
    python3 tools/validate_config.py chemin/vers/config.json

Code retour 0 si exploitable, 1 sinon. Affiche un message lisible ; préfixe
« ::error:: » compris par GitHub Actions pour annoter le run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def extraire_objet(texte: str) -> dict | None:
    """Extrait le premier objet JSON valide, même entouré de parasites."""
    texte = texte.strip().lstrip("\ufeff")
    if texte[:2] in ("b'", 'b"'):
        texte = texte[2:]
    depart = texte.find("{")
    if depart == -1:
        return None
    try:
        objet, _ = json.JSONDecoder().raw_decode(texte[depart:])
    except json.JSONDecodeError:
        return None
    return objet if isinstance(objet, dict) else None


def valider(chemin: Path) -> int:
    if not chemin.is_file():
        print("::error::config.json absent", file=sys.stderr)
        return 1
    donnees = extraire_objet(chemin.read_text(encoding="utf-8"))
    if donnees is None:
        print("::error::config.json n'est pas un objet JSON lisible", file=sys.stderr)
        return 1
    source = donnees.get("source")
    a_cles = bool(donnees.get("client_id") and donnees.get("client_secret"))
    print(f"config valide : source={source!r} cles_piste={a_cles}")
    if source == "piste" and not a_cles:
        print(
            "::error::source=piste mais client_id/client_secret manquants",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_config.py <config.json>", file=sys.stderr)
        return 2
    return valider(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
