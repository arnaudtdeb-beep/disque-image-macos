"""Tests hors-ligne de l'image disque macOS et des lanceurs double-clic.

Aucun accès réseau, aucun appel à `launchctl` : l'assemblage est produit dans
un dossier temporaire, le plist est vérifié en mémoire, et les scripts shell
sont analysés sans être exécutés.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_dmg as dmg_mod  # noqa: E402
import serve_launchd as serve_mod  # noqa: E402

LANCEUR = "Veille criminelle.command"
ARRET = "Arrêter la veille.command"
LISEZMOI = "Lisez-moi.txt"


@contextlib.contextmanager
def silencieux():
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        yield tampon


class TestLanceursDuDepot(unittest.TestCase):
    """Les trois fichiers livrés dans l'image doivent être utilisables tels quels."""

    def setUp(self):
        self.lanceur = (dmg_mod.PACKAGING / LANCEUR).read_text(encoding="utf-8")
        self.arret = (dmg_mod.PACKAGING / ARRET).read_text(encoding="utf-8")

    def test_fichiers_presents(self):
        for nom in (LANCEUR, ARRET, LISEZMOI):
            with self.subTest(fichier=nom):
                self.assertTrue((dmg_mod.PACKAGING / nom).is_file())

    def test_executables(self):
        # Sans le bit d'exécution, un double-clic est refusé par le Finder.
        for nom in (LANCEUR, ARRET):
            with self.subTest(fichier=nom):
                chemin = dmg_mod.PACKAGING / nom
                self.assertTrue(chemin.stat().st_mode & 0o111, f"{nom} n'est pas exécutable")

    def test_syntaxe_shell_valide(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash absent")
        for nom in (LANCEUR, ARRET):
            with self.subTest(fichier=nom):
                resultat = subprocess.run(
                    [bash, "-n", str(dmg_mod.PACKAGING / nom)], capture_output=True, text=True
                )
                self.assertEqual(resultat.returncode, 0, resultat.stderr)

    def test_shebang_bash(self):
        for nom in (LANCEUR, ARRET):
            with self.subTest(fichier=nom):
                premiere = (dmg_mod.PACKAGING / nom).read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(premiere, "#!/bin/bash")

    def test_interrompt_en_entree_ferme(self):
        # Un `read` sans entrée ne doit pas laisser le Terminal bloqué.
        self.assertIn("read -r _", self.lanceur)
        self.assertIn("|| break", self.lanceur)

    def test_cherche_un_python_suffisant(self):
        self.assertIn("sys.version_info >= (3, 9)", self.lanceur)
        for chemin in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3"):
            with self.subTest(chemin=chemin):
                self.assertIn(chemin, self.lanceur)

    def test_appelle_les_outils_du_projet(self):
        self.assertIn("tools/install.py", self.lanceur)
        for nom, texte in ((LANCEUR, self.lanceur), (ARRET, self.arret)):
            with self.subTest(fichier=nom):
                self.assertIn("tools/serve_launchd.py", texte)

    def test_ouvre_le_navigateur(self):
        self.assertIn("open \"$URL\"", self.lanceur)
        self.assertIn("http://127.0.0.1:$PORT/", self.lanceur)

    def test_ne_depend_dun_chemin_de_developpement(self):
        for interdit in ("/home/", "/Users/", "C:\\", str(ROOT)):
            with self.subTest(interdit=interdit):
                for nom, texte in ((LANCEUR, self.lanceur), (ARRET, self.arret)):
                    self.assertNotIn(interdit, texte, f"{nom} contient un chemin figé")

    def test_aucun_secret_dans_les_lanceurs(self):
        for interdit in ("client_secret", "api_key", "CLIENT_SECRET", "Mot de passe"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, self.lanceur + self.arret)

    def test_arreter_arme_bien_le_stop(self):
        # Un double-clic ne doit jamais pouvoir détruire les rapports.
        executees = [
            ligne
            for ligne in self.arret.splitlines()
            if "serve_launchd.py" in ligne and not ligne.lstrip().startswith("#")
        ]
        self.assertEqual(len(executees), 1, f"arrêt inattendu : {executees}")
        self.assertIn(" stop", executees[0])
        self.assertNotIn("rm -rf", self.arret)

    def test_installe_sans_ecraser_les_donnees(self):
        # Seuls les répertoires de code sont remplacés à la mise à jour.
        for nom in dmg_mod.A_COPIER:
            with self.subTest(dossier=nom):
                self.assertIn('"$RACINE/$d"', self.lanceur)
        for interdit in ('rm -rf "$RACINE/data"', 'rm -rf "$RACINE"', 'rm -rf "${RACINE:?}"'):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, self.lanceur)


