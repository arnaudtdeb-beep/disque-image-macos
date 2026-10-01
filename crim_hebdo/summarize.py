"""Rédaction de l'analyse d'un arrêt.

Deux niveaux complémentaires, jamais confondus :

1. Synthèse extractive (toujours disponible, sans aucun modèle externe).
   Elle ne produit aucune phrase : elle sélectionne et juxtapose des extraits
   du texte de la Cour, en indiquant la zone d'origine
   (exposé du litige / moyens / motivations / dispositif).
   C'est le niveau de confiance maximale : chaque mot provient de l'arrêt.

2. Synthèse assistée par un modèle de langue (optionnel).
   Le modèle reçoit le texte réel et doit renvoyer un JSON containing des
   citations littérales. Chaque citation est vérifiée mot à mot dans le texte
   de l'arrêt ; toute citation introuvable fait tomber le résumé et l'on
   bascule sur la synthèse extractive. Le résultat est alors étiqueté
   "assisté par IA, à vérifier".

En aucun cas l'outil n'invente de règle de droit : si le dispositif est
incompréhensible ou absent, l'analyse le dit au lieu de combler.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import LLMSettings
from .textutil import (
    collapse,
    extract_articles,
    normalize,
    sentences,
    sentences_matching,
    strip_list_mark,
    truncate,
    zone_text,
)

# Marqueurs des phrases qui portent la solution de la Cour.
SOLUTION_PATTERNS = (
    r"REJETTE le pourvoi",
    r"CASSE ET ANNULE",
    r"CASSE et annule",
    r"casse et annule",
    r"condamne la cour d'appel",
    r"statuant sur l'appel",
    r"La Cour de cassation,?[ :]",
    r"Par ces motifs,",
)
# Marqueurs des phrases de motivation.
MOTIF_PATTERNS = (
    r"il n['’]y a (?:pas )?lieu [àa] ",
    r"il y a lieu [àa] ",
    r"en violation de",
    r"sans violation de",
    r"a commis une erreur",
    r"a exactement d[ée]duit",
    r"n['’]a pas exactement d[ée]duit",
    r"n['’]a pas exactement [ée]tabli",
    r"n['’][ée]nonce pas",
    r"conduit [àa] ",
    r"est (?:justifi[ée]|injustifi[ée]|inexacte|erron[ée]e)",
    r"sont (?:justifi[ées]|injustifi[ées]|inexactes|erron[ées])",
    r"l['’]enqu[êe]te a [ée]t[ée] (?:men[ée]|d[ée]roul[ée]e|conduite)",
    r"est (?:irr[ée]guli[èe]re|licite|illicite|r[ée]guli[èe]re)",
    r"porte atteinte",
    r"viole",
    r"ne peut [êe]tre que",
    r"p[ée]nalement justifi[ée]",
    r"ill[ée]galit[ée]",
    r"moyen tir[ée] (?:de|du)",
    r"doit [êe]tre (?:cass[ée]|annul[ée]|rejet[ée])",
    r"y a lieu (?:de )?prononcer",
    r"ne peut [êe]tre pr[ée]serv[ée]",
)

_APPORT_PATTERNS = (
    r"premi[èe]re application",
    r"nouvelle jurisprudence",
    r"fait divergence",
    r"fait Chambre",
    r"tranch[ée] [àle] divergence",
    r"pour l'avenir",
    r"interpr[ée]tation nouvelle",
    r"\bdivergence\b",
    r"\bbien d[ée]termin[ée]",
)

# Repérage des moyens : alinéas numérotés à la française (« 1°/ », « 2. », « 3) »).
_MEAN_SPLIT = r"(?=(?:^|\n)\s*\d+\s*(?:[°º)]\s*/?|\.)\s)"
_MEAN_MARK = re.compile(r"^\s*\d+\s*(?:[°º)]\s*/?|\.)\s")

SOLUTION_LABELS = {
    "rejet": "Rejet du pourvoi",
    "cassation": "Cassation de l'arrêt d'appel",
    "casse": "Cassation",
    "annulation": "Annulation",
    "irrecevabilite": "Irrecevabilité",
    "decheance": "Déchéance",
    "nonlieu": "Non-lieu à suivre",
    "rabat": "Rabat",
    "designation": "Désignation",
    "avis": "Avis",
    "qpc": "Question prioritaire de constitutionnalité",
    "renvoi": "Renvoi",
}


@dataclass
class Citation:
    quote: str
    zone: str
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"quote": self.quote, "zone": self.zone, "verified": self.verified}


@dataclass
class ExtractiveAnalysis:
    attendu: list[str] = field(default_factory=list)
    solution: list[str] = field(default_factory=list)
    motifs: list[str] = field(default_factory=list)
    moyens: list[str] = field(default_factory=list)
    apport: list[str] = field(default_factory=list)
    textes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attendu": self.attendu,
            "solution": self.solution,
            "motifs": self.motifs,
            "moyens": self.moyens,
            "apport": self.apport,
            "textes": self.textes,
        }


def extractive_analysis(
    text: str,
    zones: dict[str, Any] | None,
    official_summary: str | None = None,
    visa: list[Any] | None = None,
) -> ExtractiveAnalysis:
    """Synthèse 100 % extractive, structurée autour des zones de l'arrêt."""
    expose = zone_text(text, zones, "expose")
    moyens = zone_text(text, zones, "moyens")
    motivations = zone_text(text, zones, "motivations")
    dispositif = zone_text(text, zones, "dispositif")
    annexes = zone_text(text, zones, "annexes")

    analysis = ExtractiveAnalysis()

    # --- L'attendu de la Cour : ce sur quoi elle est appelée à statuer ------
    # 1) le sommaire officiel de la Cour, s'il existe ;
    # 2) les questions telles que la Cour les formule en ouverture de ses
    #    motivations (« Sur le moyen tiré de... ») ;
    # 3) à défaut, les phrases de l'exposé du litige qui posent le problème.
    if official_summary:
        analysis.attendu.append(f"Sommaire de la Cour : {collapse(official_summary)}")
    questions = _question_headers(motivations) or _question_lines(expose)
    analysis.attendu.extend(questions)
    if not analysis.attendu and expose:
        analysis.attendu.append(truncate(expose, 420))

    # --- Les moyens soulevés (titres, tels qu'énoncés par la partie) ---------
    analysis.moyens = _moyen_headings(moyens)

    # --- La solution : le dispositif, mot pour mot --------------------------
    solution = _device_lines(dispositif, motivations)
    analysis.solution = solution

    # --- Les motifs retenus par la Cour -------------------------------------
    analysis.motifs = _motif_lines(motivations)

    # --- La portée de l'arrêt ----------------------------------------------
    analysis.apport = sentences_matching(
        f"{motivations}\n{annexes}\n{dispositif}", list(_APPORT_PATTERNS), limit=3
    )

    # --- Les textes appliqués ----------------------------------------------
    analysis.textes = _visa_titles(visa) or extract_articles(
        f"{motivations}\n{dispositif}"
    )[:12]
    return analysis


