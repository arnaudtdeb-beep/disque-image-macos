"""Utilitaires de traitement du texte des arrêts.

Objectif : produire des extraits fidèles, sans réécriture. On découpe, on
selectionne, on cites — on n'invente jamais de phrase.
"""

from __future__ import annotations

import re
import unicodedata

# Zones Judilibre : segments {start, end} indexes dans le texte integral.
ZONE_ORDER = ("introduction", "expose", "moyens", "motivations", "dispositif", "annexes")

_ABREVIATIONS = {
    "art", "arts", "c", "cp", "civ", "crim", "cch", "cj", "cass", "ch", "chb",
    "conv", "cg", "d", "dir", "div", "éd", "eds", "fr", "i", "ii", "iii", "iv",
    "m", "mm", "n", "no", "nos", "not", "p", "pp", "pr", "qpc", "r", "s", "sav",
    "ss", "t", "v", "vf", "vr", "art", "al", "cpc", "csp", "cpp", "cjpm", "cim",
    "l", "annex", "av", "cf", "ibid", "env", "qq", "réf", "ibid", "not",
}

# Abréviations suiviES d'une référence (« L. 628-1 », « art. 63-2 ») : le point
# ne clôt pas une phrase. On les protège avant de découper.
_LEGAL_REF = re.compile(r"\b(L|D|R|S|art|al|cf|annex)\.\s+(?=[A-Z0-9])")
_SENTINEL = "\x00"

_SENTENCE_SPLIT = re.compile(r"(?<=[\.\;\:\»\)\!\?])\s+(?=[«A-ZÀ-Ÿ0-9])")
_WS = re.compile(r"[ \t ]+")
_MULTI_NL = re.compile(r"\n{2,}")
_LIST_MARK = re.compile(r"^\s*(?:\d+\s*[°º)]\s*/?\s*[:.]?|[-•*]|[a-z]\))\s*", re.IGNORECASE)
# Une référence d'article : 62, 63-2, 122.1, 706-14, 217-1…
_ARTICLE_REF = r"\d+[A-Za-z]*(?:\.\d+)*(?:-\d+[A-Za-z]*)*"
_ARTICLE = re.compile(
    rf"\b(?:articles?|art\.?)\s+({_ARTICLE_REF}(?:\s*(?:,|et|ou|à)\s*{_ARTICLE_REF})*)",
    re.IGNORECASE,
)
_ECLI = re.compile(r"ECLI\s*:\s*[A-Z]{2}\s*:\s*[A-Z0-9]+\s*:\s*\d{4}\s*:\s*[A-Z0-9.]+", re.IGNORECASE)


