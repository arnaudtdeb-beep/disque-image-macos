"""Construit l'image disque (DMG) macOS de la veille chambre criminelle.

L'image contient deux lanceurs double-clic, un mode d'emploi et le programme.
Aucun code n'est compilé ni signé : il n'y a donc rien qui puisse être refusé
par macOS à l'ouverture, contrairement à une application non signée.

La construction se fait en deux temps :

1. l'assemblage (`stage`) ne dépend que de la bibliothèque standard et
   fonctionne sur n'importe quel système — c'est donc ce que les tests
   vérifient ;
2. la création du fichier `.dmg` appelle `hdiutil` via dmgbuild et exige
   macOS. Sur Linux, `--stage-only` permet de tout préparer sans l'image.

Usage :
    python3 tools/build_dmg.py --stage-only            # Linux : assemblage seul
    python3 tools/build_dmg.py --stage-only -o dist    # dossier de sortie
    python3 tools/build_dmg.py                         # macOS : le .dmg
    python3 tools/build_dmg.py --version 1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging" / "macos"
PAYLOAD = "crim-hebdo"
VOLUME = "Veille criminelle"
LAUNCH = "Veille criminelle.command"
STOP = "Arrêter la veille.command"
README_MAC = "Lisez-moi.txt"
# Dossiers et fichiers copiés dans l'image. `data/` en est volontairement absent :
# les archives téléchargées pèsent 76 Mo et n'ont rien à faire dans une image
# distribuée. Les données de l'utilisateur sont créées dans `~/crim-hebdo`.
A_COPIER = ("crim_hebdo", "web", "tools", "samples", "tests")
A_COPIER_FICHIERS = ("config.example.json", "README.md")
EXCLUS = {"__pycache__", ".git", ".DS_Store", "data", ".pytest_cache"}
EXCLUS_FICHIERS = {".env", ".gitignore"}
SUFFIXES_EXCLUS = (".pyc", ".pyo", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm")


def version_lisible(descrit: str) -> str:
    """Transforme la sortie de `git describe` en version acceptable dans un nom.

    Sans tag, `git describe` ne rend qu'un condensé : le nom du fichier `.dmg`
    porterait alors un identifiant de commit au lieu d'une version.
    """
    texte = descrit.strip()
    if not texte:
        return "0.0.0-dev"
    tete = texte.removeprefix("v").split("-", 1)[0].split("+", 1)[0]
    majeure, _, mineure = tete.partition(".")
    if majeure.isdigit() and mineure[:1].isdigit():
        return texte.removeprefix("v")
    return f"0.0.0-dev+{texte}"


def version_par_defaut() -> str:
    """Version du dépôt si elle existe, sinon une version de développement lisible."""
    try:
        resultat = subprocess.run(  # noqa: S603,S607 - git, commande figée
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
    except OSError:
        return "0.0.0-dev"
    if resultat.returncode:
        return "0.0.0-dev"
    return version_lisible(resultat.stdout)


def est_exclu(nom: str) -> bool:
    return nom in EXCLUS or nom in EXCLUS_FICHIERS or nom.endswith(SUFFIXES_EXCLUS)


def copier(src: Path, dest: Path) -> None:
    """Copie un dossier ou un fichier en écartant ce qui n'a pas sa place."""
    if src.is_dir():
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(*EXCLUS, *EXCLUS_FICHIERS, *SUFFIXES_EXCLUS),
        )
    else:
        shutil.copy2(src, dest)


def empreinte(dossier: Path) -> str:
    """Empreinte stable du contenu, pour détecter les mises à jour du programme."""
    hache = hashlib.sha256()
    for chemin in sorted(p for p in dossier.rglob("*") if p.is_file()):
        relatif = chemin.relative_to(dossier).as_posix()
        if est_exclu(chemin.name) or relatif == "VERSION":
            continue
        hache.update(relatif.encode())
        hache.update(chemin.read_bytes())
    return hache.hexdigest()[:16]