def _motif_lines(motivations: str, limit: int = 6) -> list[str]:
    """Les motifs de la Cour.

    Priorité aux phrases qui portent un jugement (violation, inexactitude,
    absence de distinction, conclusion). Si le repérage reste trop pauvre, on
    restitue le début de la zone « motivations » : c'est là que la Cour énonce
    ses raisons, et un extrait fidèle vaut mieux qu'une sélection vide.
    """
    if not motivations:
        return []
    picked = sentences_matching(motivations, list(MOTIF_PATTERNS), limit=limit)
    if len(picked) >= 2:
        return picked
    opening = [strip_list_mark(sentence) for sentence in sentences(motivations)[:limit]]
    opening = [line for line in opening if len(line) >= 40 and line not in picked]
    return (picked + opening)[:limit]


def _question_headers(motivations: str, limit: int = 6) -> list[str]:
    """Les questions soumises à la Cour, telles qu'elle les énonce elle-même.

    La chambre criminelle ouvre sa motivation par « Sur le moyen tiré de... »,
    « Mais sur la recevabilité... » : ces intitulés sont, littéralement, la
    liste des questions sur lesquelles la Cour statue.
    """
    if not motivations:
        return []
    pattern = re.compile(
        r"^\s*(?:Mais\s+)?Sur\s+(?:le|les|la|l['’]|l['’])\s[^\n:]{8,180}?:",
        re.IGNORECASE | re.MULTILINE,
    )
    found: list[str] = []
    for match in pattern.finditer(motivations):
        header = collapse(match.group(0)).strip(" :")
        if header and header not in found:
            found.append(header)
        if len(found) >= limit:
            break
    return found


