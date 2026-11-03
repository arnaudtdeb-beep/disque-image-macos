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



class TestServeLaunchd(unittest.TestCase):
    """L'agent launchd doit se relancer à la connexion et rester simple."""

    def test_plist_runatload(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import serve_launchd
        data = serve_launchd.build_plist(port=8765)
        self.assertTrue(data["RunAtLoad"])
        args = data["ProgramArguments"]
        self.assertIn("--port", args)
        self.assertEqual(args[args.index("--port") + 1], "8765")
        self.assertIn("--no-browser", args)
        # Pas de KeepAlive global : un plantage ne doit pas boucler.
        self.assertNotIn("KeepAlive", data)

    def test_liberer_port_port_libre_ne_tue_rien(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import serve_launchd
        # Un port très improbablement utilisé : libérer ne doit rien casser.
        self.assertEqual(serve_launchd.liberer_port(59999), 0)

    def test_est_notre_serveur_pid_inexistant(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import serve_launchd
        self.assertFalse(serve_launchd._est_notre_serveur(999999))



class TestTLS(unittest.TestCase):
    """Le contexte TLS suit les variables d'environnement, sans casser le défaut."""

    def test_defaut_verifie(self):
        import os
        from unittest import mock
        import ssl
        from crim_hebdo import tls
        env = {k: v for k, v in os.environ.items()
               if k not in ("CRIM_HEBDO_CA_BUNDLE", "CRIM_HEBDO_SSL_NO_VERIFY")}
        with mock.patch.dict(os.environ, env, clear=True):
            ctx = tls.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    def test_desactivation(self):
        import os
        from unittest import mock
        import ssl
        from crim_hebdo import tls
        with mock.patch.dict(os.environ, {"CRIM_HEBDO_SSL_NO_VERIFY": "1"}):
            ctx = tls.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)

    def test_ca_bundle_inexistant_leve(self):
        import os
        from unittest import mock
        from crim_hebdo import tls
        with mock.patch.dict(os.environ, {"CRIM_HEBDO_CA_BUNDLE": "/n/existe/pas.pem"}):
            os.environ.pop("CRIM_HEBDO_SSL_NO_VERIFY", None)
            with self.assertRaises(RuntimeError):
                tls.ssl_context()

    def test_plist_transmet_variables_reseau(self):
        import os
        from unittest import mock
        sys.path.insert(0, str(ROOT / "tools"))
        import serve_launchd
        with mock.patch.dict(os.environ, {
            "CRIM_HEBDO_CA_BUNDLE": "/tmp/ca.pem",
            "CRIM_HEBDO_SSL_NO_VERIFY": "1",
        }):
            data = serve_launchd.build_plist(port=8765)
        env = data["EnvironmentVariables"]
        self.assertEqual(env["CRIM_HEBDO_CA_BUNDLE"], "/tmp/ca.pem")
        self.assertEqual(env["CRIM_HEBDO_SSL_NO_VERIFY"], "1")


if __name__ == "__main__":
    unittest.main()
