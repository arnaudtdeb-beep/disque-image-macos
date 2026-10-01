"""Interface en ligne de commande.

    python3 -m crim_hebdo serve                 # interface web locale
    python3 -m crim_hebdo update                # actualisation (source DILA, sans clé)
    python3 -m crim_hebdo update --debut ... --fin ...
    python3 -m crim_hebdo update --source piste # API Judilibre si vous avez une clé PISTE
    python3 -m crim_hebdo list --debut ... --fin ...
    python3 -m crim_hebdo themes
    python3 -m crim_hebdo show 21-12.345
    python3 -m crim_hebdo export --format md
    python3 -m crim_hebdo init-config
    python3 -m crim_hebdo demo                  # charge un jeu de démonstration
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, load_config, save_template
from .dila import DilaError, list_releases
from .piste import MissingCredentials, PisteError
from .report import write_reports
from .store import Store
from .summary import render_card_text
from .weekly import last_week, run_update

SAMPLE_PATH = PROJECT_ROOT / "samples" / "demo_arrets.json"


def _period(args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "debut", None) and getattr(args, "fin", None):
        return args.debut, args.fin
    if getattr(args, "debut", None) or getattr(args, "fin", None):
        raise SystemExit("Les options --debut et --fin doivent être utilisées ensemble.")
    return last_week()


def _print_period(date_start: str, date_end: str) -> None:
    print(f"Période : {date_start} → {date_end}")


# ----------------------------------------------------------------- commands
def cmd_update(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.source:
        config.source = args.source
    if args.only_bulletin:
        config.only_bulletin = True
    if args.sans_llm:
        config.use_llm = False
    if args.legifrance:
        config.enrich_legifrance = True

    if config.source == "dila":
        # La source DILA publie par lot : sans fenêtre de dates explicite,
        # on traite tous les fichiers d'appoint encore inconnus.
        date_start = date_end = None
        if args.debut or args.fin:
            date_start, date_end = _period(args)
        _print_period(date_start, date_end or "(tous les fichiers d'appoint)")
    else:
        date_start, date_end = _period(args)
        _print_period(date_start, date_end)

    store = Store(config.data_dir)
    try:
        result = run_update(
            config,
            date_start=date_start,
            date_end=date_end,
            store=store,
            force=args.force,
            source=config.source,
        )
    except MissingCredentials as exc:
        print(f"\nConfiguration manquante.\n{exc}\n", file=sys.stderr)
        print("Astuce : `python3 -m crim_hebdo init-config` puis éditez config.json.", file=sys.stderr)
        return 2
    except PisteError as exc:
        print(f"\nÉchec de l'appel PISTE : {exc}", file=sys.stderr)
        return 3
    except DilaError as exc:
        print(f"\nÉchec de l'accès aux données ouvertes DILA : {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"\nConfiguration invalide : {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()

    origine = f"source {result.source}"
    if result.releases:
        origine += f" ({len(result.releases)} fichier(s) d'appoint)"
    print(
        f"\n{result.found} arrêt(s) sur la période · {result.new} nouveau(x) · "
        f"{result.skipped} déjà connu(s) · {result.bulletin} au bulletin · {origine}"
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config.data_dir)
    date_start, date_end = _period(args)
    rows = store.decisions_between(date_start, date_end)
    if not rows:
        print(f"Aucun arrêt enregistré entre le {date_start} et le {date_end}.")
        print("Lancez `python3 -m crim_hebdo update` (ou `demo`) d'abord.")
        store.close()
        return 0

    print(f"\n{len(rows)} arrêt(s) entre le {date_start} et le {date_end}\n")
    for row in rows:
        analysis = row.get("analysis") or {}
        meta = analysis.get("meta") or {}
        bulletin = "B" if meta.get("au_bulletin") else " "
        themes = ", ".join(t.get("label", "") for t in (analysis.get("themes") or [])[:3])
        print(
            f"[{bulletin}] {row['decision_date']}  {row['number'] or '—':<14} "
            f"{(analysis.get('solution_label') or row.get('solution') or ''):<28} {themes}"
        )
    print("\n[B] = publié au bulletin. Détail : `show <n° de pourvoi>`.\n")
    store.close()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config.data_dir)
    rows = [r for r in store.all_decisions() if r.get("number") == args.pourvoi]
    store.close()
    if not rows:
        print(f"Aucun arrêt en base pour le pourvoi {args.pourvoi}.")
        return 1
    row = rows[0]
    analysis = dict(row.get("analysis") or {})
    analysis["meta"] = analysis.get("meta") or {}
    analysis["meta"].update(
        {
            "id": row["id"],
            "ecli": row["ecli"],
            "number": row["number"],
            "decision_date": row["decision_date"],
            "solution": row["solution"],
            "summary": row["summary"],
            "url": row["url"],
            "publication": row["publication"] or [],
        }
    )
    analysis["meta"]["au_bulletin"] = analysis["meta"].get(
        "au_bulletin", "b" in (row["publication"] or [])
    )
    analysis["meta"]["solution_label"] = analysis.get("solution_label") or row["solution"]
    if args.json:
        print(json.dumps({"meta": analysis["meta"], "analyse": analysis}, ensure_ascii=False, indent=2))
    else:
        print(render_card_text({"meta": analysis["meta"], "analysis": analysis}))
    return 0


def cmd_themes(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config.data_dir)
    counts = store.theme_counts()
    store.close()
    if not counts:
        print("Aucun thème enregistré. Lancez d'abord `update` ou `demo`.")
        return 0
    total = sum(counts.values()) or 1
    print("\nRépartition thématique (toutes périodes)\n")
    for label, count in counts.items():
        bar = "█" * max(1, round(count / total * 30))
        text = label if len(label) <= 40 else label[:39] + "…"
        print(f"{text:<42} {count:>4}  {bar}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config.data_dir)
    date_start, date_end = _period(args)
    rows = store.decisions_between(date_start, date_end)
    store.close()
    if not rows:
        print("Aucun arrêt sur la période.")
        return 1
    paths = write_reports(config, rows, date_start, date_end)
    for kind, path in paths.items():
        print(f"{kind:<10} {path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    config = load_config(args.config)
    serve(config, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_init_config(args: argparse.Namespace) -> int:
    target = Path(args.out) if args.out else PROJECT_ROOT / "config.json"
    if target.exists() and not args.force:
        print(f"{target} existe déjà (utilisez --force pour écraser).")
        return 1
    path = save_template(target)
    print(f"Modèle écrit : {path}")
    print(
        "\nAucune étape n'est nécessaire pour la source DILA (défaut) :\n"
        "  1. python3 -m crim_hebdo check\n"
        "  2. python3 -m crim_hebdo update\n"
        "  3. python3 -m crim_hebdo serve\n"
    )
    print(
        "Pour utiliser l'API Judilibre à la place, mettez \"source\": \"piste\" dans ce\n"
        "fichier, créez un compte sur https://piste.gouv.fr/registration, abonnez-vous\n"
        "à « Judilibre » (et « Légifrance » pour les n° de bulletin), puis copiez\n"
        "client_id et client_secret ici."
    )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    if not SAMPLE_PATH.exists():
        print(f"Jeu de démonstration absent : {SAMPLE_PATH}")
        return 1
    config = load_config(args.config)
    store = Store(config.data_dir)
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    count = store.import_json(payload.get("arrets", []))
    store.close()
    print(f"{count} arrêt(s) de démonstration chargé(s) dans {config.data_dir}.")
    print("Lancez `python3 -m crim_hebdo serve` pour explorer l'interface.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print("Configuration effective :")
    for key, value in config.to_dict().items():
        print(f"  {key:<20} {value}")

    if config.source == "dila":
        print("\n→ Source DILA : aucune authentification requise.")
        store = Store(config.data_dir)
        deja = store.processed_releases()
        store.close()
        try:
            releases = list_releases()
        except DilaError as exc:
            print(f"  ✗ index des données ouvertes injoignable : {exc}")
            return 3
        print(f"  ✓ {len(releases)} fichier(s) d'appoint publié(s) par la DILA.")
        if deja:
            print(f"  {len(deja)} déjà traité(s) · {len(releases) - len(deja)} à venir")
        else:
            print(f"  {len(releases)} fichier(s) à traiter au premier lancement")
        print("\n→ Lancez `python3 -m crim_hebdo update` pour obtenir les arrêts.")
        return 0

    if not config.has_piste_credentials:
        print(
            "\n→ Source PISTE : identifiants absents. Sans compte PISTE, utilisez\n"
            "  la source DILA (par défaut) : python3 -m crim_hebdo update"
        )
        return 2
    from .piste import PisteClient

    try:
        client = PisteClient(config)
        token = client.token(force=True)
        print(f"\n→ Authentification PISTE OK (jeton de {len(token)} caractères).")
    except PisteError as exc:
        print(f"\n→ Échec d'authentification : {exc}")
        return 3
    return 0


# -------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crim_hebdo",
        description="Veille hebdomadaire de la chambre criminelle de la Cour de cassation.",
    )
    parser.add_argument("--config", help="chemin vers un fichier de configuration")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_period(p: argparse.ArgumentParser) -> None:
        p.add_argument("--debut", help="date de début (AAAA-MM-JJ)")
        p.add_argument("--fin", help="date de fin (AAAA-MM-JJ)")

    p_update = sub.add_parser(
        "update",
        help="actualiser la veille (source DILA par défaut, API Judilibre avec --source piste)",
    )
    add_period(p_update)
    p_update.add_argument(
        "--source",
        choices=("dila", "piste"),
        help="dila : données ouvertes sans clé (défaut) ; piste : API Judilibre",
    )
    p_update.add_argument("--force", action="store_true", help="réanalyser les arrêts déjà connus")
    p_update.add_argument("--only-bulletin", action="store_true", help="ne récupérer que les arrêts B")
    p_update.add_argument("--sans-llm", action="store_true", help="désactiver la synthèse assistée")
    p_update.add_argument("--legifrance", action="store_true", help="activer l'enrichissement Légifrance")
    p_update.set_defaults(func=cmd_update)

    p_serve = sub.add_parser("serve", help="ouvrir l'interface web locale")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_list = sub.add_parser("list", help="lister les arrêts enregistrés")
    add_period(p_list)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="afficher l'analyse d'un arrêt")
    p_show.add_argument("pourvoi", help="numéro de pourvoi, ex. 21-12.345")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=cmd_show)

    p_themes = sub.add_parser("themes", help="répartition thématique")
    p_themes.set_defaults(func=cmd_themes)

    p_export = sub.add_parser("export", help="régénérer les rapports d'une période")
    add_period(p_export)
    p_export.set_defaults(func=cmd_export)

    p_init = sub.add_parser("init-config", help="écrire un fichier de configuration modèle")
    p_init.add_argument("--out", help="chemin du fichier à écrire")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init_config)

    p_demo = sub.add_parser("demo", help="charger le jeu de démonstration")
    p_demo.set_defaults(func=cmd_demo)

    p_check = sub.add_parser("check", help="vérifier la configuration et l'authentification")
    p_check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
