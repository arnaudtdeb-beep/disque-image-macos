"""Source « données ouvertes » de la Cour de cassation (opendata DILA).

Aucune authentification, aucune clé, aucun quota : la DILA publie chaque semaine
un fichier d'appoint contenant les décisions nouvellement ouvertes au public.

    https://echanges.dila.gouv.fr/OPENDATA/CASS/CASS_AAAAMMJJ-HHMMSS.tar.gz

Un tel fichier contient des XML `TEXTE_JURI_JUDI` (le même format que les
données de Légifrance) : métadonnées complètes, sommaire officiel de la Cour,
visa, et **texte intégral de l'arrêt**. C'est la solution de repli quand l'API
Judilibre via PISTE n'est pas accessible.

Ce module produit exactement les mêmes structures que `judilibre.py`
(`short` + `full`), de sorte que l'analyse, le classement thématique et les
rapports sont identiques quelle que soit la source.
"""

from __future__ import annotations

import re
import shutil
import tarfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.request import Request, urlopen

from .textutil import collapse, split_zones_by_markers

BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA/CASS/"
LEGIFRANCE_URL = "https://www.legifrance.gouv.fr/juri/id/{id}"
USER_AGENT = "crim-hebdo/1.0 (+veille chambre criminelle, open data DILA)"

# Dossier du fichier d'appoint correspondant à la chambre criminelle.
CASS_CRIM = "criminelle"

_RELEASE_NAME = re.compile(r'href="(CASS_(\d{8})-(\d{6})\.tar\.gz)"[^>]*>([^<]+)</a>')
_RELEASE_ROW = re.compile(
    r'href="(CASS_(\d{8})-(\d{6})\.tar\.gz)"[^>]*>[^<]*</a>\s*'
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})?\s*([0-9.]+[KMG]?)?'
)
_SIZE_UNITS = {"K": 1024, "M": 1024**2, "G": 1024**3}


class DilaError(RuntimeError):
    """Indisponibilité ou anomalie du flux de données ouvertes."""


@dataclass(frozen=True)
class Release:
    """Un fichier d'appoint hebdomadaire."""

    name: str
    url: str
    published: str  # date de dépôt, ISO
    size_bytes: int | None = None

    @property
    def date(self) -> str:
        return self.published[:10]


def _human_size(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"([0-9.]+)([KMG]?)", value.strip())
    if not match:
        return None
    number = float(match.group(1))
    return int(number * _SIZE_UNITS.get(match.group(2).upper(), 1))


def _http_get(url: str, timeout: int = 60) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL DILA figée
            return response.read()
    except Exception as exc:  # noqa: BLE001
        raise DilaError(f"accès impossible à {url} : {exc}") from exc


def list_releases(timeout: int = 60) -> list[Release]:
    """Liste des fichiers d'appoint publiés, du plus récent au plus ancien."""
    body = _http_get(BASE_URL, timeout=timeout).decode("utf-8", "replace")
    releases: dict[str, Release] = {}
    for name, stamp, _time, published, size in _RELEASE_ROW.findall(body):
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        releases[name] = Release(
            name=name,
            url=BASE_URL + name,
            published=published[:10] or day,
            size_bytes=_human_size(size),
        )
    if not releases:
        raise DilaError(
            "aucun fichier CASS_*.tar.gz trouvé dans l'index DILA : "
            "l'index a peut-être changé de forme, voir " + BASE_URL
        )
    return sorted(releases.values(), key=lambda r: (r.date, r.name), reverse=True)


def latest_releases(limit: int = 1, timeout: int = 60) -> list[Release]:
    return list_releases(timeout=timeout)[:limit]


def release_url(name: str) -> str:
    return BASE_URL + name


