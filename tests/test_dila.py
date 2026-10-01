"""Tests de la source « données ouvertes » (DILA) sur de vrais fichiers de la Cour.

Les fixtures sont des extraits XML publiés par la DILA pour la Cour de cassation
(licence ouverte 2.0), attribution : Cour de cassation / DILA.
Aucun appel réseau n'est effectué : les tests lisent `tests/fixtures/`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crim_hebdo.analysis import build_card  # noqa: E402
from crim_hebdo.config import Config  # noqa: E402
from crim_hebdo.dila import (  # noqa: E402
    LEGIFRANCE_URL,
    Release,
    format_number,
    parse_decision,
    parse_release,
    period_of,
    sommaire_lines,
)
from crim_hebdo.textutil import all_zones  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "criminelle" / "JURI" / "TEXT"
RELEASE = Release("CASS_20260930-215413.tar.gz", "https://exemple/CASS.tar.gz", "2026-09-30", 358400)


def parsed(name: str):
    path = next(FIXTURES.glob(f"*{name}*"))
    result = parse_decision(path, RELEASE)
    assert result is not None, f"fixture illisible : {path.name}"
    return result


class TestFormatNumber(unittest.TestCase):
    def test_numero_brut_ou_separe(self):
        for brut in ("2482494", "24-82494", "24.82.494"):
            self.assertEqual(format_number(brut), "24-82.494", brut)

    def test_numero_deja_normalise(self):
        self.assertEqual(format_number("24-82.494"), "24-82.494")

    def test_numero_incomplet_conserve(self):
        self.assertEqual(format_number("123"), "123")
        self.assertEqual(format_number("1-2-3"), "1-2-3")

    def test_vide(self):
        self.assertIsNone(format_number(None))
        self.assertIsNone(format_number("   "))


class TestParseDecision(unittest.TestCase):
    def test_metadonnees_essentielles(self):
        short, _full = parsed("2482494")
        self.assertEqual(short["number"], "24-82.494")
        self.assertEqual(short["numbers"], ["24-82.494"])
        self.assertEqual(short["decision_date"], "2026-03-10")
        self.assertEqual(short["solution"], "Cassation partielle")
        self.assertEqual(short["ecli"], "ECLI:FR:CCASS:2026:CR00294")
        self.assertEqual(short["chamber"], "crim")
        self.assertEqual(short["formation"], "chambre criminelle")
        self.assertEqual(short["source"], "dila")
        self.assertEqual(short["release"], RELEASE.name)

    def test_publication_au_bulletin(self):
        for name in ("2482494", "2584212", "2696004"):
            short, _ = parsed(name)
            self.assertEqual(short["publication"], ["b"], name)

    def test_url_lisible_avec_l_identifiant_open_data(self):
        short, full = parsed("2482494")
        expected = LEGIFRANCE_URL.format(id="JURITEXT000053764938")
        self.assertEqual(short["url"], expected)
        self.assertEqual(full["url"], expected)

    def test_sommaire_officiel(self):
        short, full = parsed("2584212")
        self.assertEqual(short["summary"], "AUTORITE PARENTALE ; Retrait ; Conditions ; Détermination")
        self.assertEqual(short["themes"], ["AUTORITE PARENTALE"])
        self.assertTrue(full["titlesAndSummaries"])
        self.assertTrue(sommaire_lines(full["sommaire"]))

    def test_solutions_variees(self):
        solutions = {parsed(p)[0]["solution"] for p in ("2482494", "2584212", "2696004", "2683654")}
        self.assertGreaterEqual(len(solutions), 3)

    def test_texte_integral_et_visa(self):
        _short, full = parsed("2482494")
        self.assertGreater(len(full["text"]), 5000)
        self.assertNotIn("<br/>", full["text"])
        self.assertTrue(any(v["title"].startswith("Vu ") for v in full["visa"]))
        for visa in full["visa"]:
            self.assertEqual(visa["title"], visa["title"].strip())


class TestZones(unittest.TestCase):
    def test_zones_reconstituent_le_texte(self):
        for path in sorted(FIXTURES.glob("*.xml")):
            result = parse_decision(path, RELEASE)
            self.assertIsNotNone(result, path.name)
            _short, full = result
            zones = all_zones(full["text"], full["zones"])
            for name in ("expose", "motivations", "dispositif"):
                self.assertTrue(zones[name], f"{path.name} : zone {name} vide")

    def test_la_motivation_est_entre_les_zones(self):
        _short, full = parsed("2482494")
        zones = all_zones(full["text"], full["zones"])
        motifs = full["text"].find("1. Il résulte")
        self.assertLess(motifs, zones["dispositif"].__len__() + full["zones"]["motivations"][0]["start"])
        self.assertIn("Il résulte de l'arrêt", zones["motivations"])
        self.assertIn("CASSE", zones["dispositif"])
        self.assertNotIn("CASSE", zones["motivations"])

    def test_introduction_est_la_phrase_de_composition(self):
        _short, full = parsed("2482494")
        zones = all_zones(full["text"], full["zones"])
        self.assertTrue(zones["introduction"].startswith("Sur le rapport"))

    def test_la_signature_ne_tient_pas_dans_les_annexes(self):
        _short, full = parsed("2482494")
        zones = all_zones(full["text"], full["zones"])
        self.assertNotIn("Ainsi fait et jugé", zones["annexes"])


class TestCarteComplete(unittest.TestCase):
    def test_une_fiche_se_construit_comme_avec_judilibre(self):
        short, full = parsed("2584752")
        card = build_card(short, full, Config(use_llm=False))
        self.assertEqual(card.meta["source"], "dila")
        self.assertTrue(card.meta["au_bulletin"])
        self.assertEqual(card.meta["solution_label"], "Cassation de l'arrêt d'appel")
        self.assertEqual(card.meta["themes_officiels"], ["DOUANES"])
        self.assertIn("extractive", card.analysis["fiabilite"])
        self.assertTrue(card.analysis["solution_texte"])
        self.assertTrue(card.analysis["motifs"])
        self.assertTrue(any(t["code"] == "douanes" for t in card.analysis["themes"]))

    def test_le_sommaire_alimente_l_attendu(self):
        short, full = parsed("2584752")
        card = build_card(short, full, Config(use_llm=False))
        self.assertTrue(card.analysis["attendu"])
        self.assertIn("DOUANES", " ".join(card.analysis["attendu"]))


class TestNomenclatureOfficielle(unittest.TestCase):
    """Le sommaire de la Cour complète la détection par le texte."""

    def test_matiere_officielle_au_dessus_du_seuil_du_texte(self):
        # « PEINES » seul ne fait franchir aucun seuil par motifs : le thème
        # n'est retenu que grâce à la nomenclature officielle.
        from crim_hebdo.themes import classify, theme_codes_for_official

        result = classify({"motivations": "REJETTE le pourvoi."}, official_matters=["PEINES"])
        codes = [t.code for t in result]
        self.assertIn("peines", codes)
        self.assertNotIn("procedure_criminale", codes)

    def test_sans_matiere_officielle_le_theme_reapparait(self):
        from crim_hebdo.themes import classify

        codes = [t.code for t in classify({"motivations": "REJETTE le pourvoi."})]
        self.assertEqual(codes, ["procedure_criminale"])

    def test_un_theme_deja_detecte_nest_pas_duplique(self):
        from crim_hebdo.themes import classify

        text = "M. X a été interpellé après une garde à vue irrégulière."
        result = classify({"motivations": text * 4}, official_matters=["GARDE A VUE"])
        codes = [t.code for t in result]
        self.assertEqual(codes.count("garde_a_vue"), 1)

    def test_correspondance_officielle(self):
        from crim_hebdo.themes import theme_codes_for_official

        self.assertEqual(
            theme_codes_for_official(["DOUANES", "URBANISME", "matière inconnue"]),
            ["douanes", "urbanisme"],
        )
        self.assertEqual(theme_codes_for_official(None), [])
        self.assertEqual(theme_codes_for_official([]), [])

    def test_la_nomenclature_est_reprise_telle_quelle_dans_la_fiche(self):
        for path in sorted(FIXTURES.glob("*.xml")):
            short, _ = parse_decision(path, RELEASE)
            for matter in short["themes"]:
                self.assertEqual(matter, matter.strip().upper() if matter.isupper() else matter)
                self.assertTrue(matter)


class TestProvenanceDesRapports(unittest.TestCase):
    """Un rapport ne doit pas annoncer une source que les données n'utilisent pas."""

    def _card(self, source: str) -> dict:
        short, full = parsed("2482494")
        short["source"] = source
        card = build_card(short, full, Config(use_llm=False))
        return {"meta": card.meta, "analysis": card.analysis, "raw": full}

    def test_provenance_dila(self):
        from crim_hebdo.report import source_label

        self.assertIn("DILA", source_label([self._card("dila")]))

    def test_provenance_judilibre(self):
        from crim_hebdo.report import source_label

        self.assertIn("Judilibre", source_label([self._card("piste")]))

    def test_provenance_mixte(self):
        from crim_hebdo.report import source_label

        label = source_label([self._card("dila"), self._card("piste")])
        self.assertIn("DILA", label)
        self.assertIn("Judilibre", label)

    def test_provenance_inconnue_ne_mentionne_aucune_api(self):
        from crim_hebdo.report import source_label

        label = source_label([self._card("autre-chose")])
        self.assertEqual(label, "Cour de cassation")

    def test_ligne_source_du_rapport(self):
        from crim_hebdo.report import build_markdown

        text = build_markdown([self._card("dila")], "2026-03-01", "2026-03-31")
        self.assertIn("source : données ouvertes de la Cour de cassation (DILA)", text)
        self.assertNotIn("PISTE", text)


class TestRelease(unittest.TestCase):
    def test_extraction_depuis_un_dossier(self):
        pairs = parse_release(FIXTURES, RELEASE)
        self.assertEqual(len(pairs), len(list(FIXTURES.glob("*.xml"))))
        for short, _full in pairs:
            self.assertEqual(short["chamber"], "crim")

    def test_les_mauvaises_formations_sont_ignorees(self):
        paires = parse_release(FIXTURES, RELEASE)
        self.assertTrue(all(s["chamber"] == "crim" for s, _ in paires))

    def test_periode_couverte(self):
        pairs = parse_release(FIXTURES, RELEASE)
        start, end = period_of([s for s, _ in pairs])
        self.assertLessEqual(start, end)
        self.assertEqual(start, "2026-03-10")
        self.assertEqual(end, "2026-09-16")

    def test_periode_vide(self):
        start, end = period_of([])
        self.assertTrue(start and end)
        self.assertRegex(start, r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(end, r"^\d{4}-\d{2}-\d{2}$")

    def test_release_est_un_nom_de_fichier(self):
        self.assertTrue(RELEASE.name.startswith("CASS_"))
        self.assertEqual(RELEASE.date, "2026-09-30")


if __name__ == "__main__":
    unittest.main(verbosity=2)