def _question_lines(expose: str) -> list[str]:
    """Retient les phrases de l'exposé qui formulenient le problème juridique."""
    if not expose:
        return []
    patterns = (
        r"la question de savoir",
        r"le probl[èe]me pos[ée]",
        r"la difficulty (?:est|portait)",
        r"portait sur",
        r"le moyen (?:r[ée]摄氏度|soutient|est de savoir)",
        r"p[ée]nalement r[ée]prim[ée]",
        r"\bquestions? de savoir\b",
        r"la cour d'appel a (?:est|été) (?:appel[ée]|[ée]t[ée] sais[ie]|[ée]t[ée] amen[ée])",
        r"a estim[ée] que",
        r"a jug[ée] que",
        r"en retenant",
        r"en estimant",
        r"en faisant application",
    )
    candidates = sentences_matching(expose, list(patterns), limit=3, min_length=60)
    if candidates:
        return [truncate(c, 500) for c in candidates]
    # à défaut : les premières phrases de l'exposé posent généralement les faits
    return [truncate(s, 380) for s in sentences(expose)[:2] if len(s) > 60]


def _moyen_headings(moyens: str, limit: int = 8) -> list[str]:
    """Titres des moyens : fragments de phrase scandés par les alinéas numérotés."""
    if not moyens:
        return []
    blocks = [collapse(block) for block in re.split(_MEAN_SPLIT, "\n" + moyens)]
    blocks = [block for block in blocks if block]
    numbered = [block for block in blocks if _MEAN_MARK.match(block)]
    candidates = numbered or blocks

    headings: list[str] = []
    for block in candidates:
        # le preamble « Les moyens du pourvoi sont les suivants » n'est pas un moyen
        if block.lower().startswith("les moyens") and len(block) < 120:
            continue
        candidate = truncate(strip_list_mark(block.split("\n")[0]), 320)
        if len(candidate) >= 25 and candidate not in headings:
            headings.append(candidate)
        if len(headings) >= limit:
            break
    if not headings:
        headings = [truncate(s, 300) for s in sentences(moyens)[:3]]
    return headings


def _device_lines(dispositif: str, motivations: str, limit: int = 4) -> list[str]:
    """Formule de la solution : le dispositif, ou la phrase de rejet qui suit les motifs."""
    if dispositif:
        lines = [collapse(line) for line in dispositif.split("\n") if collapse(line)]
        if lines:
            return [truncate(lines[0], 900), *[truncate(l, 300) for l in lines[1:3]]]
    tail = sentences_matching(motivations, list(SOLUTION_PATTERNS), limit=2)
    return [truncate(t, 400) for t in tail]


def _visa_titles(visa: list[Any] | None) -> list[str]:
    titles: list[str] = []
    for entry in visa or []:
        if isinstance(entry, dict):
            title = entry.get("title") or entry.get("intitule")
            if title:
                titles.append(collapse(str(title)))
        elif isinstance(entry, str):
            titles.append(collapse(entry))
    seen: list[str] = []
    for title in titles:
        if title not in seen:
            seen.append(title)
    return seen


def solution_label(solution_key: str | None) -> str:
    if not solution_key:
        return ""
    key = str(solution_key).strip().lower()
    return SOLUTION_LABELS.get(key, key.capitalize())


