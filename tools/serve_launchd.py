"""Lance l'interface web locale en arrière-plan sur macOS, via launchd.

Ce module est le pendant de `install_launchd` pour le serveur : il écrit un
deuxième agent (`com.crimhebo.serve`) qui démarre `crim_hebdo serve` à chaque
connexion et se relance sans intervention. L'interface reste ainsi accessible
sans passer par un Terminal, et survit à la fermeture de la fenêtre.

Il est aussi pilotable depuis les lanceurs double-clic livrés dans le DMG.

Usage :
    python3 tools/serve_launchd.py install            # écrit et charge l'agent
    python3 tools/serve_launchd.py install --port 8765
    python3 tools/serve_launchd.py start              # démarre ou redémarre
    python3 tools/serve_launchd.py stop               # arrête
    python3 tools/serve_launchd.py status             # état lisible
    python3 tools/serve_launchd.py uninstall          # arrête et supprime
    python3 tools/serve_launchd.py --dry-run          # affiche sans installer
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.crimhebo.serve"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
MIN_PYTHON = (3, 9)
PORT_DEFAUT = 8765


def build_plist(port: int = PORT_DEFAUT) -> dict:
    """Construit le plist du serveur avec les chemins réels de l'installation."""
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LABEL,
        # `--no-browser` : l'agent tourne sans fenêtre ni utilisateur présent,
        # c'est le lanceur double-clic qui ouvre le navigateur.
        "ProgramArguments": [
            sys.executable,
            "-m",
            "crim_hebdo",
            "serve",
            "--port",
            str(port),
            "--no-browser",
        ],
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        # `RunAtLoad` : l'interface est disponible dès la première connexion,
        # sans rien demander à l'utilisateur. Pas de `KeepAlive` : un plantage
        # ne doit pas provoquer une boucle de redémarrages.
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "serve.log"),
        "StandardErrorPath": str(logs / "serve.err.log"),
    }


def launchctl(*args: str) -> tuple[int, str]:
    if not shutil.which("launchctl"):
        # Hors macOS, `status` doit rester consultable pour diagnostiquer.
        return 127, "launchctl est absent de cette machine"
    result = subprocess.run(  # noqa: S603 - Commande launchd figée
        ["launchctl", *args], capture_output=True, text=True
    )
    return result.returncode, (result.stderr or result.stdout).strip()


def cible() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


def est_charge() -> bool:
    code, listing = launchctl("list")
    return code == 0 and LABEL in listing.splitlines()


def port_repond(port: int = PORT_DEFAUT, delai: float = 0.5) -> bool:
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=delai) as reponse:  # noqa: S310
            return reponse.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def attendre(port: int = PORT_DEFAUT, secondes: float = 15.0) -> bool:
    """Attend que l'interface réponde, le temps que Python démarre."""
    limite = time.monotonic() + secondes
    while time.monotonic() < limite:
        if port_repond(port):
            return True
        time.sleep(0.25)
    return False


def _controle_python() -> int:
    if sys.version_info < MIN_PYTHON:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(f"Python {version} est trop ancien : 3.9 minimum.", file=sys.stderr)
        return 2
    return 0


def installer(port: int, dry_run: bool) -> int:
    code = _controle_python()
    if code:
        return code

    data = build_plist(port)
    if dry_run:
        print(f"# destination : {PLIST_PATH}\n")
        print(plistlib.dumps(data, sort_keys=True).decode())
        return 0

    if sys.platform != "darwin":
        print(
            f"Installation impossible hors macOS (plateforme : {sys.platform}).",
            file=sys.stderr,
        )
        print(
            "Partout ailleurs, le serveur se lance directement :\n"
            f"    cd {ROOT} && python3 -m crim_hebdo serve",
            file=sys.stderr,
        )
        return 2

    # Un agent déjà chargé doit être déchargé avant d'être remplacé.
    if PLIST_PATH.exists() or est_charge():
        launchctl("bootout", cible())

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plistlib.dumps(data, sort_keys=True))
    print(f"plist écrit : {PLIST_PATH}")

    code, message = launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH))
    if code:
        print(f"chargement impossible : {message}", file=sys.stderr)
        return 1

    if attendre(port):
        print(f"interface disponible sur http://127.0.0.1:{port}/")
        return 0

    print("l'agent est chargé mais l'interface ne répond pas encore", file=sys.stderr)
    print(f"consulter le journal : tail -20 {data['StandardOutPath']}", file=sys.stderr)
    return 1


def demarrer(port: int, attendre_port: bool = True) -> int:
    """Démarre l'agent, ou le redémarre s'il tourne déjà."""
    if not PLIST_PATH.exists():
        return installer(port, dry_run=False)

    if est_charge():
        code, message = launchctl("kickstart", "-k", cible())
    else:
        code, message = launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH))
    if code:
        print(f"démarrage impossible : {message}", file=sys.stderr)
        return 1

    if attendre_port and not attendre(port):
        print("l'interface ne répond pas", file=sys.stderr)
        print(f"journal : tail -20 {ROOT / 'data' / 'logs' / 'serve.log'}", file=sys.stderr)
        return 1
    return 0


def arreter() -> int:
    if not est_charge():
        print("le serveur n'est pas démarré")
    else:
        launchctl("bootout", cible())
        print("serveur arrêté")
    print(f"il redémarrera à la prochaine connexion (plist : {PLIST_PATH})")
    return 0


def desinstaller() -> int:
    if est_charge():
        launchctl("bootout", cible())
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        print(f"supprimé : {PLIST_PATH}")
    else:
        print("plist déjà absent")
    return 0


def status(port: int = PORT_DEFAUT) -> int:
    if est_charge():
        print(f"serveur : démarré (agent {LABEL})")
        print(f"interface : http://127.0.0.1:{port}/")
    elif PLIST_PATH.exists():
        print(f"serveur : arrêté (agent installé : {PLIST_PATH})")
    else:
        print("serveur : non installé")
    return 0 if est_charge() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["install", "start", "stop", "status", "uninstall"],
    )
    parser.add_argument("--port", type=int, default=PORT_DEFAUT)
    parser.add_argument(
        "--sans-attente",
        action="store_true",
        help="ne pas attendre que l'interface réponde",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.action == "install":
        return installer(args.port, args.dry_run)
    if args.action == "start":
        return demarrer(args.port, attendre_port=not args.sans_attente)
    if args.action == "stop":
        return arreter()
    if args.action == "uninstall":
        return desinstaller()
    return status(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