def normalize(text: str | None) -> str:
    """Normalise pour comparaison (accents, espaces, ponctuation)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace(" ", " ").replace(" ", " ")
    return _WS.sub(" ", text).strip().lower()


def collapse(text: str) -> str:
    return _MULTI_NL.sub("\n", _WS.sub(" ", text or "")).strip()


def sentences(text: str) -> list[str]:
    """Découpe en phrases en respectant les abréviations juridiques."""
    if not text:
        return []
    guarded = _LEGAL_REF.sub(lambda m: m.group(1) + "." + _SENTINEL, collapse(text))
    chunks = _SENTENCE_SPLIT.split(guarded)
    out: list[str] = []
    buffer = ""
    for chunk in chunks:
        candidate = f"{buffer} {chunk}".strip() if buffer else chunk.strip()
        if not candidate:
            continue
        tail = re.split(r"[\s]", candidate.rstrip(".!?;:"))[-1].lower().rstrip(".")
        if tail in _ABREVIATIONS:
            buffer = candidate
            continue
        out.append(candidate)
        buffer = ""
    if buffer:
        out.append(buffer)
    return [s.replace(_SENTINEL, " ") for s in out if len(s) > 1]


def zone_text(text: str, zones: dict[str, Any] | None, zone: str) -> str:
    """Reconstruit une zone a partir des segments {start, end}."""
    if not text or not zones:
        return ""
    segments = zones.get(zone) or []
    parts: list[str] = []
    for segment in segments:
        try:
            start = int(segment["start"])
            end = int(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= start < end <= len(text):
            parts.append(text[start:end])
    return collapse("\n".join(parts))


def all_zones(text: str, zones: dict[str, Any] | None) -> dict[str, str]:
    return {zone: zone_text(text, zones, zone) for zone in ZONE_ORDER}


# ------------------------------------------------------------------ données DILA
# L'open data ne fournit pas les zones Judilibre : on les retrouve par repères.
# Mêmes clés, mêmes index {start, end} → le reste de la chaîne est inchangé.
_MOTIFS = re.compile(r"\bPAR\s+CES\s+MOTIFS\b", re.IGNORECASE)
_MOYENS = re.compile(r"\b(?:Les\s+moyens|moyens\s+du\s+pourvoi)\b", re.IGNORECASE)
_DISPOSITIF = re.compile(
    r"(?m)^[\s,;:.\u2013\u2014()\u00ab*]*\s*(?:LA\s+COUR\s*:?\s*)?(?:a\s+d[\u00e9e]cid[\u00e9e]\s+de\s+)?\**\s*"
    r"(?:REJETTE|CASSE|CASSE[EA]|ANNULE|RENVOIE|D[\u00c9E]CLARE|ORDONNE|DIT|STATUE|PRONONCE|CONSTATE)",
    re.IGNORECASE,
)
_FIN_ARRET = re.compile(r"\bAinsi\s+fait\s+et\s+jug[\u00e9e]\b", re.IGNORECASE)
_ENTETE = re.compile(r"a\s+rendu\s+l[\u2019']arr[\u00eae]t\s+suivant\s*:?", re.IGNORECASE)
_BLOC_TITRE = re.compile(r"ARR[\u00caE]T\s+DE\s+LA\s+COUR\s+DE\s+CASSATION[^\n]*", re.IGNORECASE)
_ALINENUM = re.compile(r"(?m)^\s*1\s*[.)]\s+\S")
_TITRE_MOTIF = re.compile(
    r"(?mi)^\s*(?:motifs?|I\.|A\.|1\.\s*sur)(?:\s+de\s+la\s+d[\u00e9e]cision)?\s*$"
    r"|^\s*Sur\s+(?:le|la|les|l[\u2019'])"
)


def _span(start: int, end: int, length: int) -> list[dict[str, int]]:
    start = max(0, min(start, length))
    end = max(0, min(end, length))
    return [{"start": start, "end": end}] if end > start else []


def _reasoning_start(text: str, body_start: int, intro_end: int) -> int | None:
    """Début de la motivation : première.alinéa numéroté de la Cour.

    Dans les arrêts publiés au bulletin, la motivation est une suite d'alinéas
    numérotés (« 1. », « 2. »…) qui précèdent la formule « PAR CES MOTIFS ».
    """
    numbered = _ALINENUM.search(text, max(body_start, intro_end - 200), len(text))
    if numbered:
        # on rattache à la motivation le titre qui la précède (« Sur le moyen… »)
        heading = None
        for match in _TITRE_MOTIF.finditer(text, max(body_start, intro_end - 200), numbered.start()):
            if match.end() > intro_end:
                heading = match.start()
        return heading if heading is not None else numbered.start()
    return None


def split_zones_by_markers(text: str) -> dict[str, list[dict[str, int]]]:
    """Zones d'un arrêt à partir de ses repères rédactionnels.

    L'open data DILA donne le texte à plat, sans les index de Judilibre. On
    retrouve les articulations employées par la Cour (bandeau d'en-tête,
    « Sur le rapport », « Les moyens », les alinéas de motivation,
    « PAR CES MOTIFS », le dispositif, « Ainsi fait et jugé ») pour produire la
    même structure d'index que Judilibre : l'analyse est identique quelle que
    soit la source.
    """
    zones: dict[str, list[dict[str, int]]] = {zone: [] for zone in ZONE_ORDER}
    length = len(text or "")
    if not text or not length:
        return zones

    # Bandeau d'en-tête : « ... a rendu l'arrêt suivant : ARRÊT DE LA COUR DE
    # CASSATION, CHAMBRE CRIMINELLE, DU 10 MARS 2026 ». L'exposé commence après.
    entete = _ENTETE.search(text)
    body_start = entete.end() if entete else 0
    titre = _BLOC_TITRE.search(text, body_start)
    if titre and len(text[titre.end():].strip()) > 400:
        body_start = titre.end()
        # la date du prononcé figure sur la ou les lignes suivantes
        for _ in range(2):
            ligne = text[body_start:].split("\n", 1)
            if len(ligne) < 2:
                break
            contenu = ligne[0].strip()
            if contenu and not re.fullmatch(r"(?:DU\s+)?\d{1,2}\s+[A-Z\u00c9\u00c8\u00ca]+\s+\d{4}", contenu):
                break
            body_start += len(ligne[0]) + 1

    # « Ainsi fait et jugé par la Cour de cassation » clôt l'arrêt.
    signature = _FIN_ARRET.search(text)
    body_end = signature.start() if signature else length

    # Introduction : la phrase de composition (« Sur le rapport de ..., a rendu
    # le présent arrêt. »).
    intro_end = body_start
    sur_rapport = re.search(r"\bSur\s+le\s+rapport\b", text[body_start:body_end], re.IGNORECASE)
    if sur_rapport:
        start = body_start + sur_rapport.start()
        premiere = sentences(text[start : start + 1500])
        end = start + (len(premiere[0]) if premiere else 200)
        intro_end = end
        zones["introduction"] = _span(start, end, length)

    motifs_marqueur = _MOTIFS.search(text, body_start)
    raisonnement = _reasoning_start(text, body_start, intro_end)

    # Dispositif : le premier énoncé de décision après la formule
    # « PAR CES MOTIFS, la Cour : », ou à défaut après la motivation.
    plancher = motifs_marqueur.end() if motifs_marqueur else (raisonnement or body_start)
    dispositif = None
    for match in _DISPOSITIF.finditer(text, plancher, body_end):
        dispositif = match.start()
        break
    if dispositif is None:
        dispositif = body_end

    # Les moyens du pourvoi, lorsqu'ils sont énoncés avant la motivation.
    borne_moyens = raisonnement if raisonnement is not None else dispositif
    moyens = _MOYENS.search(text, intro_end, borne_moyens) if borne_moyens > intro_end else None
    if moyens:
        zones["moyens"] = _span(moyens.end(), borne_moyens, length)
        expose_end = moyens.start()
    else:
        expose_end = raisonnement if raisonnement is not None else dispositif

    if expose_end > body_start:
        zones["expose"] = _span(body_start, expose_end, length)

    if raisonnement is not None:
        fin_motifs = motifs_marqueur.start() if motifs_marqueur else dispositif
        if fin_motifs > raisonnement:
            zones["motivations"] = _span(raisonnement, fin_motifs, length)

    zones["dispositif"] = _span(dispositif, length, length)
    # Annexes : ce qui suit réellement la signature, pas la formule de clôture.
    if signature and signature.end() + 200 < length:
        zones["annexes"] = _span(signature.end(), length, length)
    return zones


def strip_list_mark(sentence: str) -> str:
    return _LIST_MARK.sub("", sentence).strip()


def extract_articles(text: str) -> list[str]:
    """Références d'articles citées (dédupliquées, ordre d'apparition).

    Gère les énumérations : « les articles 62, 63-2 et 431 du code ».
    """
    seen: list[str] = []
    for match in _ARTICLE.finditer(text or ""):
        for ref in re.findall(_ARTICLE_REF, match.group(1)):
            ref = ref.rstrip(".,;:")
            if ref and ref not in seen:
                seen.append(ref)
    return seen


def find_ecli(text: str) -> str | None:
    match = _ECLI.search(text or "")
    return match.group(0).replace(" ", "").upper() if match else None


def truncate(text: str, limit: int = 480) -> str:
    text = collapse(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "; ", ", "):
        pos = cut.rfind(sep)
        if pos > limit * 0.6:
            return cut[: pos + 1].strip()
    return cut.rsplit(" ", 1)[0] + "…"


def sentences_matching(
    text: str,
    patterns: list[str],
    limit: int = 6,
    min_length: int = 40,
) -> list[str]:
    """Sentences contenant l'un des motifs (regex, insensitive a la casse)."""
    if not text:
        return []
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    found: list[str] = []
    for sentence in sentences(text):
        if len(sentence) < min_length:
            continue
        if any(rx.search(sentence) for rx in compiled):
            cleaned = strip_list_mark(sentence)
            if cleaned and cleaned not in found:
                found.append(cleaned)
        if len(found) >= limit:
            break
    return found


def count_matches(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text or "", re.IGNORECASE))
