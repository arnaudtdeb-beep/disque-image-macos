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
    environment = {"PYTHONUNBUFFERED": "1"}
    ca_bundle = os.environ.get("CRIM_HEBDO_CA_BUNDLE")
    if ca_bundle:
        environment["CRIM_HEBDO_CA_BUNDLE"] = ca_bundle
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
        "EnvironmentVariables": environment,
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
    # `launchctl list` prints PID, exit status, then label; labels are not
    # whole-line matches (e.g. "-\t0\tcom.crimhebo.serve").
    return code == 0 and any(
        ligne.split() and ligne.split()[-1] == LABEL
        for ligne in listing.splitlines()
    )


def port_repond(port: int = PORT_DEFAUT, delai: float = 0.5) -> bool:
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=delai) as reponse:  # noqa: S310
            return reponse.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def attendre(port: int = PORT_DEFAUT, secondes: float = 25.0) -> bool:
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
        if est_charge():
            print(
                f"l'ancien agent {LABEL} est toujours chargé ; impossible de le remplacer.",
                file=sys.stderr,
            )
            print(f"État launchd : {launchctl('print', cible())[1]}", file=sys.stderr)
            return 1

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plistlib.dumps(data, sort_keys=True))
    print(f"plist écrit : {PLIST_PATH}")

    # Catch the common launchd EIO case (a missing/non-executable interpreter
    # or working directory) before asking launchd to load the job.
    executable = Path(sys.executable)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        print(f"Python configuré dans le plist est introuvable ou inexécutable : {executable}", file=sys.stderr)
        return 1
    if not ROOT.is_dir():
        print(f"dossier du programme introuvable : {ROOT}", file=sys.stderr)
        return 1

    code, message = launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH))
    if code:
        print(f"chargement impossible : {message}", file=sys.stderr)
        print(f"Python : {sys.executable}", file=sys.stderr)
        print(f"Dossier : {ROOT}", file=sys.stderr)
        print(f"Plist : {PLIST_PATH}", file=sys.stderr)
        if PLIST_PATH.exists():
            print(f"Plist lisible : {os.access(PLIST_PATH, os.R_OK)}", file=sys.stderr)
        print(f"Journal serveur : {ROOT / 'data' / 'logs' / 'serve.err.log'}", file=sys.stderr)
        _code, diagnostic = launchctl("print", cible())
        if diagnostic:
            print(f"État launchd : {diagnostic}", file=sys.stderr)
        print(f"Vérifiez aussi le journal launchd : {ROOT / 'data' / 'logs' / 'serve.err.log'}", file=sys.stderr)
        return 1

    if attendre(port):
        print(f"interface disponible sur http://127.0.0.1:{port}/")
        return 0

    print("l'agent est chargé mais l'interface ne répond pas encore", file=sys.stderr)
    print(f"consulter le journal : tail -20 {data['StandardOutPath']}", file=sys.stderr)
    return 1


def _pids_sur_port(port: int) -> list[int]:
    """PIDs des processus qui écoutent sur `port` (macOS : lsof)."""
    if not shutil.which("lsof"):
        return []
    result = subprocess.run(  # noqa: S603,S607 - lsof figé
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True, text=True,
    )
    pids: list[int] = []
    for ligne in result.stdout.splitlines():
        ligne = ligne.strip()
        if ligne.isdigit():
            pids.append(int(ligne))
    return pids


def _est_notre_serveur(pid: int) -> bool:
    """Vrai si le PID est bien un `crim_hebdo serve` (pas un autre service)."""
    if not shutil.which("ps"):
        return False
    result = subprocess.run(  # noqa: S603,S607 - ps figé
        ["ps", "-o", "command=", "-p", str(pid)],
        capture_output=True, text=True,
    )
    commande = result.stdout.strip()
    # On ne tue QUE nos processus : ligne de commande contenant crim_hebdo.
    return "crim_hebdo" in commande


def liberer_port(port: int) -> int:
    """Arrête un ancien `crim_hebdo serve` qui occuperait déjà `port`.

    Un serveur orphelin (lancé à la main, ou ancien agent encore vivant) fait
    échouer le premier démarrage : kickstart/bootstrap ne peuvent pas prendre
    un port déjà tenu. On l'arrête proprement pour que le premier essai
    réussisse. Ne touche jamais à un autre logiciel.
    """
    libere = 0
    for pid in _pids_sur_port(port):
        if pid == os.getpid() or not _est_notre_serveur(pid):
            continue
        try:
            os.kill(pid, 15)  # SIGTERM : arrêt propre
        except OSError:
            continue
        libere += 1
    if libere:
        # Laisse au processus le temps de rendre le port.
        limite = time.monotonic() + 3.0
        while time.monotonic() < limite and _pids_sur_port(port):
            time.sleep(0.2)
    return libere


def _lancer_agent() -> tuple[int, str]:
    """Tente kickstart si l'agent est chargé, sinon bootstrap."""
    if est_charge():
        return launchctl("kickstart", "-k", cible())
    return launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH))


def demarrer(port: int, attendre_port: bool = True) -> int:
    """Démarre l'agent et s'assure que l'interface répond.

    Auto-réparateur : si l'agent est présent mais que l'interface ne répond
    pas (agent chargé mais mort, plist pointant vers un Python disparu après
    une mise à jour de macOS, etc.), on réinstalle l'agent (bootout +
    bootstrap) et on réessaie une fois. Cela évite d'avoir à supprimer un
    marqueur « premier lancement » pour que le serveur reparte après un
    redémarrage de la machine.
    """
    if not PLIST_PATH.exists():
        return installer(port, dry_run=False)

    # Un ancien serveur orphelin peut tenir le port : on le libère d'abord,
    # sinon le premier essai échoue et il faut relancer une seconde fois.
    libere = liberer_port(port)
    if libere:
        print(f"ancien serveur arrêté sur le port {port} ({libere} processus).", file=sys.stderr)

    code, message = _lancer_agent()
    if code == 0 and (not attendre_port or attendre(port)):
        return 0

    # Échec (code non nul ou interface muette) : on répare en réinstallant.
    print("démarrage direct insuffisant, réinstallation de l'agent…", file=sys.stderr)
    install_code = installer(port, dry_run=False)
    if install_code == 0:
        return 0

    if code:
        print(f"démarrage impossible : {message}", file=sys.stderr)
    if attendre_port and not port_repond(port):
        print("l'interface ne répond pas", file=sys.stderr)
        print(
            f"journal : tail -20 {ROOT / 'data' / 'logs' / 'serve.err.log'}",
            file=sys.stderr,
        )
    return 1


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
