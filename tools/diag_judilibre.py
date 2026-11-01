"""Diagnostic de connexion à l'API Judilibre via PISTE.

Lance ce script depuis la racine du projet pour vérifier, en un coup d'œil,
si tes identifiants PISTE fonctionnent et sur quel environnement
(sandbox ou production).

Usage :

    # Production (par défaut)
    CRIM_HEBDO_CLIENT_ID='...' CRIM_HEBDO_CLIENT_SECRET='...' \
        python3 tools/diag_judilibre.py

    # Sandbox explicitement
    DIAG_SANDBOX=1 CRIM_HEBDO_CLIENT_ID='...' CRIM_HEBDO_CLIENT_SECRET='...' \
        python3 tools/diag_judilibre.py

Le script affiche l'environnement, tente une authentification OAuth puis un
appel /search sur la chambre criminelle, et résume le diagnostic. Il ne
modifie aucune donnée et ne révèle pas les secrets.

Codes de retour :
    0  succès (authentification + appel accepté)
    2  identifiants absents de l'environnement
    3  authentification refusée (401/400 : identifiants incorrects)
    4  appel API refusé (403 : application non abonnée à Judilibre)
    5  autre erreur
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# Permet d'exécuter le script sans PYTHONPATH depuis la racine du projet.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from crim_hebdo.piste import PisteError  # noqa: E402


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def main() -> int:
    client_id = _env("CRIM_HEBDO_CLIENT_ID")
    client_secret = _env("CRIM_HEBDO_CLIENT_SECRET")
    sandbox = _env("DIAG_SANDBOX") == "1"

    if not client_id or not client_secret:
        print("ERREUR : renseigne CRIM_HEBDO_CLIENT_ID et CRIM_HEBDO_CLIENT_SECRET.")
        print(
            "Exemple :\n"
            "  CRIM_HEBDO_CLIENT_ID='...' CRIM_HEBDO_CLIENT_SECRET='...' \\\n"
            "    python3 tools/diag_judilibre.py"
        )
        return 2

    if sandbox:
        token_url = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
        api_url = "https://sandbox-api.piste.gouv.fr"
        env_label = "SANDBOX (données fictives)"
    else:
        token_url = "https://oauth.piste.gouv.fr/api/oauth/token"
        api_url = "https://api.piste.gouv.fr"
        env_label = "PRODUCTION (données réelles)"

    print("=== Environnement :", env_label, "===")
    print("token_url      =", token_url)
    print("api_url        =", api_url)
    print("client_id      =", (client_id[:6] + "…") if len(client_id) > 6 else client_id)
    print("client_secret  =", "***" if client_secret else "(vide)")
    print()

    # --- Étape 1 : authentification OAuth, isolée du reste du code ----------
    print("[1/2] Authentification OAuth…")
    data = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "openid",
        }
    ).encode()
    request = urllib.request.Request(
        token_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("access_token"):
            print("  ✗ Réponse inattendue, pas de access_token :", payload)
            return 3
        print("  ✓ Authentification acceptée (token reçu).")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(f"  ✗ Authentification refusée (HTTP {exc.code}) : {body}")
        text = body
        if "invalid_client" in text:
            print(
                "    → client_id / client_secret non reconnu.\n"
                "      Vérifie : bonne application (prod vs sandbox), secret révélé\n"
                "      et recopié sans espace, secret non régénéré depuis."
            )
        elif "invalid_scope" in text:
            print("    → L'application n'est pas abonnée à Judilibre sur cet environnement.")
        return 3

    # --- Étape 2 : appel /search via le client du projet --------------------
    print("\n[2/2] Appel /search Judilibre (chambre criminelle)…")
    from crim_hebdo.config import Config
    from crim_hebdo.judilibre import JudilibreClient
    from crim_hebdo.piste import PisteClient

    cfg = Config(client_id=client_id, client_secret=client_secret, use_sandbox=sandbox)
    cfg.token_url = token_url
    cfg.api_url = api_url
    http = PisteClient(cfg)
    judi = JudilibreClient(cfg, http)
    try:
        results = judi.search(date_start="2025-01-01", date_end="2025-01-31", publication=None)
        print(f"  ✓ Appel accepté — {len(results)} résultat(s) sur janvier 2025.")
        for item in results[:5]:
            print("    -", item.get("number"), item.get("decision_date"), "| pub:", item.get("publication"))
        if not results and not sandbox:
            print(
                "    (0 résultat en production peut venir de la période ; élargis les\n"
                "     dates ou vérifie chamber=cr / jurisdiction=cc.)"
            )
    except PisteError as exc:
        print("  ✗ Appel refusé :", exc)
        status = getattr(exc, "status", None)
        if status == 403:
            print(
                "    → Authentification OK mais accès Judilibre refusé : l'application\n"
                "      n'est pas (encore) abonnée/habilitée à Judilibre sur cet environnement."
            )
            return 4
        return 5

    print("\nDiagnostic : tout fonctionne pour cet environnement.", end=" ")
    if sandbox:
        print("(Rappel : sandbox = données fictives, pas de vrais inédits.)")
    else:
        print("Tu peux lancer : python3 -m crim_hebdo update --source piste")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
