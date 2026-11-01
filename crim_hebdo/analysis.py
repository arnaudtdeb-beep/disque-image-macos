"""Assemblage de la fiche d'analyse d'un arrêt.

Une fiche = métadonnées fiables (Judilibre) + zones structurées + repérage
thématique justifié + synthèse extractive (+ synthèse IA vérifiée le cas échéant).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .config import Config
from .legifrance import LegifranceClient, publication_details
from .summarize import (
    ExtractiveAnalysis,
    extractive_analysis,
    llm_analysis,
    solution_label,
)
from .textutil import all_zones, collapse, find_ecli
from .themes import classify, official_themes

# Niveaux de publication Judilibre. Le libellé officiel complet est relu
# depuis /taxonomy?id=publication quand le compte y a accès.
# Libellés officiels de la taxonomie Judilibre (/taxonomy?id=publication) :
#   b = Publié au Bulletin, r = Publié au Rapport,
#   l = Publié aux Lettres de chambre, c = Communiqué, n = Non publié.
PUBLICATION_LABELS = {
    "b": "Publié au bulletin (B)",
    "r": "Publié au rapport (R) — décision de principe",
    "l": "Publié aux lettres de chambre (L)",
    "c": "Avec communiqué de la Cour (C)",
    "n": "Non publié (inédit)",
}

COUR_URL = "https://www.courdecassation.fr/decision/{id}"
COUR_SEARCH_URL = "https://www.courdecassation.fr/recherche-judilibre?judilibre_juridiction=cc"


# Judilibre renvoie parfois les codes (b, r, l, c, n) et parfois les libellés
# en toutes lettres (« Publié au bulletin »). On ramène tout aux codes pour que
# les tests et compteurs (bulletin, rapport, inédit) soient fiables.
_PUBLICATION_TEXT_TO_CODE = {
    "publié au bulletin": "b",
    "publie au bulletin": "b",
    "bulletin": "b",
    "publié au rapport": "r",
    "publie au rapport": "r",
    "rapport": "r",
    "publié aux lettres de chambre": "l",
    "publie aux lettres de chambre": "l",
    "lettres de chambre": "l",
    "lettres": "l",
    "communiqué": "c",
    "communique": "c",
    "non publié": "n",
    "non publie": "n",
    "inédit": "n",
    "inedit": "n",
}


def normalize_publication(values: list[str] | None) -> list[str]:
    """Ramène chaque valeur (code ou libellé) au code Judilibre canonique.

    Les valeurs inconnues sont conservées en minuscules pour ne rien perdre.
    """
    out: list[str] = []
    for raw in values or []:
        key = str(raw).strip().lower()
        code = _PUBLICATION_TEXT_TO_CODE.get(key, key)
        if code and code not in out:
            out.append(code)
    return out


def publication_labels(keys: list[str] | None) -> list[str]:
    return [PUBLICATION_LABELS.get(str(k).lower(), str(k).upper()) for k in keys or []]


def is_bulletin(keys: list[str] | None) -> bool:
    return any(str(k).lower() == "b" for k in keys or [])


def is_rapport(keys: list[str] | None) -> bool:
    return any(str(k).lower() == "r" for k in keys or [])


# Clés qui, à elles seules, signalent une décision « publiée » au sens de la
# taxonomie Judilibre : bulletin, rapport, lettres de chambre, communiqué.
# Tout le reste — et notamment « n » (= non publié) ou une liste vide — vaut
# « inédit ». C'est le cas de la grande majorité des arrêts Judilibre.
PUBLISHED_KEYS = {"b", "r", "l", "c"}


def is_unpublished(keys: list[str] | None) -> bool:
    """Vrai si la décision n'est ni au bulletin ni au rapport ni autrement publiée.

    Ce cas n'apparaît qu'avec la source Judilibre : les fichiers DILA ne
    contiennent que des arrêts publiés au bulletin. Une décision « inédite »
    est donc, en pratique, un arrêt non publié récupéré via l'API Judilibre.
    """
    published = {str(k).lower() for k in keys or []}
    return not (published & PUBLISHED_KEYS)


@dataclass
class DecisionCard:
    meta: dict[str, Any]
    analysis: dict[str, Any]
    raw: dict[str, Any]

    @property
    def identifiant(self) -> str:
        return str(self.meta.get("id") or self.meta.get("ecli") or "")


def _title_of(raw: dict[str, Any]) -> str | None:
    """Titrage / sommaire officiel, lorsque la Cour l'a publié."""
    entries = raw.get("titlesAndSummaries") or []
    for entry in entries:
        if isinstance(entry, dict):
            for key in ("title", "summary", "sommaire", "label"):
                value = entry.get(key)
                if isinstance(value, str) and collapse(value):
                    return collapse(value)
                if isinstance(value, list) and value:
                    first = value[0]
                    if isinstance(first, dict):
                        inner = first.get("title") or first.get("text")
                        if isinstance(inner, str) and collapse(inner):
                            return collapse(inner)
    return None