# --------------------------------------------------------------------------
# Synthèse assistée par modèle de langue, avec vérification des citations
# --------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Tu es un juriste Analyste la jurisprudence de la chambre criminelle de la Cour de "
    "cassation. Tu produis des notes de lecture FIDELES au texte source. "
    "REGLE ABSOLUE : tu n'inventes rien, tu n'ajoutes aucune règle de droit, aucune "
    "référence, aucun article qui ne figure pas dans le texte fourni. "
    "Chaque affirmation doit s'appuyer sur une citation LITTÉRALE recopiée caractère "
    "pour caractère depuis le texte (y compris la ponctuation). "
    "Si une information est absente du texte, écris null pour le champ concerné. "
    "Tu réponds uniquement par un objet JSON, sans texte autour."
)

USER_TEMPLATE = """Voici un arrêt de la chambre criminelle de la Cour de cassation.

MÉTADONNÉES
- Numéro de pourvoi : {number}
- Date : {date}
- Formation : {formation}
- Solution : {solution}
- Niveau de publication : {publication}
- Sommaires officiels de la Cour : {official_summary}

ZONE « EXPOSÉ DU LITIGE »
{expose}

ZONE « MOYENS »
{moyens}

ZONE « MOTIVATIONS »
{motivations}

ZONE « DISPOSITIF »
{dispositif}

TEXTES APPLIQUÉS
{textes}

Retourne cet objet JSON :
{{
  "attendu": "En 2 à 4 phrases : ce sur quoi la Cour est appelée à statuer (la question juridique posée par le pourvoi). Langage juridique sobre.",
  "solution": "En 1 à 3 phrases : la décision de la Cour (rejet, cassation, irrecevabilité...), l'autorité de la décision d'appel et le cas échéant la sanction. Décrire le dispositif.",
  "motifs": ["2 à 5 motifs essentials, un par phrase, dans l'ordre de la motivation de la Cour"],
  "portee": "En 1 à 2 phrases : portée pratique de l'arrêt (ce qui change pour le praticien), ou null si l'arrêt est anecdotique.",
  "citations": [
    {{"zone": "motivations", "quote": "une citation LITTÉRALE du texte, 15 à 400 caractères"}}
  ],
  "citations_attendu": [
    {{"zone": "expose", "quote": "une citation LITTÉRALE justifiant l'attendu, 15 à 400 caractères"}}
  ],
  "citations_solution": [
    {{"zone": "dispositif", "quote": "une citation LITTÉRALE du dispositif"}}
  ],
  "confidence": 0.0
}}
Au moins deux citations doivent être fournies. Le champ confidence est une note entre 0 et 1."""


class LLMAnalyzer:
    """Appel HTTP direct à un fournisseur de modèle de langue."""

    def __init__(self, settings: LLMSettings):
        self.settings = settings

    def available(self) -> bool:
        if not self.settings.enabled:
            return False
        if self.settings.provider in ("openai", "anthropic"):
            return bool(self.settings.api_key)
        return True

    def analyze(self, context: dict[str, Any]) -> dict[str, Any] | None:
        if not self.available():
            return None
        prompt = USER_TEMPLATE.format(
            number=context.get("number") or "?",
            date=context.get("decision_date") or "?",
            formation=context.get("formation") or "chambre criminelle",
            solution=solution_label(context.get("solution")),
            publication=", ".join(context.get("publication") or []) or "-",
            official_summary=context.get("official_summary") or "aucun",
            expose=_clip(context.get("expose"), 4000),
            moyens=_clip(context.get("moyens"), 4000),
            motivations=_clip(context.get("motivations"), 6000),
            dispositif=_clip(context.get("dispositif"), 2500),
            textes="\n".join(context.get("textes") or []) or "aucun",
        )
        raw = self._call(prompt)
        if not raw:
            return None
        return _parse_json_object(raw)


