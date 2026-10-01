"""Production des rapports : Markdown (lisible, partageable), JSON et HTML."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# Provenance affichée dans les rapports. La source est déduite des données
# réellement présentes : un rapport ne doit pas annoncer PISTE s'il a été produit
# à partir des données ouvertes DILA.
SOURCE_LABELS = {
    "dila": "données ouvertes de la Cour de cassation (DILA)",
    "piste": "API Judilibre (Cour de cassation, open data) via PISTE",
    "judilibre": "API Judilibre (Cour de cassation, open data) via PISTE",
}


def source_label(cards: Iterable[dict[str, Any]]) -> str:
    sources = {
        str((card.get("meta") or {}).get("source") or "").strip().lower()
        for card in cards
    }
    sources.discard("")
    if len(sources) == 1:
        return SOURCE_LABELS.get(sources.pop(), "Cour de cassation")
    if sources:
        return "Cour de cassation (données ouvertes DILA et/ou API Judilibre)"
    return "Cour de cassation"


HEADER = """# Arrêts de la chambre criminelle — période du {start} au {end}

Généré le {generated} · source : {source}

- **Arrêts recensés :** {total}
- **Publiés au bulletin (B) :** {bulletin}
- **Publiés au rapport (R) :** {rapport}

Les synthèses ci-dessous sont des **extraits vérifiés du texte de la Cour**
(zone d'origine indiquée). Elles ne remplacent pas la lecture de l'arrêt.

"""

DISCLAIMER = (
    "> Outil de veille documentaire. Chaque analyse renvoie à l'arrêt original "
    "(ECLI, numéro de pourvoi) : la citation exacte reste la référence."
)


def _cards(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise l'entrée : accepte les fiches complètes ou les lignes de base."""
    out: list[dict[str, Any]] = []
    for card in cards:
        if "meta" in card and "analysis" in card:
            out.append(card)
        else:
            from .weekly import _card_as_dict_from_row

            out.append(_card_as_dict_from_row(card))
    return out


def _bullet(value: Any) -> str:
    return "•" if value else ""


def _bullets(lines: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for line in lines or []:
        if isinstance(line, dict):
            line = line.get("quote")
        text = str(line or "").strip()
        if text:
            result.append(text)
    return result


def decision_markdown(card: dict[str, Any]) -> str:
    meta = card.get("meta") or {}
    analysis = card.get("analysis") or {}

    badges: list[str] = []
    if meta.get("au_bulletin"):
        badge = meta.get("bulletin_numero")
        badges.append(f"📌 **Publié au bulletin (B)**{f' — {badge}' if badge else ''}")
    if meta.get("au_rapport"):
        badges.append("📖 Publié au rapport (R)")
    for label in meta.get("publication_labels") or []:
        if "communiqué" in label.lower():
            badges.append(f"📢 {label}")
    if meta.get("particulier_interet"):
        badges.append("⭐ Intérêt particulier")
    if meta.get("extrait_partiel"):
        badges.append("⚠️ Publié par extraits")

    themes = analysis.get("themes") or []
    theme_labels = " · ".join(f"{t.get('icon', '')} {t.get('label')}".strip() for t in themes)
    official = meta.get("themes_officiels") or []

    lines: list[str] = []
    lines.append(
        f"## {meta.get('decision_date') or '—'} — pourvoi n° {meta.get('number') or '—'}"
    )
    lines.append("")
    if badges:
        lines.append(" · ".join(badges))
        lines.append("")
    lines.append(
        f"- **ECLI :** `{meta.get('ecli') or '—'}`"
    )
    lines.append(f"- **Solution :** {meta.get('solution_label') or meta.get('solution') or '—'}")
    lines.append(f"- **Formation :** {meta.get('formation') or 'chambre criminelle'}")
    if theme_labels:
        lines.append(f"- **Thèmes de veille :** {theme_labels}")
    if official:
        lines.append(f"- **Matières (nomenclature de la Cour) :** {', '.join(official[:8])}")
    # En source DILA, `url` pointe déjà vers Légifrance : un second lien
    # « Légifrance » serait redondant.
    from_dila = str(meta.get("source") or "").strip().lower() == "dila"
    links = []
    if meta.get("url"):
        label = "Légifrance" if from_dila else "Cour de cassation"
        links.append(f"[{label}]({meta['url']})")
    if meta.get("url_legifrance") and not from_dila:
        links.append(f"[Légifrance]({meta['url_legifrance']})")
    if links:
        lines.append(f"- **Source :** {' · '.join(links)}")
    lines.append("")

    lines.append("### L'attendu de la Cour")
    lines.append("")
    attendu = _bullets(analysis.get("attendu"))
    if attendu:
        lines.extend(f"{t}" for t in attendu)
    else:
        lines.append("_Non déterminé par l'extraction automatique : consulter l'arrêt._")
    lines.append("")

    lignes = _bullets(analysis.get("solution_texte"))
    if lignes:
        lines.append("### La solution")
        lines.append("")
        lines.extend(lignes)
        lines.append("")

    motifs = _bullets(analysis.get("motifs"))
    if motifs:
        lines.append("### Les motifs")
        lines.append("")
        lines.extend(motifs)
        lines.append("")

    moyens = _bullets(analysis.get("moyens"))
    if moyens:
        lines.append("### Les moyens du pourvoi")
        lines.append("")
        lines.extend(f"- {m}" for m in moyens)
        lines.append("")

    textes = _bullets(analysis.get("textes_appliques"))
    if textes:
        lines.append("### Textes appliqués")
        lines.append("")
        lines.extend(f"- {t}" for t in textes[:12])
        lines.append("")

    portee = _bullets(analysis.get("portee"))
    if portee:
        lines.append("### Portée")
        lines.append("")
        lines.extend(portee)
        lines.append("")

    fiabilite = analysis.get("fiabilite")
    if fiabilite:
        lines.append(f"_{fiabilite}._")
        lines.append("")

    return "\n".join(lines)


def theme_overview(cards: list[dict[str, Any]]) -> str:
    counts: dict[str, dict[str, Any]] = {}
    for card in cards:
        for theme in (card.get("analysis") or {}).get("themes") or []:
            label = theme.get("label") or theme.get("code") or "?"
            entry = counts.setdefault(
                label, {"icon": theme.get("icon", ""), "total": 0, "ids": []}
            )
            entry["total"] += 1
            entry["ids"].append((card.get("meta") or {}).get("number"))
    if not counts:
        return ""
    lines = ["## Répartition thématique", ""]
    for label, entry in sorted(counts.items(), key=lambda kv: -kv[1]["total"]):
        numbers = ", ".join(str(n) for n in entry["ids"] if n)
        lines.append(f"- {entry['icon']} **{label}** — {entry['total']} arrêt(s) · pourvois : {numbers}")
    lines.append("")
    return "\n".join(lines)


def build_markdown(cards: list[dict[str, Any]], date_start: str, date_end: str) -> str:
    bulletin = [c for c in cards if (c.get("meta") or {}).get("au_bulletin")]
    rapport = [c for c in cards if (c.get("meta") or {}).get("au_rapport")]
    header = HEADER.format(
        start=date_start,
        end=date_end,
        generated=datetime.now().strftime("%d/%m/%Y à %H:%M"),
        source=source_label(cards),
        total=len(cards),
        bulletin=len(bulletin),
        rapport=len(rapport),
    )
    body = [header, DISCLAIMER, "", theme_overview(cards), ""]
    if bulletin:
        body.append("## Arrêts publiés au bulletin — à lire en priorité")
        body.append("")
        for card in bulletin:
            body.append(decision_markdown(card))
    body.append("## Ensemble des arrêts de la période")
    body.append("")
    for card in cards:
        body.append(decision_markdown(card))
    return "\n".join(body)


def build_html(markdown_text: str) -> str:
    """Rendu HTML minimaliste et autonome (aucune dépendance externe)."""
    body = _markdown_to_html(markdown_text)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Veille chambre criminelle — {html.escape(datetime.now().strftime('%d/%m/%Y'))}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
  h1 {{ font-size: 1.6rem; }} h2 {{ font-size: 1.25rem; margin-top: 2.2rem; }}
  h3 {{ font-size: 1rem; margin-top: 1.4rem; text-transform: uppercase; letter-spacing: .04em;
        opacity: .7; }}
  code {{ background: rgba(127,127,127,.15); padding: .1em .35em; border-radius: 4px; }}
  blockquote {{ border-left: 3px solid #888; padding-left: 1rem; opacity: .75; }}
  li {{ margin: .2rem 0; }}
  a {{ color: inherit; }}
  hr {{ border: 0; border-top: 1px solid rgba(127,127,127,.3); }}
</style>
</head>
<body>{body}</body>
</html>
"""


def _markdown_to_html(text: str) -> str:
    out: list[str] = []
    in_list = False
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if line.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("> "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def build_json(cards: list[dict[str, Any]], date_start: str, date_end: str) -> str:
    payload = {
        "periode": {"debut": date_start, "fin": date_end},
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "source": source_label(cards) + " — licence ouverte 2.0",
        "nombre_arrets": len(cards),
        "nombre_bulletin": sum(1 for c in cards if (c.get("meta") or {}).get("au_bulletin")),
        "arrets": [
            {
                "meta": c.get("meta"),
                "analyse": {
                    k: v
                    for k, v in (c.get("analysis") or {}).items()
                    if k not in ("meta",)
                },
            }
            for c in cards
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_reports(
    config: Any,
    cards: Iterable[dict[str, Any]],
    date_start: str,
    date_end: str,
) -> dict[str, str]:
    """Écrit les trois rapports dans <data_dir>/rapports/."""
    normalised = _cards(cards)
    out_dir = Path(config.data_dir) / "rapports"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = f"{date_start}_{date_end}"

    markdown = build_markdown(normalised, date_start, date_end)
    paths = {
        "markdown": str(out_dir / f"veille_{slug}.md"),
        "html": str(out_dir / f"veille_{slug}.html"),
        "json": str(out_dir / f"veille_{slug}.json"),
    }
    Path(paths["markdown"]).write_text(markdown, encoding="utf-8")
    Path(paths["html"]).write_text(build_html(markdown), encoding="utf-8")
    Path(paths["json"]).write_text(build_json(normalised, date_start, date_end), encoding="utf-8")

    latest = out_dir / "dernier_veille.md"
    latest.write_text(markdown, encoding="utf-8")
    paths["dernier"] = str(latest)
    return paths