def build_card(
    short: dict[str, Any],
    full: dict[str, Any],
    config: Config,
    legifrance: LegifranceClient | None = None,
) -> DecisionCard:
    """Construit la fiche complète d'un arrêt à partir des métadonnées et du texte."""
    text = full.get("text") or ""
    zones = full.get("zones") or {}
    zone_texts = all_zones(text, zones)

    publication = normalize_publication(short.get("publication") or full.get("publication"))
    official_summary = short.get("summary") or _title_of(full)
    ecli = short.get("ecli") or find_ecli(text)

    extractive = extractive_analysis(
        text=text,
        zones=zones,
        official_summary=official_summary,
        visa=full.get("visa"),
    )

    context = {
        "number": short.get("number"),
        "decision_date": short.get("decision_date"),
        "formation": short.get("formation"),
        "solution": short.get("solution"),
        "publication": publication,
        "official_summary": official_summary,
        "expose": zone_texts["expose"],
        "moyens": zone_texts["moyens"],
        "motivations": zone_texts["motivations"],
        "dispositif": zone_texts["dispositif"],
        "annexes": zone_texts["annexes"],
        "textes": extractive.textes,
        "textes_text": "\n".join(extractive.textes),
    }

    analysis: dict[str, Any] = {}
    llm_used = False
    if config.use_llm and config.llm.enabled:
        llm = llm_analysis(context, config.llm, extractive)
        analysis = llm
        llm_used = llm.get("source") == "llm"

    themes = classify(zone_texts, text, official_matters=official_themes(short))
    bulletin = is_bulletin(publication)

    meta: dict[str, Any] = {
        "id": short.get("id") or full.get("id"),
        "ecli": ecli,
        "number": short.get("number"),
        "numbers": short.get("numbers") or [],
        "chamber": short.get("chamber"),
        "formation": short.get("formation"),
        "decision_date": short.get("decision_date"),
        "type": short.get("type"),
        "solution": short.get("solution"),
        "solution_label": solution_label(short.get("solution")),
        "publication": publication,
        "publication_labels": publication_labels(publication),
        "au_bulletin": bulletin,
        "au_rapport": is_rapport(publication),
        "inedit": is_unpublished(publication),
        "summary": official_summary,
        "particulier_interet": bool(short.get("particularInterest") or full.get("particularInterest")),
        "extrait_partiel": bool(full.get("partial")),
        "url": short.get("url") or COUR_URL.format(id=short.get("id")),
        "source": short.get("source") or full.get("source") or "judilibre",
        "update_date": full.get("update_date"),
        "themes_officiels": official_themes(short),
        "nac": full.get("nac"),
    }

    if legifrance is not None and short.get("number"):
        hit = legifrance.search_by_number(str(short["number"]))
        details = publication_details(hit)
        if details:
            meta["legifrance"] = details
            if "b" in details:
                meta["au_bulletin"] = True
                meta["bulletin_numero"] = next(
                    (entry.get("numero") for entry in details.get("b", []) if entry.get("numero")), None
                )
            if details.get("url"):
                meta["url_legifrance"] = details["url"]

    analysis_payload: dict[str, Any] = {
        "meta": meta,
        "themes": [t.to_dict() for t in themes],
        "extractive": extractive.to_dict(),
        "solution_label": meta["solution_label"],
        "llm": analysis if analysis else None,
        "llm_utilise": llm_used,
        "fiabilite": (
            "synthese IA verifiee (citations retrouvees dans le texte de l'arrêt)"
            if llm_used
            else "synthese extractive (extraits mot pour mot de l'arrêt)"
        ),
        "portee": (analysis or {}).get("portee") or extractive.apport,
        "attendu": (analysis or {}).get("attendu") or extractive.attendu,
        "solution_texte": (analysis or {}).get("solution") or extractive.solution,
        "motifs": (analysis or {}).get("motifs") or extractive.motifs,
        "citations": (analysis or {}).get("citations") or [],
        "moyens": extractive.moyens,
        "textes_appliques": extractive.textes,
        "generated_at": date.today().isoformat(),
    }

    raw_payload = {
        "zones": zones,
        "visa": full.get("visa"),
        "text": text,
        "rapprochements": full.get("rapprochements") or [],
        "contested": full.get("contested"),
        "forward": full.get("forward"),
        "titlesAndSummaries": full.get("titlesAndSummaries") or [],
    }

    return DecisionCard(meta=meta, analysis=analysis_payload, raw=raw_payload)


def summarise_for_display(card: DecisionCard) -> dict[str, Any]:
    """Projection allégée destinée à l'interface web et aux rapports."""
    return {
        "id": card.meta.get("id"),
        "ecli": card.meta.get("ecli"),
        "number": card.meta.get("number"),
        "numbers": card.meta.get("numbers"),
        "chamber": card.meta.get("chamber"),
        "formation": card.meta.get("formation"),
        "decision_date": card.meta.get("decision_date"),
        "type": card.meta.get("type"),
        "solution": card.meta.get("solution"),
        "solution_label": card.meta.get("solution_label"),
        "publication": card.meta.get("publication"),
        "publication_labels": card.meta.get("publication_labels"),
        "au_bulletin": card.meta.get("au_bulletin"),
        "au_rapport": card.meta.get("au_rapport"),
        "inedit": card.meta.get("inedit"),
        "bulletin_numero": card.meta.get("bulletin_numero"),
        "summary": card.meta.get("summary"),
        "themes_officiels": card.meta.get("themes_officiels"),
        "particulier_interet": card.meta.get("particulier_interet"),
        "extrait_partiel": card.meta.get("extrait_partiel"),
        "url": card.meta.get("url"),
        "url_legifrance": card.meta.get("url_legifrance"),
        "themes": card.analysis.get("themes"),
        "attendu": card.analysis.get("attendu"),
        "solution_texte": card.analysis.get("solution_texte"),
        "motifs": card.analysis.get("motifs"),
        "portee": card.analysis.get("portee"),
        "moyens": card.analysis.get("moyens"),
        "textes_appliques": card.analysis.get("textes_appliques"),
        "citations": card.analysis.get("citations"),
        "fiabilite": card.analysis.get("fiabilite"),
        "llm_utilise": card.analysis.get("llm_utilise"),
        "raw_text": card.raw.get("text"),
    }
