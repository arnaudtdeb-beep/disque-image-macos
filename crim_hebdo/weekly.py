"""Orchestration de l'actualisation hebdomadaire.

Deux sources, même résultat :

  - **dila** (défaut) : les fichiers d'appoint hebdomadaires publiés par la DILA
    pour la Cour de cassation. Aucune clé, aucun quota. Chaque fichier contient
    les décisions nouvellement ouvertes au public ; un numéro de version déjà
    traité est ignoré.
  - **piste** : l'API Judilibre, qui exige un couple client_id / client_secret.

Déroulé commun : collecte des décisions inconnues → analyse (thèmes + synthèse)
→ enregistrement → rapports Markdown / HTML / JSON.

L'opération est idempotente : relancer une même période ne duplique rien et
ne réanalyse pas les arrêts déjà présents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from . import dila as dila_source
from .analysis import DecisionCard, build_card, is_bulletin, is_rapport, publication_labels
from .config import Config
from .judilibre import JudilibreClient
from .legifrance import LegifranceClient
from .piste import PisteClient
from .report import write_reports
from .store import Store
from .summarize import solution_label

Logger = Callable[[str], None]


def _print(message: str) -> None:
    """Journalisation : le flush évite de perdre l'avancement en redirection."""
    print(message, flush=True)


@dataclass
class RunResult:
    date_start: str
    date_end: str
    found: int
    new: int
    analysed: int
    bulletin: int
    skipped: int
    cards: list[dict[str, Any]]
    report_paths: dict[str, str]
    source: str = "dila"
    releases: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_start": self.date_start,
            "date_end": self.date_end,
            "source": self.source,
            "releases": self.releases or [],
            "found": self.found,
            "new": self.new,
            "analysed": self.analysed,
            "bulletin": self.bulletin,
            "skipped": self.skipped,
            "reports": self.report_paths,
        }


def last_week(today: date | None = None) -> tuple[str, str]:
    """Période hebdomadaire par défaut : les 7 derniers jours (inclus)."""
    ref = today or date.today()
    end = ref - timedelta(days=1)
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()


def run_update(
    config: Config,
    date_start: str | None = None,
    date_end: str | None = None,
    store: Store | None = None,
    log: Logger = _print,
    force: bool = False,
    source: str | None = None,
) -> RunResult:
    """Actualise la base et produit le rapport de la période.

    `date_start` / `date_end` filtrent les décisions **par date de prononcé**.
    Sans argument, la période est la semaine écoulée (source PISTE) ou
    l'ensemble des fichiers d'appoint non encore traités (source DILA, qui
    publie par lot hebdomadaire et non par date de décision).
    """
    source = (source or config.source or "dila").strip().lower()
    own_store = store is None
    store = store or Store(config.data_dir)

    try:
        if source == "dila":
            return _run_dila(config, store, log, force=force, date_start=date_start, date_end=date_end)
        if source == "piste":
            return _run_piste(
                config, store, log, force=force, date_start=date_start, date_end=date_end
            )
        raise ValueError(f"source inconnue : {source!r} (attendu : dila ou piste)")
    finally:
        if own_store:
            store.close()


class _Known:
    """Dédoublonnage des décisions déjà vues.

    L'identifiant technique (JURITEXT… ou identifiant Judilibre) et l'ECLI
    font foi. Le numéro de pourvoi n'est retenu que s'il n'a jamais désigné
    une autre décision : en chambre criminelle, des arrêts joints partagent
    parfois le même numéro, et les écarter serait une perte de matière.
    """

    def __init__(self, store: Store):
        self.ids: set[str] = set()
        self.eclis: set[str] = set()
        self.numbers: dict[str, set[str]] = {}
        for identifier, ecli, number in store.identity_index():
            if identifier:
                self.ids.add(identifier)
            if ecli:
                self.eclis.add(ecli)
            if number:
                self.numbers.setdefault(number, set()).add(identifier)

    def register(self, short: dict[str, Any]) -> None:
        identifier = str(short.get("id") or "")
        ecli = str(short.get("ecli") or "")
        number = str(short.get("number") or "")
        if identifier:
            self.ids.add(identifier)
        if ecli:
            self.eclis.add(ecli)
        if number:
            self.numbers.setdefault(number, set()).add(identifier)

    def is_new(self, short: dict[str, Any]) -> bool:
        identifier = str(short.get("id") or "")
        ecli = str(short.get("ecli") or "")
        number = str(short.get("number") or "")
        if identifier and identifier in self.ids:
            return False
        if ecli and ecli in self.eclis:
            return False
        if number and self.numbers.get(number) == {identifier}:
            return False
        return True