# ------------------------------------------------------------------ téléchargement
def download(release: Release, cache_dir: str | Path, log: Callable[[str], None] = lambda _m: None) -> Path:
    """Télécharge et décompresse un fichier d'appoint dans un dossier dédié.

    Le dossier d'extraction porte le nom exact du fichier : sans cela, une
    archive dont la racine interne diffère ferait retomber l'appelant sur le
    cache entier, et chaque fichier serait rescanné avec tous les précédents.
    """
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    extracted = cache / release.name
    archive = cache / f"{release.name}.download"

    if extracted.is_dir():
        return extracted

    if not archive.is_file():
        log(f"  téléchargement {release.name}…")
        payload = _http_get(release.url, timeout=300)
        partial = archive.with_suffix(".part")
        partial.write_bytes(payload)
        partial.replace(archive)

    log(f"  décompression {release.name}…")
    staging = extracted.with_suffix(".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            _safe_extract(tar, staging)
        staging.replace(extracted)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return extracted


def _safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    """Extraction sans traverser le répertoire cible."""
    target = target.resolve()
    for member in tar.getmembers():
        destination = (target / member.name).resolve()
        if target not in destination.parents and destination != target:
            raise DilaError(f"archive DILA refusée : entrée hors périmètre {member.name}")
    tar.extractall(target)  # noqa: S202 - members vérifiés ci-dessus


def iter_decision_files(root: str | Path) -> Iterator[Path]:
    """Fichiers XML de la chambre criminelle d'un fichier d'appoint."""
    root = Path(root)
    if not root.is_dir():
        return
    yield from sorted(p for p in root.rglob("*.xml") if CASS_CRIM in p.parts)


# ------------------------------------------------------------------ parsing
def _text_of(element: ET.Element | None) -> str:
    """Texte d'un noeud XML en convertissant les <br/> en retours à la ligne."""
    if element is None:
        return ""
    parts: list[str] = [element.text or ""]
    for child in element:
        parts.append("\n" if child.tag.lower() == "br" else _text_of(child))
        parts.append(child.tail or "")
    raw = "".join(parts)
    raw = raw.replace("\u00a0", " ").replace("\u202f", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    return re.sub(r"\n{3,}", "\n\n", raw).strip()


def format_number(raw: str | None) -> str | None:
    """Normalise un numéro de pourvoi : « 24-82494 », « 2482494 » → « 24-82.494 »."""
    if not raw:
        return None
    value = raw.strip()
    digits = re.sub(r"\D", "", value)
    if len(digits) == 7:  # AA-NN.NNN
        return f"{digits[:2]}-{digits[2:4]}.{digits[4:]}"
    if len(digits) == 8:  # AAA-NN.NNN
        return f"{digits[:3]}-{digits[3:5]}.{digits[5:]}"
    return value or None


def sommaire_of(root: ET.Element) -> list[dict[str, str]]:
    """Sommaire officiel de la Cour, avec sa hiérarchie (« - » et indentation)."""
    entries: list[dict[str, str]] = []
    for node in root.findall(".//SOMMAIRE/SCT"):
        if node.get("TYPE") == "REFERENCE" or not node.text:
            continue
        label = collapse(node.text.replace(" -", "\n-"))
        entries.append({"label": label, "type": node.get("TYPE") or ""})
    return entries


def sommaire_lines(entries: list[dict[str, str]]) -> list[str]:
    """Le sommaire rendu en lignes lisibles, pour l'« attendu »."""
    lines: list[str] = []
    for entry in entries:
        for line in (entry.get("label") or "").splitlines():
            line = line.strip(" -–")
            if line:
                lines.append(line)
    return lines


def _visa_of(text: str) -> list[dict[str, str]]:
    """Textes appliqués : les mentions « Vu … » de l'en-tête de l'arrêt."""
    visa: list[dict[str, str]] = []
    lines = text.split("\n")
    for index, block in enumerate(lines):
        stripped = block.strip()
        if not re.match(r"^V[us]\s", stripped) or len(stripped) <= 12:
            continue
        entry = stripped
        # les rubriques courent sur plusieurs lignes (« Vu le code … ,\narticle 62 ; »)
        for continuation in lines[index + 1 : index + 6]:
            nxt = continuation.strip()
            if not nxt or re.match(r"^(?:V[us]|Sur\s|LA\s+COUR|OU\s+LA\s+COUR|[A-ZÉÈ]{4,})", nxt):
                break
            entry += " " + nxt.rstrip(";.")
        entry = entry.strip().rstrip(";.:").strip()
        if entry and entry not in [v["title"] for v in visa]:
            visa.append({"title": entry})
    return visa[:12]


def parse_decision(path: str | Path, release: Release | None = None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """XML DILA → couple (short, full) compatible avec Judilibre."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise DilaError(f"XML illisible : {path.name} ({exc})") from exc

    commun = root.find("./META/META_COMMUN")
    juri = root.find("./META/META_SPEC/META_JURI")
    judi = root.find("./META/META_SPEC/META_JURI_JUDI")
    if juri is None or judi is None:
        return None

    identifier = (commun.findtext("ID") or path.stem).strip()
    numbers = [n for n in (format_number(e.text) for e in judi.findall(".//NUMERO_AFFAIRE")) if n]
    if not numbers:
        return None

    text = _text_of(root.find("./TEXTE/BLOC_TEXTUEL/CONTENU"))
    if len(text) < 500:
        return None

    decision_date = (juri.findtext("DATE_DEC") or "").strip()
    formation = (judi.findtext("FORMATION") or "").strip()
    solution = (juri.findtext("SOLUTION") or "").strip()
    ecli = (judi.findtext("ECLI") or "").strip() or None
    nature = (commun.findtext("NATURE") or "ARRET").strip().lower()

    publie = judi.find("PUBLI_BULL") is not None
    publication = ["b"] if publie else []

    sommaire = sommaire_of(root)
    summary = " ; ".join(sommaire_lines(sommaire)) or None
    # Le sommaire de la Cour tient lieu de nomenclature officielle : on retient
    # ses entrées principales (« DOUANES », « PEINES », « ACTION CIVILE »…).
    matters = [
        collapse((entry.get("label") or "").splitlines()[0] if entry.get("label") else "")
        for entry in sommaire
        if entry.get("type") == "PRINCIPAL"
    ]
    matters = [m for m in matters if m]

    zones = split_zones_by_markers(text)
    url = LEGIFRANCE_URL.format(id=identifier)

    short = {
        "id": identifier,
        "jurisdiction": "cc",
        "chamber": "crim",
        "number": numbers[0],
        "numbers": numbers,
        "ecli": ecli,
        "formation": "chambre criminelle" if "CRIMINELLE" in formation.upper() else formation,
        "publication": publication,
        "decision_date": decision_date,
        "type": nature,
        "solution": solution,
        "summary": summary,
        "themes": matters,
        "particularInterest": False,
        "url": url,
        "source": "dila",
        "release": release.name if release else None,
    }
    full = {
        "id": identifier,
        "text": text,
        "zones": zones,
        "visa": _visa_of(text),
        "partial": False,
        "titlesAndSummaries": [{"title": line} for line in sommaire_lines(sommaire)],
        "sommaire": sommaire,
        "publication": publication,
        "contested": {
            "court": (judi.findtext("FORM_DEC_ATT") or "").strip() or None,
            "date": (judi.findtext("DATE_DEC_ATT") or "").strip() or None,
        } or None,
        "update_date": release.date if release else None,
        "source": "dila",
        "url": url,
    }
    return short, full


def parse_release(root: str | Path, release: Release | None = None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Toutes les arrêts criminels d'un fichier d'appoint."""
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for path in iter_decision_files(root):
        try:
            parsed = parse_decision(path, release)
        except DilaError:
            continue
        if parsed:
            found.append(parsed)
    return found


def period_of(decisions: list[dict[str, Any]]) -> tuple[str, str]:
    """Période (borne basse, borne haute) couverte par une liste d'arrêts."""
    dates = sorted({str(d.get("decision_date")) for d in decisions if d.get("decision_date")})
    if not dates:
        today = date.today().isoformat()
        return today, today
    return dates[0], dates[-1]