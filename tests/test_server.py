"""Tests de l'endpoint /api/decisions : le total doit être réel, pas plafonné."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crim_hebdo.config import Config  # noqa: E402
from crim_hebdo.server import Handler  # noqa: E402
from crim_hebdo.store import Store  # noqa: E402


class _HandlerFactice(Handler):
    """Handler sans socket : on teste _decisions sur un vrai store temporaire."""

    def __init__(self, state):
        self.state = state

    def _json(self, payload, status=200):  # au cas où
        self._derniere_reponse = payload


def _peupler(store: Store, n: int, date_jour: str) -> None:
    for i in range(n):
        store.upsert_decision(
            {
                "id": f"id-{i}",
                "ecli": f"ECLI:{i}",
                "number": f"20-{i:05d}",
                "chamber": "cr",
                "formation": "f",
                "decision_date": date_jour,
                "publication": ["b"],
                "solution": "rejet",
                "summary": "",
                "url": "",
                "source": "piste",
            },
            {"text": ""},
            {"meta": {}, "themes": []},
        )


class TestDecisionsTotal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Config(data_dir=Path(self.tmp.name), source="piste")
        cfg.data_dir = Path(self.tmp.name)
        from crim_hebdo.server import AppState

        self.state = AppState(cfg)
        self.state.store = Store(Path(self.tmp.name))
        self.handler = _HandlerFactice(self.state)

    def tearDown(self):
        self.state.store.close()
        self.tmp.cleanup()

    def test_total_reel_au_dela_de_400(self):
        _peupler(self.state.store, 649, "2026-10-21")
        rep = self.handler._decisions({"debut": ["2020-01-01"], "fin": ["2026-12-31"]})
        self.assertEqual(rep["total"], 649)
        self.assertEqual(rep["affiches"], 649)
        self.assertFalse(rep["tronque"])

    def test_limit_explicite_expose_le_vrai_total(self):
        _peupler(self.state.store, 500, "2026-10-21")
        rep = self.handler._decisions(
            {"debut": ["2020-01-01"], "fin": ["2026-12-31"], "limit": ["400"]}
        )
        self.assertEqual(rep["total"], 500)
        self.assertEqual(rep["affiches"], 400)
        self.assertTrue(rep["tronque"])

    def test_deux_periodes_totaux_differents(self):
        # 10 arrêts au 21/10 et 30 arrêts au 01/08 : 30j et 90j diffèrent.
        _peupler(self.state.store, 10, "2026-10-21")
        for i in range(30):
            self.state.store.upsert_decision(
                {
                    "id": f"aout-{i}", "ecli": "", "number": f"a-{i}", "chamber": "cr",
                    "formation": "f", "decision_date": "2026-08-01", "publication": [],
                    "solution": "rejet", "summary": "", "url": "", "source": "piste",
                },
                {"text": ""}, {"meta": {}, "themes": []},
            )
        for periode, attendu in (
            (("2026-09-23", "2026-10-22"), 10),   # ~30j
            (("2026-07-25", "2026-10-22"), 40),   # ~90j
        ):
            rep = self.handler._decisions({"debut": [periode[0]], "fin": [periode[1]]})
            self.assertEqual(rep["total"], attendu, attendu)


if __name__ == "__main__":
    unittest.main()