def _analyse_and_store(
    store: Store,
    config: Config,
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    log: Logger,
    force: bool,
    legifrance: LegifranceClient | None = None,
) -> tuple[int, int, int, int, list[dict[str, Any]]]:
    """Analyse puis enregistre les couples (short, full) inconnus.

    Retourne (analysés, nouveaux, bulletin, ignorés, fiches).
    """
    known = _Known(store)
    analysed = new_count = bulletin_count = skipped = 0
    cards: list[dict[str, Any]] = []

    total = len(pairs)
    verbeux = total <= 30
    for index, (short, full) in enumerate(pairs, start=1):
        deja_connu = not known.is_new(short)
        nouveau = not deja_connu
        if deja_connu and not force:
            skipped += 1
            continue
        if verbeux:
            log(f"  [{index}/{total}] pourvoi {short.get('number') or short.get('id')}")
        elif index % 50 == 0:
            log(f"  {index}/{total} traités…")
        try:
            card = build_card(short, full, config, legifrance)
        except Exception as exc:  # noqa: BLE001 - on ne stoppe pas le lot
            log(f"    ! analyse en échec pour {short.get('number')} : {exc}")
            continue
        store.upsert_decision(card.meta, card.raw, card.analysis)
        analysed += 1
        if nouveau:
            new_count += 1
        known.register(short)
        if card.meta.get("au_bulletin"):
            bulletin_count += 1
        cards.append(_card_as_dict(card))
    return analysed, new_count, bulletin_count, skipped, cards


def _finish(
    store: Store,
    config: Config,
    run_id: int,
    period_start: str,
    period_end: str,
    found: int,
    new_count: int,
    bulletin_count: int,
    source: str,
    log: Logger,
    releases: list[str] | None = None,
) -> RunResult:
    stored = store.decisions_between(period_start, period_end)
    stored_cards = [
        dict(row, analysis=row.get("analysis") or {}, raw=row.get("raw") or {}) for row in stored
    ]
    store.finish_run(run_id, found=found, new=new_count, bulletin=bulletin_count, status="ok")
    report_paths = write_reports(config, stored_cards, period_start, period_end)
    log(
        f"Terminé : {found} trouvé(s), {new_count} nouveau(x), "
        f"{bulletin_count} publié(s) au bulletin."
    )
    for kind, path in report_paths.items():
        log(f"  Rapport {kind} : {path}")
    return RunResult(
        date_start=period_start,
        date_end=period_end,
        found=found,
        new=new_count,
        analysed=found,
        bulletin=bulletin_count,
        skipped=0,
        cards=[_card_as_dict_from_row(card) for card in stored_cards],
        report_paths=report_paths,
        source=source,
        releases=releases or [],
    )


def _run_dila(
    config: Config,
    store: Store,
    log: Logger,
    *,
    force: bool,
    date_start: str | None = None,
    date_end: str | None = None,
) -> RunResult:
    """Actualisation via les fichiers d'appoint DILA (source par défaut)."""
    log("Lecture de l'index des données ouvertes DILA…")
    releases = dila_source.list_releases()
    log(f"{len(releases)} fichier(s) d'appoint disponible(s).")

    deja_traites = set(store.processed_releases())
    if force:
        a_traiter = releases
        log("Mode --force : tous les fichiers sont réanalysés.")
    else:
        a_traiter = [r for r in releases if r.name not in deja_traites]
    if not a_traiter:
        log("Aucun nouveau fichier d'appoint : rien à faire.")

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    # Chaque version est comptée pour être marquée « traitée » APRÈS l'écriture
    # effective des arrêts : une interruption en cours de route doit laisser la
    # version rejouable au prochain lancement.
    versions: list[tuple[Any, int]] = []
    for release in a_traiter:
        log(f"Fichier {release.name} (déposé le {release.date})")
        root = dila_source.download(release, config.cache_dir, log=log)
        trouves = dila_source.parse_release(root, release)
        if date_start or date_end:
            trouves = [
                p
                for p in trouves
                if (not date_start or p[0]["decision_date"] >= date_start)
                and (not date_end or p[0]["decision_date"] <= date_end)
            ]
        log(f"  {len(trouves)} arrêt(s) de la chambre criminelle.")
        pairs.extend(trouves)
        versions.append((release, len(trouves)))

    noms_traites = [release.name for release, _ in versions]
    if date_start and date_end:
        period_start, period_end = date_start, date_end
    elif pairs:
        period_start, period_end = dila_source.period_of([s for s, _ in pairs])
    else:
        run_id = store.start_run("", "")
        store.finish_run(run_id, found=0, new=0, bulletin=0, status="aucun nouveau fichier")
        return RunResult(
            date_start="", date_end="", found=0, new=0, analysed=0, bulletin=0,
            skipped=0, cards=[], report_paths={}, source="dila", releases=[],
        )
    run_id = store.start_run(period_start, period_end)
    log(f"Période couverte : {period_start} → {period_end}")

    analysed, new_count, bulletin_count, skipped, _cards = _analyse_and_store(
        store, config, pairs, log, force
    )
    if skipped:
        log(f"{skipped} arrêt(s) déjà connu(s), ignoré(s).")

    # Les versions ne sont déclarées traitées qu'une fois les arrêts écrits :
    # en cas d'interruption, elles seront reprises au prochain lancement.
    for release, count in versions:
        store.mark_release(release.name, release.date, release.url, count)

    return _finish(
        store, config, run_id, period_start, period_end, analysed, new_count,
        bulletin_count, "dila", log, releases=noms_traites,
    )


