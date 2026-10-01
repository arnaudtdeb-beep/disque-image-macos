"""Installation guidée de la veille chambre criminelle.

Regroupe en une seule commande tout ce qu'il faut faire après avoir copié le
dossier : vérification de l'environnement, création des dossiers de données,
contrôle de la configuration, première veille réelle et planification
hebdomadaire (launchd sur macOS, cron sur Linux).

La source par défaut est DILA : aucun compte, aucune clé, aucun abonnement.

Usage :
    python3 tools/install.py                  # installation guidée
    python3 tools/install.py --yes            # sans aucune question
    python3 tools/install.py --skip-update    # ne télécharge rien
    python3 tools/install.py --no-schedule    # ne programme pas la veille
    python3 tools/install.py --dry-run        # affiche sans rien modifier
    python3 tools/install.py --uninstall      # retire la planification
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.install_launchd import LABEL, PLIST_PATH  # noqa: E402

CRON_MARK_BEGIN = "# >>> crim-hebdo (veille chambre criminelle)"
CRON_MARK_END = "# <<< crim-hebdo"
MIN_PYTHON = (3, 9)
PORTS_DEFAUT = 8765


def titre(etape: int, total: int, texte: str) -> None:
    print(f"\n[{etape}/{total}] {texte}")
    print("-" * (len(texte) + 10))


def ok(texte: str) -> None:
    print(f"  ✓ {texte}")


def info(texte: str) -> None:
    print(f"    {texte}")


def warn(texte: str) -> None:
    print(f"  ! {texte}")


def echec(texte: str) -> int:
    print(f"  ✗ {texte}", file=sys.stderr)
    return 1


def demander(question: str, defaut: bool, oui: bool) -> bool:
    """Pose une question, ou renvoie le défaut si --yes ou stdin non interactif."""
    if oui or not sys.stdin.isatty():
        return defaut
    suffixe = " [O/n] " if defaut else " [o/N] "
    try:
        reponse = input(f"  {question}{suffixe}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return defaut
    if not reponse:
        return defaut
    return reponse in ("o", "oui", "y", "yes")


def lancer(*args: str, dry_run: bool) -> int:
    """Lance `python3 -m crim_hebdo <args>` depuis la racine du projet."""
    commande = [sys.executable, "-m", "crim_hebdo", *args]
    if dry_run:
        info(" ".join(["python3", "-m", "crim_hebdo", *args]))
        return 0
    result = subprocess.run(commande, cwd=str(ROOT))  # noqa: S603 - args figés
    return result.returncode


# --------------------------------------------------------------------------


def etape_environnement() -> int:
    version = sys.version_info
    if version[:2] < MIN_PYTHON:
        return echec(
            f"Python {version.major}.{version.minor} est trop ancien. "
            f"Il faut {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou plus récent."
        )
    ok(f"Python {version.major}.{version.minor}.{version.micro} ({sys.executable})")

    if platform.system() == "Darwin":
        base = platform.mac_ver()[0]
        if int(base.split(".")[0]) < 11 and version[:2] < (3, 10):
            warn(
                f"macOS {base} fournit un Python {version.major}.{version.minor}. "
                "Surveillez les erreurs de syntaxe ; `brew install python` est plus sûr."
            )
    return 0


def etape_fichiers() -> int:
    attendus = {
        "crim_hebdo/__init__.py": "le module",
        "crim_hebdo/cli.py": "la ligne de commande",
        "web/index.html": "l'interface",
        "web/app.js": "le script de l'interface",
    }
    manquants = [nom for nom in attendus if not (ROOT / nom).is_file()]
    if manquants:
        return echec("fichiers manquants : " + ", ".join(manquants))
    ok(f"les {len(attendus)} fichiers essentiels sont présents")
    return 0


def etape_dossiers(dry_run: bool) -> int:
    dossiers = ["data", "data/cache", "data/logs", "data/rapports"]
    for nom in dossiers:
        if dry_run:
            info(f"mkdir {nom}/")
            continue
        (ROOT / nom).mkdir(parents=True, exist_ok=True)
    ok("dossiers de données prêts : " + ", ".join(dossiers))
    return 0


def etape_configuration(dry_run: bool) -> int:
    cible = ROOT / "config.json"
    if cible.exists():
        ok(f"configuration existante : {cible.name}")
        return 0
    if dry_run:
        info("écriture de config.json (source DILA, sans identifiant)")
        return 0
    result = lancer("init-config", dry_run=False)
    if result:
        return echec("écriture de la configuration impossible")
    return 0


def etape_controle(dry_run: bool) -> int:
    code = lancer("check", dry_run=dry_run)
    if dry_run:
        return 0
    if code:
        warn("l'accès aux données ouvertes n'a pas abouti")
        return 0
    ok("accès aux données ouvertes confirmé")
    return 0


def etape_veille(sauter: bool, oui: bool, dry_run: bool) -> int:
    if sauter:
        info("ignorée (--skip-update)")
        return 0
    if not dry_run and not demander("Télécharger la première veille maintenant ?", True, oui):
        info("ignorée")
        return 0
    info("premier téléchargement : quelques minutes selon la connexion")
    code = lancer("update", dry_run=dry_run)
    if code:
        warn("la veille n'a pas abouti ; relancez `python3 -m crim_hebdo update` plus tard")
        return 0
    if not dry_run:
        ok("veille enregistrée")
    return 0


def _cron_ligne(heure: int, minute: int) -> str:
    return (
        f"{minute} {heure} * * 1 cd {ROOT} && "
        f"{sys.executable} -m crim_hebdo update >> {ROOT}/data/logs/veille.log 2>&1"
    )


def _cron_ajouter(actuel: str, ligne: str) -> str:
    """Ajoute le bloc encadré en fin de crontab, sans le dupliquer."""
    if CRON_MARK_BEGIN in actuel:
        return actuel
    prefixe = actuel if actuel.endswith("\n") or not actuel else actuel + "\n"
    return f"{prefixe}\n{CRON_MARK_BEGIN}\n{ligne}\n{CRON_MARK_END}\n"


def _cron_retirer(actuel: str) -> str:
    """Retire le bloc encadré et toute ligne résiduelle du projet."""
    dans_bloc = False
    restant: list[str] = []
    for ligne in actuel.splitlines():
        if CRON_MARK_BEGIN in ligne:
            dans_bloc = True
            continue
        if CRON_MARK_END in ligne:
            dans_bloc = False
            continue
        if dans_bloc or "crim_hebdo" in ligne:
            continue
        restant.append(ligne)
    if not any(ligne.strip() for ligne in restant):
        return ""
    return "\n".join(restant).strip("\n") + "\n"


def etape_cron(heure: int, minute: int, dry_run: bool, oui: bool) -> int:
    ligne = _cron_ligne(heure, minute)
    if dry_run:
        info(f"crontab += {ligne}")
        return 0
    if not shutil.which("crontab"):
        warn("commande `crontab` absente : ajoutez la ligne manuellement")
        info(ligne)
        return 0
    if not demander(f"Programmer la veille chaque lundi à {heure:02d} h {minute:02d} (cron) ?", True, oui):
        info("non programmée")
        return 0

    actuel = subprocess.run(  # noqa: S603,S607 - crontab du système
        ["crontab", "-l"], capture_output=True, text=True
    ).stdout
    if CRON_MARK_BEGIN in actuel:
        info("déjà programmée")
        return 0
    if not actuel.strip():
        warn("votre crontab est vide et votre table est peut-être inactive")

    result = subprocess.run(  # noqa: S603 - "crontab -" et texte contrôlé
        ["crontab", "-"], input=_cron_ajouter(actuel, ligne), text=True
    )
    if result.returncode:
        warn("écriture de la crontab refusée ; ajoutez la ligne manuellement")
        info(ligne)
        return 0
    ok(f"veille programmée chaque lundi à {heure:02d} h {minute:02d} (cron)")
    return 0


def etape_planification(dry_run: bool, oui: bool, heure: int, minute: int) -> int:
    systeme = platform.system()
    if systeme == "Darwin":
        from tools import install_launchd

        if dry_run:
            info(f"python3 tools/install_launchd.py --heure {heure} --minute {minute}")
            return 0
        if not demander(f"Programmer la veille chaque lundi à {heure:02d} h {minute:02d} (launchd) ?", True, oui):
            info("non programmée")
            return 0
        code = install_launchd.install(heure, minute, dry_run=False)
        if code:
            warn("la planification n'a pas abouti")
            info(f"pour la retryer : python3 tools/install_launchd.py --heure {heure} --minute {minute}")
            if PLIST_PATH.exists():
                ok(f"plist prêt : {PLIST_PATH}")
        return 0

    if systeme == "Linux":
        return etape_cron(heure, minute, dry_run, oui)

    info(f"planification automatique non gérée sur {systeme}")
    info("ajoutez manuellement :")
    info(_cron_ligne(heure, minute))
    return 0


def desinstaller() -> int:
    if PLIST_PATH.exists() and platform.system() == "Darwin":
        from tools import install_launchd

        return install_launchd.uninstall()

    crontab = shutil.which("crontab")
    if not crontab:
        return echec("aucune planification installée")
    actuel = subprocess.run(  # noqa: S603,S607
        ["crontab", "-l"], capture_output=True, text=True
    ).stdout
    restant = _cron_retirer(actuel)
    if restant == actuel:
        info("rien à retirer de la crontab")
        return 0
    # Une crontab devenue vide doit être supprimée ainsi : « crontab -rm »
    # est plus sûr que de passer une chaîne vide à « crontab - ».
    result = subprocess.run(  # noqa: S603
        ["crontab", "-rm"] if not restant.strip() else ["crontab", "-"],
        input=restant,
        text=True,
    )
    if result.returncode:
        return echec("impossible de modifier la crontab")
    ok("planification retirée")
    return 0


def recapitulatif(schedule: bool, port: int, update: bool) -> None:
    print("\n" + "=" * 62)
    print("Installation terminée.")
    print("=" * 62)
    print(f"\nPour ouvrir l'interface :\n\n    python3 -m crim_hebdo serve\n")
    print(f"    puis http://127.0.0.1:{port}/ dans votre navigateur.")
    if not update:
        print("\nLes arrêts ne sont pas encore téléchargés :\n")
        print("    python3 -m crim_hebdo update")
    if schedule:
        print("\nLa veille se met à jour automatiquement chaque lundi au matin.")
        print(f"Journal : tail -f {ROOT}/data/logs/veille.log")
    else:
        print("\nPlanification désactivée. Pour l'activer plus tard :")
        print("    python3 tools/install.py")
    print("\nPour retirer la planification :\n\n    python3 tools/install.py --uninstall\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--yes", "-y", action="store_true", help="ne poser aucune question")
    parser.add_argument("--skip-update", action="store_true", help="ne pas télécharger les arrêts")
    parser.add_argument("--no-schedule", action="store_true", help="ne pas planifier la veille")
    parser.add_argument("--dry-run", action="store_true", help="afficher sans rien modifier")
    parser.add_argument("--uninstall", action="store_true", help="retirer la planification")
    parser.add_argument("--heure", type=int, default=7, help="heure de la veille (défaut 7)")
    parser.add_argument("--minute", type=int, default=30, help="minute (défaut 30)")
    parser.add_argument("--port", type=int, default=PORTS_DEFAUT, help="port de l'interface")
    args = parser.parse_args()

    if args.uninstall:
        return desinstaller()

    print("Installation de la veille chambre criminelle")
    print(f"Dossier : {ROOT}")
    print(f"Système : {platform.system()} {platform.release()}")
    total = 7 if not args.no_schedule else 6
    etape = 0

    etape += 1
    titre(etape, total, "Environnement")
    code = etape_environnement()
    if code:
        return code

    etape += 1
    titre(etape, total, "Fichiers du projet")
    code = etape_fichiers()
    if code:
        return code

    etape += 1
    titre(etape, total, "Dossiers de données")
    etape_dossiers(args.dry_run)

    etape += 1
    titre(etape, total, "Configuration")
    etape_configuration(args.dry_run)

    etape += 1
    titre(etape, total, "Accès aux données ouvertes")
    etape_controle(args.dry_run)

    etape += 1
    titre(etape, total, "Première veille")
    etape_veille(args.skip_update, args.yes, args.dry_run)

    if not args.no_schedule:
        etape += 1
        titre(etape, total, "Planification hebdomadaire")
        etape_planification(args.dry_run, args.yes, args.heure, args.minute)

    if not args.dry_run:
        recapitulatif(not args.no_schedule, args.port, not args.skip_update)
    else:
        print("\nSimulation terminée : rien n'a été modifié.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())