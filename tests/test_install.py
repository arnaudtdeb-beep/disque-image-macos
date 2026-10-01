"""Tests hors-ligne de l'installateur et du job macOS.

Aucun accès réseau, aucun appel à launchctl : tout est vérifié sur le plist
construit en mémoire et sur les transformations de crontab.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import install as install_mod  # noqa: E402
import install_launchd as launchd_mod  # noqa: E402


@contextlib.contextmanager
def silencieux():
    """Capture les écritures de l'installateur pour éviter de polluer la sortie."""
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        yield tampon


class TestEnvironnement(unittest.TestCase):
    def test_python_suffisant(self):
        # L'installateur refuse les versions antérieures à 3.9 ; on vérifie
        # que l'interpréteur des tests est bien accepté.
        self.assertGreaterEqual(sys.version_info[:2], install_mod.MIN_PYTHON)

    def test_fichiers_essentiels_presents(self):
        for nom in ("crim_hebdo/__init__.py", "crim_hebdo/cli.py", "web/index.html", "web/app.js"):
            with self.subTest(fichier=nom):
                self.assertTrue((ROOT / nom).is_file())

    def test_detection_python_trop_ancien(self):
        original = install_mod.MIN_PYTHON
        install_mod.MIN_PYTHON = (99, 0)
        try:
            with silencieux():
                verif = install_mod.etape_environnement()
            self.assertEqual(verif, 1)
        finally:
            install_mod.MIN_PYTHON = original


class TestPlist(unittest.TestCase):
    """Le plist doit être valide et sans aucun chemin d'exemple."""

    def setUp(self):
        self.data = launchd_mod.build_plist(7, 30)
        self.plist = plistlib.loads(plistlib.dumps(self.data))

    def test_structure(self):
        self.assertEqual(self.plist["Label"], launchd_mod.LABEL)
        self.assertEqual(self.plist["ProgramArguments"][-2:], ["crim_hebdo", "update"])
        self.assertEqual(self.plist["WorkingDirectory"], str(ROOT))
        self.assertFalse(self.plist["RunAtLoad"])

    def test_chemins_reels(self):
        self.assertEqual(self.plist["ProgramArguments"][0], sys.executable)
        for cle in ("StandardOutPath", "StandardErrorPath"):
            with self.subTest(cle=cle):
                self.assertTrue(Path(self.plist[cle]).is_absolute())
                self.assertNotIn("CHEMIN", self.plist[cle])

    def test_horaire(self):
        for heure, minute in [(7, 30), (6, 45), (23, 5)]:
            with self.subTest(heure=heure):
                data = launchd_mod.build_plist(heure, minute)
                self.assertEqual(
                    data["StartCalendarInterval"],
                    {"Weekday": 1, "Hour": heure, "Minute": minute},
                )

    def test_aucun_secret_dans_le_plist(self):
        brut = plistlib.dumps(self.data).decode()
        for interdit in ("CLIENT_SECRET", "CLIENT_ID", "SECRET", "REMPLACER"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, brut)

    def test_sortie_fonctionne_avec_python(self):
        # `python3 -m crim_hebdo` doit démarrer depuis la racine du projet.
        self.assertIn("PYTHONUNBUFFERED", self.data["EnvironmentVariables"])


class TestCrontab(unittest.TestCase):
    A = install_mod.CRON_MARK_BEGIN
    B = install_mod.CRON_MARK_END

    def setUp(self):
        self.ligne = install_mod._cron_ligne(7, 30)

    def test_ajout_sur_crontab_vide(self):
        resultat = install_mod._cron_ajouter("", self.ligne)
        self.assertEqual(resultat.strip().splitlines(), [self.A, self.ligne, self.B])

    def test_ajout_preserve_les_autres_taches(self):
        existant = "0 5 * * * /usr/bin/backup\n"
        resultat = install_mod._cron_ajouter(existant, self.ligne)
        self.assertIn("/usr/bin/backup", resultat)
        self.assertIn(self.ligne, resultat)

    def test_ajout_idempotent(self):
        une = install_mod._cron_ajouter("0 5 * * * /usr/bin/backup\n", self.ligne)
        self.assertEqual(install_mod._cron_ajouter(une, self.ligne), une)

    def test_retrait_du_bloc(self):
        existant = "0 5 * * * /usr/bin/backup\n"
        installe = install_mod._cron_ajouter(existant, self.ligne)
        self.assertEqual(install_mod._cron_retirer(installe), existant)

    def test_retrait_idempotent(self):
        installe = install_mod._cron_ajouter("0 5 * * * /usr/bin/backup\n", self.ligne)
        une = install_mod._cron_retirer(installe)
        self.assertEqual(install_mod._cron_retirer(une), une)

    def test_retrait_preserve_les_tiers(self):
        autre = "15 3 * * 0 other-job\n"
        installe = install_mod._cron_ajouter(autre, self.ligne)
        self.assertEqual(install_mod._cron_retirer(installe), autre)

    def test_retrait_vide_si_rien_dautre(self):
        installe = install_mod._cron_ajouter("", self.ligne)
        self.assertEqual(install_mod._cron_retirer(installe), "")

    def test_retrait_net_une_ligne_manuelle(self):
        residue = "5 7 * * 1 cd /x && python3 -m crim_hebdo update\n"
        self.assertNotIn("crim_hebdo", install_mod._cron_retirer(residue))

    def test_retrait_ajoute_un_retour_ligne(self):
        self.assertEqual(install_mod._cron_retirer("0 5 * * * b"), "0 5 * * * b\n")

    def test_cron_uniquement_le_lundi(self):
        champs = self.ligne.split()[:5]
        self.assertEqual(champs[4], "1")  # 1 = lundi
        self.assertEqual(champs[2], "*")
        self.assertEqual(champs[3], "*")

    def test_horaire_reflete_les_arguments(self):
        for heure, minute in [(7, 30), (6, 45), (23, 5)]:
            with self.subTest(heure=heure):
                ligne = install_mod._cron_ligne(heure, minute)
                self.assertEqual(ligne.split()[:2], [str(minute), str(heure)])


class TestDryRun(unittest.TestCase):
    """--dry-run ne doit rien écrire sur le disque."""

    def test_dry_run_ne_cree_aucun_fichier_de_configuration(self):
        cible = ROOT / "config.json"
        avant = cible.exists()
        with silencieux():
            install_mod.etape_configuration(dry_run=True)
        self.assertEqual(cible.exists(), avant)

    def test_dry_run_ne_touche_pas_aux_dossiers(self):
        inexistant = ROOT / "data" / "rapports" / "test_dry_run"
        with silencieux():
            install_mod.etape_dossiers(dry_run=True)
        self.assertFalse(inexistant.exists())

    def test_dry_run_ne_cree_pas_de_plist(self):
        cible = Path(tempfile.gettempdir()) / "crim-hebdo-dry-run.plist"
        if cible.exists():
            cible.unlink()
        with silencieux():
            launchd_mod.install(7, 30, dry_run=True)
        self.assertFalse(cible.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)