def _run_piste(
    config: Config,
    store: Store,
    log: Logger,
    *,
    force: bool,
    date_start: str | None = None,
    date_end: str | None = None,
) -> RunResult:
    """Actualisation via l'API Judilibre (PISTE, nécessite des identifiants)."""
    if date_start and date_end:
        period_start, period_end = date_start, date_end
    else:
        period_start, period_end = last_week()

    run_id = store.start_run(period_start, period_end)
    log(f"Période analysée : {period_start} → {period_end}")

    http = PisteClient(config)
    judilibre = JudilibreClient(config, http)
    legifrance = LegifranceClient(config, http) if config.enrich_legifrance else None

    publication_filter = ["b"] if config.only_bulletin else None
    log("Recherche Judilibre (chambre criminelle)…")
    shorts = judilibre.search(
        date_start=period_start,
        date_end=period_end,
        publication=publication_filter,
    )
    log(f"{len(shorts)} arrêt(s) retourné(s) par l'API.")

    known = store.known_keys()
    a_analyser: list[tuple[dict[str, Any], dict[str, Any]]] = []
    skipped = 0
    for short in shorts:
        if not force and _keys_of(short) & known:
            skipped += 1
            continue
        decision_id = str(short.get("id") or "")
        if not decision_id:
            continue
        try:
            full = judilibre.decision(decision_id)
        except Exception as exc:  # noqa: BLE001 - on ne stoppe pas le lot
            log(f"  ! texte indisponible pour {decision_id} ({exc})")
            continue
        if full:
            a_analyser.append((short, full))

    if skipped:
        log(f"{skipped} arrêt(s) déjà connu(s), ignoré(s).")
    if a_analyser:
        log(f"Téléchargement du texte intégral de {len(a_analyser)} arrêt(s)…")

    analysed, new_count, bulletin_count, skipped2, _cards = _analyse_and_store(
        store, config, a_analyser, log, force, legifrance
    )
    skipped += skipped2

    return _finish(
        store, config, run_id, period_start, period_end, len(shorts), new_count,
        bulletin_count, "piste", log,
    )


def _keys_of(short: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    if short.get("id"):
        keys.add(f"id:{short['id']}")
    if short.get("ecli"):
        keys.add(f"ecli:{short['ecli']}")
    if short.get("number"):
        keys.add(f"num:{short['number']}")
    return keys


def _card_as_dict(card: DecisionCard) -> dict[str, Any]:
    return {
        "meta": card.meta,
        "raw": card.raw,
        "analysis": card.analysis,
    }


def _card_as_dict_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Reconstruit une fiche depuis une ligne de base (le meta complet est
    conservé dans l'analyse au moment de l'écriture)."""
    analysis = row.get("analysis") or {}
    meta: dict[str, Any] = dict(analysis.get("meta") or {})
    publication = [str(p).lower() for p in (row.get("publication") or [])]
    meta.update(
        {
            "id": row.get("id"),
            "ecli": row.get("ecli"),
            "number": row.get("number"),
            "chamber": row.get("chamber"),
            "formation": row.get("formation"),
            "decision_date": row.get("decision_date"),
            "publication": publication,
            "publication_labels": publication_labels(publication),
            "au_bulletin": is_bulletin(publication),
            "au_rapport": is_rapport(publication),
            "solution": row.get("solution"),
            "solution_label": solution_label(row.get("solution")),
            "summary": row.get("summary"),
            "url": row.get("url"),
            "source": row.get("source"),
        }
    )
    return {"meta": meta, "analysis": analysis, "raw": row.get("raw") or {}}


def export_period(config: Config, date_start: str, date_end: str) -> Path:
    """Réécrit les rapports d'une période déjà présente en base."""
    store = Store(config.data_dir)
    rows = store.decisions_between(date_start, date_end)
    cards = [dict(row, analysis=row.get("analysis") or {}, raw=row.get("raw") or {}) for row in rows]
    paths = write_reports(config, cards, date_start, date_end)
    store.close()
    return Path(next(iter(paths.values())))
