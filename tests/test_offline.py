"""Tests hors-ligne : aucun accès réseau requis.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
import pathlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crim_hebdo.analysis import build_card, is_bulletin, publication_labels  # noqa: E402
from crim_hebdo.config import Config  # noqa: E402
from crim_hebdo.report import build_markdown, build_json  # noqa: E402
from crim_hebdo.store import Store  # noqa: E402
from crim_hebdo.summarize import (  # noqa: E402
    extractive_analysis,
    llm_analysis,
    solution_label,
)
from crim_hebdo.textutil import (  # noqa: E402
    extract_articles,
    normalize,
    sentences,
    zone_text,
)
from crim_hebdo.themes import classify  # noqa: E402
from crim_hebdo.weekly import _keys_of, last_week  # noqa: E402

INTRO = "Sur le rapport de M. le conseiller rapporteur.\n\nVu l'article 431 du code de procédure pénale."
EXPOSE = (
    "Le 3 mars 2026, M. Durand a été interpellé puis placé en garde à vue sans "
    "prolongation préalable, en violation de l'article 62 du code de procédure pénale."
)
MOYENS = (
    "Les moyens du pourvoi sont les suivants.\n\n"
    "1°/ le placement en garde à vue est intervenu sans prolongation préalable;\n\n"
    "2°/ l'audition s'est déroulée sans la présence d'un avocat."
)
MOTIVATIONS = (
    "Sur le moyen tiré de l'illégalité de la garde à vue :\n\n"
    "1°/ l'article 62 du code de procédure pénale subordonne le placement en garde à vue "
    "à l'existence de circonstances graves;\n\n"
    "2°/ il n'y a lieu à l'évidence de prononcer l'annulation de la procédure.\n\n"
    "Mais sur le moyen tiré de l'absence d'avocat :\n\n"
    "3°/ le droit d'assistance a été méconnu."
)
DISPOSITIF = "REJETTE le pourvoi."

TEXT = "\n\n".join([INTRO, EXPOSE, MOYENS, MOTIVATIONS, DISPOSITIF])


def make_zones():
    zones, cursor = {}, 0
    for name, block in [
        ("introduction", INTRO),
        ("expose", EXPOSE),
        ("moyens", MOYENS),
        ("motivations", MOTIVATIONS),
        ("dispositif", DISPOSITIF),
    ]:
        start = cursor
        cursor += len(block) + 2
        zones[name] = [{"start": start, "end": start + len(block)}]
    return zones


ZONES = make_zones()

SHORT = {
    "id": "test0000000000000001",
    "jurisdiction": "cc",
    "chamber": "crim",
    "number": "26-11.111",
    "numbers": ["26-11.111"],
    "ecli": "ECLI:FR:CCASS:2026:TEST1",
    "formation": "chambre criminelle",
    "publication": ["b"],
    "decision_date": "2026-09-28",
    "type": "arret",
    "solution": "rejet",
    "summary": "Le placement en garde à vue sans prolongation préalable est illégal.",
    "themes": ["Droit des personnes", "Procédure pénale"],
}
FULL = {
    "id": SHORT["id"],
    "text": TEXT,
    "zones": ZONES,
    "visa": [{"title": "Code de procédure pénale - Article 62", "url": "https://x"}],
    "partial": False,
    "titlesAndSummaries": [{"title": SHORT["summary"]}],
}


class TestTextUtil(unittest.TestCase):
    def test_sentences_respecte_les_abreviations(self):
        parts = sentences("aux termes de l'article L. 628-1 du code, le délit existe. Il doit être rejeté.")
        self.assertEqual(len(parts), 2)
        self.assertIn("L. 628-1", parts[0])

    def test_extract_articles_gerere_les_enumerations(self):
        refs = extract_articles("en violation des articles 62, 63-2 et 431 du code")
        self.assertEqual(refs, ["62", "63-2", "431"])

    def test_extract_articles_formes_variables(self):
        self.assertEqual(extract_articles("l'article 122.1 du code pénal"), ["122.1"])
        self.assertEqual(extract_articles("les articles 706-14 et 217-1"), ["706-14", "217-1"])

    def test_normalize_insensible_aux_accents(self):
        self.assertEqual(normalize("Nullité É À garde-à-vue"), normalize("nullite e a garde-a-vue"))

    def test_zone_text_reconstruit_les_offsets(self):
        self.assertEqual(zone_text(TEXT, ZONES, "dispositif"), DISPOSITIF)
        self.assertEqual(zone_text(TEXT, ZONES, "expose"), EXPOSE)

    def test_zone_text_tolere_offsets_invalides(self):
        self.assertEqual(zone_text(TEXT, {"expose": [{"start": 10, "end": 2}]}, "expose"), "")


class TestThemes(unittest.TestCase):
    def test_classification_cible_nullite_et_garde_a_vue(self):
        result = classify(
            {"introduction": INTRO, "expose": EXPOSE, "moyens": MOYENS, "motivations": MOTIVATIONS}
        )
        codes = [t.code for t in result]
        self.assertIn("garde_a_vue", codes)
        self.assertIn("nullite", codes)

    def test_classification_sans_preuve_texte(self):
        result = classify({})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, "procedure_criminale")

    def test_chaque_theme_expose_une_preuve(self):
        result = classify({"motivations": MOTIVATIONS * 3, "expose": EXPOSE * 3})
        for theme in result:
            if theme.code == "procedure_criminale":
                continue
            self.assertTrue(
                theme.evidence or theme.note,
                f"le thème {theme.code} doit être justifié ou documenté",
            )

    def test_theme_evidence_est_un_extrait_du_texte(self):
        source = normalize(MOTIVATIONS + EXPOSE)
        for theme in classify({"motivations": MOTIVATIONS, "expose": EXPOSE}):
            for quote in theme.evidence:
                self.assertIn(normalize(quote), source)


class TestSummarize(unittest.TestCase):
    def setUp(self):
        self.analysis = extractive_analysis(TEXT, ZONES, SHORT["summary"], FULL["visa"])

    def test_attendu_contient_le_sommaire_et_la_question(self):
        self.assertTrue(self.analysis.attendu)
        self.assertTrue(self.analysis.attendu[0].startswith("Sommaire de la Cour"))
        self.assertTrue(any("illégalité de la garde à vue" in a for a in self.analysis.attendu))

    def test_solution_reprend_le_dispositif(self):
        self.assertTrue(any("REJETTE le pourvoi" in s for s in self.analysis.solution))

    def test_moyens_sont_decoupes_par_alinea(self):
        self.assertGreaterEqual(len(self.analysis.moyens), 2)
        self.assertTrue(all(not m.startswith("1°/") for m in self.analysis.moyens))

    def test_motifs_sont_des_extraits_fideles(self):
        source = normalize(MOTIVATIONS)
        for motif in self.analysis.motifs:
            self.assertIn(normalize(motif), source)

    def test_textes_appliques_depuis_le_visa(self):
        self.assertEqual(self.analysis.textes, ["Code de procédure pénale - Article 62"])

    def test_solution_label_connu_et_inconnu(self):
        self.assertEqual(solution_label("rejet"), "Rejet du pourvoi")
        self.assertEqual(solution_label("cassation"), "Cassation de l'arrêt d'appel")
        self.assertEqual(solution_label("xyz"), "Xyz")

    def test_ia_desactivee_bascule_en_extractif(self):
        config = Config(use_llm=True)
        config.llm.provider = "none"
        result = llm_analysis({"expose": EXPOSE}, config.llm, self.analysis)
        self.assertEqual(result["source"], "extractive")
        self.assertIsNotNone(result["fallback_reason"])
        self.assertEqual(result["attendu"], self.analysis.attendu)


class TestAnalysis(unittest.TestCase):
    def test_detection_du_bulletin(self):
        self.assertTrue(is_bulletin(["b"]))
        self.assertTrue(is_bulletin(["r", "b"]))
        self.assertFalse(is_bulletin(["r"]))
        self.assertFalse(is_bulletin(None))

    def test_libelles_de_publication(self):
        self.assertEqual(publication_labels(["b"]), ["Publié au bulletin (B)"])

    def test_build_card(self):
        card = build_card(SHORT, FULL, Config(use_llm=False))
        self.assertTrue(card.meta["au_bulletin"])
        self.assertFalse(card.meta["au_rapport"])
        self.assertEqual(card.meta["solution_label"], "Rejet du pourvoi")
        self.assertEqual(card.meta["themes_officiels"], ["Droit des personnes", "Procédure pénale"])
        self.assertIn("garde_a_vue", [t["code"] for t in card.analysis["themes"]])
        self.assertIn("extractive", card.analysis["fiabilite"])

    def test_build_card_sans_publication(self):
        short = dict(SHORT, publication=[])
        card = build_card(short, FULL, Config(use_llm=False))
        self.assertFalse(card.meta["au_bulletin"])


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _card(self):
        return build_card(SHORT, FULL, Config(use_llm=False))

    def test_insertion_puis_dedupliquonnage(self):
        card = self._card()
        self.assertTrue(self.store.upsert_decision(card.meta, card.raw, card.analysis))
        self.assertFalse(self.store.upsert_decision(card.meta, card.raw, card.analysis))
        self.assertEqual(len(self.store.decisions_between("2026-01-01", "2026-12-31")), 1)

    def test_cles_de_dedupliquonnage(self):
        card = self._card()
        self.store.upsert_decision(card.meta, card.raw, card.analysis)
        keys = self.store.known_keys()
        self.assertIn(f"id:{SHORT['id']}", keys)
        self.assertIn(f"ecli:{SHORT['ecli']}", keys)
        self.assertIn(f"num:{SHORT['number']}", keys)
        self.assertTrue(_keys_of(SHORT) & keys)

    def test_comptage_thematique(self):
        card = self._card()
        self.store.upsert_decision(card.meta, card.raw, card.analysis)
        counts = self.store.theme_counts()
        self.assertIn("Garde à vue", counts)
        self.assertEqual(sum(counts.values()), len(card.analysis["themes"]))

    def test_filtre_de_periode(self):
        card = self._card()
        self.store.upsert_decision(card.meta, card.raw, card.analysis)
        self.assertEqual(self.store.decisions_between("2026-01-01", "2026-01-02"), [])
        self.assertEqual(len(self.store.decisions_between("2026-09-28", "2026-09-28")), 1)

    def test_piste_des_executions(self):
        run_id = self.store.start_run("2026-09-20", "2026-09-26")
        self.store.finish_run(run_id, found=3, new=2, bulletin=1, status="ok")
        runs = self.store.recent_runs()
        self.assertEqual(runs[0]["status"], "ok")
        self.assertEqual(runs[0]["bulletin"], 1)

    def test_import_du_jeu_de_demo(self):
        payload = json.loads((ROOT / "samples" / "demo_arrets.json").read_text(encoding="utf-8"))
        count = self.store.import_json(payload["arrets"])
        self.assertEqual(count, len(payload["arrets"]))
        self.assertFalse(self.store.is_empty())


class TestReport(unittest.TestCase):
    def _cards(self):
        card = build_card(SHORT, FULL, Config(use_llm=False))
        return [{"meta": card.meta, "analysis": card.analysis, "raw": card.raw}]

    def test_markdown_signale_le_bulletin_et_l_ecli(self):
        md = build_markdown(self._cards(), "2026-09-28", "2026-10-04")
        self.assertIn("Publié au bulletin (B)", md)
        self.assertIn(SHORT["ecli"], md)
        self.assertIn("L'attendu de la Cour", md)
        self.assertIn("Répartition thématique", md)

    def test_markdown_sans_arret(self):
        self.assertIn("0", build_markdown([], "2026-01-01", "2026-01-07"))

    def test_json_est_serialisable(self):
        payload = json.loads(build_json(self._cards(), "2026-09-28", "2026-10-04"))
        self.assertEqual(payload["nombre_arrets"], 1)
        self.assertEqual(payload["nombre_bulletin"], 1)


class TestWeekly(unittest.TestCase):
    def test_last_week_couvre_sept_jours(self):
        start, end = last_week(date(2026, 10, 1))
        self.assertEqual(start, "2026-09-24")
        self.assertEqual(end, "2026-09-30")
        delta = (date.fromisoformat(end) - date.fromisoformat(start)).days
        self.assertEqual(delta, 6)

    def test_keys_of(self):
        keys = _keys_of(SHORT)
        self.assertEqual(keys, {f"id:{SHORT['id']}", f"ecli:{SHORT['ecli']}", f"num:{SHORT['number']}"})

    def test_les_versions_traitees_ne_sont_plus_rejouees(self):
        """Une version déjà écrite doit être sautée au prochain lancement."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(pathlib.Path(tmp))
            store.mark_release("CASS_20260930-215413.tar.gz", "2026-09-30", "https://x/f.tar.gz", 18)
            traites = set(store.processed_releases())
            store.close()
            self.assertIn("CASS_20260930-215413.tar.gz", traites)
            self.assertNotIn("CASS_20260105-000000.tar.gz", traites)


class TestConfig(unittest.TestCase):
    def test_credentials_absentes(self):
        cfg = Config(client_id="", client_secret="")
        self.assertFalse(cfg.has_piste_credentials)

    def test_to_dict_ne_fuit_pas_le_secret(self):
        cfg = Config(client_id="abc", client_secret="top-secret")
        dumped = json.dumps(cfg.to_dict())
        self.assertNotIn("top-secret", dumped)
        self.assertNotIn("client_secret", cfg.to_dict())

    def test_urls_par_defaut(self):
        cfg = Config()
        self.assertEqual(cfg.judilibre_base, "https://api.piste.gouv.fr/cassation/judilibre/v1.0")
        self.assertEqual(cfg.chambers, ["crim"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