class TestAssemblage(unittest.TestCase):
    """`stage()` est le cœur vérifiable sur n'importe quel système."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="crimhebo-stage-")
        self.racine = dmg_mod.stage(Path(self.tmp) / "image", "9.9.9")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_contenu_de_la_racine(self):
        entrees = {p.name for p in self.racine.iterdir()}
        self.assertEqual(entrees, {LANCEUR, ARRET, LISEZMOI, dmg_mod.PAYLOAD})

    def test_programme_complet(self):
        for nom in ("crim_hebdo/cli.py", "crim_hebdo/server.py", "web/index.html", "tools/install.py"):
            with self.subTest(fichier=nom):
                self.assertTrue((self.racine / dmg_mod.PAYLOAD / nom).is_file())

    def test_lanceurs_executables_dans_limage(self):
        for nom in (LANCEUR, ARRET):
            with self.subTest(fichier=nom):
                self.assertTrue((self.racine / nom).stat().st_mode & 0o111)

    def test_aucune_donnee_personnelle(self):
        interdits = ["data", "config.json", ".env", "__pycache__"]
        trouves = [
            p
            for p in self.racine.rglob("*")
            for interdit in interdits
            if interdit in (p.name, p.suffix)
        ]
        self.assertEqual(trouves, [], f"contenu inutile dans l'image : {trouves}")

    def test_aucun_fichier_compile(self):
        self.assertEqual([p.name for p in self.racine.rglob("*.pyc")], [])

    def test_version_et_empreinte(self):
        contenu = (self.racine / dmg_mod.PAYLOAD / "VERSION").read_text()
        version, empreinte = contenu.split()
        self.assertEqual(version, "9.9.9")
        self.assertRegex(empreinte, r"^[0-9a-f]{16}$")

    def test_empreinte_stable(self):
        reference = dmg_mod.empreinte(self.racine / dmg_mod.PAYLOAD)
        shutil.rmtree(self.racine)
        seconde = dmg_mod.stage(Path(self.tmp) / "image2", "9.9.9")
        self.assertEqual(dmg_mod.empreinte(seconde / dmg_mod.PAYLOAD), reference)

    def test_empreinte_suit_une_modification(self):
        # Une modification du programme doit déclencher la réinstallation.
        cible = self.racine / dmg_mod.PAYLOAD / "crim_hebdo" / "cli.py"
        avant = dmg_mod.empreinte(self.racine / dmg_mod.PAYLOAD)
        cible.write_text(cible.read_text() + "\n# changement\n")
        self.assertNotEqual(dmg_mod.empreinte(self.racine / dmg_mod.PAYLOAD), avant)

    def test_assemblage_repetable_meme_dossier(self):
        # Un dossier déjà peuplé ne doit pas faire échouer la construction.
        again = dmg_mod.stage(Path(self.tmp) / "image", "9.9.9")
        self.assertTrue((again / LANCEUR).is_file())

    def test_refuse_un_dossier_dangereux(self):
        with self.assertRaises(SystemExit):
            dmg_mod.stage(ROOT, "9.9.9")
        # Le dépôt doit être intact.
        self.assertTrue((ROOT / "crim_hebdo" / "cli.py").is_file())

    def test_reglages_dmgbuild(self):
        reglages = dmg_mod.reglages_dmgbuild(self.racine)
        self.assertIn(dmg_mod.PAYLOAD, reglages["hide"])
        self.assertEqual(len(reglages["files"]), 4)
        for nom in (LANCEUR, ARRET, LISEZMOI):
            with self.subTest(fichier=nom):
                self.assertIn(nom, reglages["icon_locations"])
                self.assertTrue(any(nom in f for f in reglages["files"]))

    def test_couleur_de_fond_en_minuscules(self):
        # dmgbuild rejette une couleur hexadécimale en majuscules.
        couleur = dmg_mod.reglages_dmgbuild(self.racine)["background"]
        self.assertEqual(couleur, couleur.lower())
        self.assertTrue(couleur.startswith("#"))
        self.assertRegex(couleur, r"^#[0-9a-f]{6}$")

    def test_version_lisible(self):
        # Sans tag, `git describe` ne rend qu'un condensé : le nom du fichier
        # ne doit pas être un identifiant de commit.
        for attendu, descrit in [
            ("1.2.3", "v1.2.3"),
            ("1.2.3", "1.2.3"),
            ("1.2.3-4-gabc1234", "1.2.3-4-gabc1234"),
            ("0.1", "v0.1"),
            ("0.0.0-dev+98ffc1b", "98ffc1b"),
            ("0.0.0-dev+98ffc1b-dirty", "98ffc1b-dirty"),
            ("0.0.0-dev", ""),
        ]:
            with self.subTest(descrit=descrit):
                self.assertEqual(dmg_mod.version_lisible(descrit), attendu)

    def test_version_par_defaut_est_exploitable(self):
        version = dmg_mod.version_par_defaut()
        self.assertRegex(version, r"^0?\.?\d+\.\d+")
        self.assertNotIn(" ", version)

    def test_poids_restant_raisonnable(self):
        taille = sum(p.stat().st_size for p in self.racine.rglob("*") if p.is_file())
        self.assertLess(taille, 5 * 1024 * 1024, "l'image embarquerait des données")

    def test_construction_dmg_refusee_hors_macos(self):
        if sys.platform == "darwin":
            self.skipTest("ce test vérifie le comportement hors macOS")
        with silencieux(), contextlib.redirect_stderr(io.StringIO()):
            resultat = dmg_mod.construire_dmg(self.racine, Path(self.tmp))
        self.assertEqual(resultat.suffix, ".dmg")
        self.assertFalse(resultat.is_file())


class TestPlistDuServeur(unittest.TestCase):
    """L'agent du serveur doit être valide, explicite et sans secret."""

    def setUp(self):
        self.donnees = serve_mod.build_plist(8765)
        self.plist = plistlib.loads(plistlib.dumps(self.donnees))

    def test_demarre_a_la_connexion(self):
        self.assertTrue(self.plist["RunAtLoad"])
        # `KeepAlive` absent : un plantage ne doit pas boucler.
        self.assertNotIn("KeepAlive", self.plist)

    def test_commande(self):
        self.assertEqual(self.plist["Label"], serve_mod.LABEL)
        arguments = self.plist["ProgramArguments"]
        self.assertEqual(arguments[1:4], ["-m", "crim_hebdo", "serve"])
        self.assertIn("--no-browser", arguments)

    def test_port_demande(self):
        arguments = self.plist["ProgramArguments"]
        port = arguments[arguments.index("--port") + 1]
        self.assertEqual(port, "8765")

    def test_chemins_reels(self):
        self.assertEqual(self.plist["WorkingDirectory"], str(ROOT))
        self.assertEqual(self.plist["ProgramArguments"][0], sys.executable)
        for cle in ("StandardOutPath", "StandardErrorPath"):
            with self.subTest(cle=cle):
                self.assertTrue(Path(self.plist[cle]).is_absolute())
                self.assertNotIn("CHEMIN", self.plist[cle])

    def test_aucun_secret(self):
        brut = plistlib.dumps(self.donnees).decode()
        for interdit in ("SECRET", "client_id", "api_key"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, brut)

    def test_statut_lisible_sans_launchctl(self):
        # Doit rester consultable sur une machine sans launchd, sans planter.
        with silencieux():
            code = serve_mod.status(8765)
        self.assertIn(code, (0, 1))


class TestDocumentation(unittest.TestCase):
    def test_readme_mentionne_image_et_lanceur(self):
        texte = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(".dmg", texte)
        self.assertIn(LANCEUR, texte)

    def test_workflow_present(self):
        chemin = ROOT / ".github" / "workflows" / "dmg.yml"
        self.assertTrue(chemin.is_file())
        self.assertIn("macos", chemin.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
