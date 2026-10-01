"""Installe la veille hebdomadaire sur macOS via launchd.

Le script remplit un modèle de plist avec le dossier du projet et
l'interpréteur Python réellement utilisés, l'écrit dans
`~/Library/LaunchAgents/`, puis charge le job auprès de launchd.

Usage :
    python3 tools/install_launchd.py                 # installe et charge
    python3 tools/install_launchd.py --uninstall     # décharge et supprime
    python3 tools/install_launchd.py --dry-run       # affiche, n'installe rien
    python3 tools/install_launchd.py --heure 6 --minute 45

Aucune configuration n'est nécessaire : la source DILA ne demande ni compte
ni clé. Le job écrit les rapports dans <projet>/data/rapports/ et un journal
dans <projet>/data/logs/veille.log.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.crimhebo.veille"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(hour: int, minute: int) -> dict:
    """Construit le plist avec les chemins réels de cette installation."""
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "crim_hebdo", "update"],
        "WorkingDirectory": str(ROOT),
        # DILA est en Python pur : aucun PYTHONPATH n'est nécessaire puisque le
        # module est dans le dossier de travail.
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StartCalendarInterval": {"Weekday": 1, "Hour": hour, "Minute": minute},
        "RunAtLoad": False,
        "StandardOutPath": str(logs / "veille.log"),
        "StandardErrorPath": str(logs / "veille.err.log"),
        "ProcessType": "Background",
    }


def launchctl(*args: str) -> tuple[int, str]:
    result = subprocess.run(  # noqa: S603 - Commande launchd figée
        ["launchctl", *args], capture_output=True, text=True
    )
    return result.returncode, (result.stderr or result.stdout).strip()


def uninstall() -> int:
    code, message = launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    # bootout échoue si le job n'est pas chargé : ce n'est pas une erreur ici.
    print("déchargement : ok" if not code else f"déchargement : {message or 'rien à décharger'}")
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        print(f"supprimé : {PLIST_PATH}")
    else:
        print("plist déjà absent")
    return 0


def install(hour: int, minute: int, dry_run: bool) -> int:
    if sys.version_info < (3, 9):
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(f"Python {version} est trop ancien : 3.9 minimum.", file=sys.stderr)
        return 2

    data = build_plist(hour, minute)
    cible = PLIST_PATH
    if dry_run:
        print(f"# destination : {cible}\n")
        print(plistlib.dumps(data, sort_keys=True).decode())
        return 0

    if sys.platform != "darwin":
        print(f"Installation impossible hors macOS (plateforme : {sys.platform}).", file=sys.stderr)
        print("Sous Linux, utilisez une tâche cron : voir la section 6 du README.", file=sys.stderr)
        return 2

    # Un job déjà chargé doit être déchargé avant d'être remplacé.
    if cible.exists():
        launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")

    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(plistlib.dumps(data, sort_keys=True))
    print(f"plist écrit : {cible}")

    code, message = launchctl("bootstrap", f"gui/{os.getuid()}", str(cible))
    if code:
        print(f"chargement impossible : {message}", file=sys.stderr)
        print("Si le job était déjà chargé, déchargez-le d'abord avec --uninstall.", file=sys.stderr)
        return 1

    listed, listing = launchctl("list")
    if LABEL in listing:
        print(f"job chargé : {LABEL}")
    else:
        print(f"job écrit mais absent de `launchctl list` :\n{listing}", file=sys.stderr)
        return 1

    print(f"\nveille planifiée chaque lundi à {hour:02d}:{minute:02d}")
    print(f"déclencher maintenant : launchctl start gui/{os.getuid()}/{LABEL}")
    print(f"consulter le journal : tail -20 {data['StandardOutPath']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heure", type=int, default=7, help="heure de la veille (défaut 7)")
    parser.add_argument("--minute", type=int, default=30, help="minute (défaut 30)")
    parser.add_argument("--uninstall", action="store_true", help="décharge et supprime le job")
    parser.add_argument("--dry-run", action="store_true", help="affiche le plist sans installer")
    args = parser.parse_args()

    if args.uninstall:
        return uninstall()
    return install(args.heure, args.minute, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())