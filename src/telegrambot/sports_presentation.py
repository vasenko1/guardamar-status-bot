"""Deterministic presentation helpers for source-owned sport codes."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Event


@dataclass(frozen=True)
class SportPresentation:
    icon: str
    label_ru: str


_PRESENTATIONS = {
    "chess": SportPresentation(icon="♟", label_ru="Шахматы"),
    "fishing": SportPresentation(icon="🎣", label_ru="Спортивная рыбалка"),
}


def sport_presentation(code: str) -> SportPresentation:
    """Return presentation metadata for one accepted canonical sport code."""

    try:
        return _PRESENTATIONS[code]
    except KeyError as exc:
        raise ValueError(f"unsupported sport code: {code!r}") from exc


def sport_display_title(event: Event) -> str:
    """Decorate an Event title for resident-facing sport presentation only."""

    if event.sport is None:
        return event.title
    presentation = sport_presentation(event.sport)
    return f"{presentation.icon} {presentation.label_ru} — {event.title}"
