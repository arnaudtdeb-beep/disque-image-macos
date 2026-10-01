"""Rendu texte d'une fiche d'arrêt pour le terminal."""

from __future__ import annotations

from typing import Any

from .report import decision_markdown


def render_card_text(card: dict[str, Any]) -> str:
    """Retourne la fiche au format Markdown (lisible tel quel au terminal)."""
    return decision_markdown(card)