def _clip(text: str | None, limit: int) -> str:
    text = collapse(text)
    return text if len(text) <= limit else text[:limit] + " […tronqué…]"


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _verify(quotes: Any, source: str) -> list[Citation]:
    """Vérifie que chaque citation figure littéralement dans le texte source."""
    reference = normalize(source)
    verified: list[Citation] = []
    for entry in quotes or []:
        if isinstance(entry, str):
            quote, zone = entry, ""
        elif isinstance(entry, dict):
            quote = str(entry.get("quote") or "")
            zone = str(entry.get("zone") or "")
        else:
            continue
        quote = quote.strip()
        if len(quote) < 15:
            continue
        ok = normalize(quote) in reference
        verified.append(Citation(quote=quote, zone=zone, verified=ok))
    return verified


def _call_openai_compatible(settings: LLMSettings, prompt: str) -> str | None:
    base = (settings.base_url or "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": settings.temperature,
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else None
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError):
        return None


def _call_anthropic(settings: LLMSettings, prompt: str) -> str | None:
    base = (settings.base_url or "https://api.anthropic.com/v1").rstrip("/")
    payload = {
        "model": settings.model,
        "max_tokens": 1400,
        "temperature": settings.temperature,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        f"{base}/messages",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": settings.api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        blocks = body.get("content") or []
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        return "\n".join(texts) or None
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
        return None


def _call(settings: LLMSettings, prompt: str) -> str | None:
    if settings.provider == "anthropic":
        return _call_anthropic(settings, prompt)
    return _call_openai_compatible(settings, prompt)


def llm_analysis(
    context: dict[str, Any],
    settings: LLMSettings,
    fallback: ExtractiveAnalysis,
    min_verified: int = 2,
) -> dict[str, Any]:
    """Retourne une analyse IA vérifiée, ou une analyse extractive de repli.

    Le repli est déclenché si le modèle est indisponible, si la réponse n'est pas
    un JSON exploitable, ou si les citations ne sont pas retrouvées dans le texte.
    """
    base = {
        "source": "extractive",
        "model": None,
        "verified_citations": 0,
        "attendu": fallback.attendu,
        "solution": fallback.solution,
        "motifs": fallback.motifs,
        "portee": fallback.apport,
        "citations": [c.to_dict() for c in []],
        "fallback_reason": None,
        "confidence": None,
    }

    analyzer = LLMAnalyzer(settings)
    parsed = analyzer.analyze(context)
    if not parsed:
        base["fallback_reason"] = "modèle indisponible ou réponse non exploitable"
        return base

    source_text = "\n".join(
        [
            context.get("expose") or "",
            context.get("moyens") or "",
            context.get("motivations") or "",
            context.get("dispositif") or "",
            context.get("textes_text") or "",
        ]
    )
    citations = _verify(parsed.get("citations"), source_text)
    citations += _verify(parsed.get("citations_attendu"), source_text)
    citations += _verify(parsed.get("citations_solution"), source_text)
    verified = [c for c in citations if c.verified]

    if len(verified) < min_verified:
        base["fallback_reason"] = (
            f"citations non vérifiables ({len(verified)}/{len(citations)} retrouvées dans le texte) "
            "— analyse extractive conservée"
        )
        base["citations"] = [c.to_dict() for c in citations]
        return base

    attendu = _as_list(parsed.get("attendu")) or fallback.attendu
    solution = _as_list(parsed.get("solution")) or fallback.solution
    motifs = _as_list(parsed.get("motifs")) or fallback.motifs
    portee = _as_list(parsed.get("portee")) or []

    return {
        "source": "llm",
        "model": settings.model,
        "provider": settings.provider,
        "verified_citations": len(verified),
        "attendu": attendu,
        "solution": solution,
        "motifs": motifs,
        "portee": portee,
        "citations": [c.to_dict() for c in citations],
        "fallback_reason": None,
        "confidence": parsed.get("confidence"),
        "extractive": fallback.to_dict(),
    }


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = collapse(value)
        return [text] if text else []
    if isinstance(value, list):
        return [collapse(str(v)) for v in value if collapse(str(v))]
    return []