def stage(dest: Path, version: str) -> Path:
    """Assemble le contenu de l'image dans `dest` et renvoie sa racine."""
    racine = dest.resolve()
    # `rmtree` est exécuté ci-dessous : on refuse un dossier qui contient le
    # dépôt lui-même, plutôt que de découvrir l'erreur trop tard.
    if racine == ROOT or racine == ROOT.parent or (racine / ".git").exists():
        raise SystemExit(f"refus de vider ce dossier : {racine}")
    if racine.exists():
        shutil.rmtree(racine)
    racine.mkdir(parents=True)

    for nom in A_COPIER:
        copier(ROOT / nom, racine / PAYLOAD / nom)
    for nom in A_COPIER_FICHIERS:
        copier(ROOT / nom, racine / PAYLOAD / nom)

    for nom in (LAUNCH, STOP, README_MAC):
        copier(PACKAGING / nom, racine / nom)
    # Double-clic = fichier exécutable. Le bit doit exister avant `ditto`.
    for nom in (LAUNCH, STOP):
        chemin = racine / nom
        chemin.chmod(chemin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # VERSION porte la version et l'empreinte : le lanceur compare les deux
    # fichiers avec `cmp` pour savoir s'il doit réinstaller.
    (racine / PAYLOAD / "VERSION").write_text(f"{version} {empreinte(racine / PAYLOAD)}\n")
    return racine


def fichiers_image(racine: Path) -> list[str]:
    entrees = sorted(p for p in racine.iterdir() if p.is_file())
    # Le dossier du programme est ajouté puis masqué : il ne sert qu'au
    # premier lancement, une fois la copie faite dans le dossier personnel.
    entrees.append(racine / PAYLOAD)
    return [str(p) for p in entrees]


def reglages_dmgbuild(racine: Path) -> dict:
    """Réglages de mise en page de la fenêtre de l'image disque."""
    return {
        "format": "UDBZ",
        "filesystem": "HFS+",
        "compression_level": 9,
        "files": fichiers_image(racine),
        "symlinks": {},
        "hide": [PAYLOAD],
        # dmgbuild n'accepte les couleurs hexadécimales qu'en minuscules.
        "background": "#f4f4f2",
        "window_rect": ((140, 120), (620, 420)),
        "default_view": "icon-view",
        "show_status_bar": False,
        "show_toolbar": False,
        "show_pathbar": False,
        "show_sidebar": False,
        "icon_size": 96.0,
        "text_size": 14.0,
        "icon_locations": {
            LAUNCH: (180, 200),
            STOP: (180, 350),
            README_MAC: (430, 200),
        },
    }


def construire_dmg(racine: Path, sortie: Path) -> Path:
    """Crée le fichier `.dmg`. Nécessite macOS (`hdiutil`)."""
    if sys.platform != "darwin":
        print(
            "La création du .dmg exige macOS : `hdiutil` est absent de cette "
            "machine.\n"
            "Utilisez `--stage-only` pour assembler le contenu, puis "
            "construisez l'image sur un Mac ou sur GitHub Actions.",
            file=sys.stderr,
        )
        return sortie / "echec.dmg"

    try:
        from dmgbuild.core import build_dmg
    except ImportError as erreur:
        print(
            "Le module `dmgbuild` est nécessaire : pip install dmgbuild",
            file=sys.stderr,
        )
        return sortie / "echec.dmg"

    sortie.mkdir(parents=True, exist_ok=True)
    chemin = sortie / f"Veille-criminelle-{emprise_version(racine)}.dmg"
    if chemin.exists():
        chemin.unlink()
    build_dmg(str(chemin), VOLUME, settings=reglages_dmgbuild(racine))
    return chemin


def emprise_version(racine: Path) -> str:
    """Nom de version lisible, repris du fichier VERSION de l'assemblage."""
    fichier = racine / PAYLOAD / "VERSION"
    if fichier.is_file():
        return fichier.read_text().split()[0]
    return "0.0.0-dev"


def verifier_image(chemin: Path) -> bool:
    """Monte l'image et vérifie que les lanceurs sont toujours exécutables."""
    point = Path("/tmp") / f"crimhebo-verify-{os.getpid()}"
    resultat = subprocess.run(  # noqa: S603,S607 - hdiutil, commande figée
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(point), str(chemin)],
        capture_output=True,
        text=True,
    )
    if resultat.returncode:
        print(f"montage impossible : {resultat.stderr.strip()}", file=sys.stderr)
        return False
    try:
        for nom in (LAUNCH, STOP):
            mode = (point / nom).stat().st_mode
            if not mode & stat.S_IXUSR:
                print(f"{nom} n'est pas exécutable dans l'image", file=sys.stderr)
                return False
        if (point / PAYLOAD / "crim_hebdo" / "cli.py").is_file():
            print("contenu de l'image vérifié")
            return True
        print("programme absent de l'image", file=sys.stderr)
        return False
    finally:
        subprocess.run(  # noqa: S603,S607 - hdiutil, commande figée
            ["hdiutil", "detach", str(point)], capture_output=True, text=True
        )
        if point.exists():
            shutil.rmtree(point, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None, help="version inscrite dans VERSION")
    parser.add_argument("-o", "--sortie", default="dist", help="dossier de sortie (défaut dist)")
    parser.add_argument("--stage-only", action="store_true", help="assembler sans créer le .dmg")
    parser.add_argument("--stage", default=None, help="dossier d'assemblage (défaut <sortie>/stage)")
    args = parser.parse_args()

    version = args.version or version_par_defaut()
    racine = stage(Path(args.stage or Path(args.sortie) / "stage"), version)

    taille = sum(p.stat().st_size for p in racine.rglob("*") if p.is_file())
    print(f"assemblage : {racine}")
    print(f"version    : {version}")
    print(f"empreinte  : {empreinte(racine / PAYLOAD)}")
    print(f"poids      : {taille / 1024:.0f} Ko")
    if args.stage_only:
        return 0

    chemin = construire_dmg(racine, Path(args.sortie))
    if chemin.suffix != ".dmg" or not chemin.is_file():
        return 2
    print(f"image      : {chemin}")
    print(f"poids      : {chemin.stat().st_size / 1024 / 1024:.1f} Mo")
    if sys.platform == "darwin" and not verifier_image(chemin):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
