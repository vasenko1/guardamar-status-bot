"""Deterministic presentation helpers for source-owned sport codes."""

from __future__ import annotations

from dataclasses import dataclass, replace

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


SPORTS_SECTION_HEADING = "🏅 <b>Спортивные мероприятия</b>"


def split_sport_events(
    events: tuple[Event, ...],
) -> tuple[tuple[Event, ...], tuple[Event, ...]]:
    """Split one merged stream into ordinary and resident-facing sport rows.

    Mixed source programmes keep their parent only on the ordinary side.
    Sporting members are flattened there so one programme parent is never
    rendered twice. Wholly sporting programmes keep normal grouping.
    """

    programme_kinds: dict[str, set[bool]] = {}
    for event in events:
        if event.programme_title is None:
            continue
        programme_kinds.setdefault(
            event.programme_title,
            set(),
        ).add(event.sport is not None)

    mixed_programmes = {
        programme
        for programme, kinds in programme_kinds.items()
        if kinds == {False, True}
    }

    ordinary: list[Event] = []
    sports: list[Event] = []
    for event in events:
        if event.sport is None:
            ordinary.append(event)
            continue

        presented = replace(
            event,
            title=sport_display_title(event),
        )
        if event.programme_title in mixed_programmes:
            presented = replace(
                presented,
                programme_title=None,
                programme_display_title=None,
                programme_order=None,
            )
        sports.append(presented)

    return tuple(ordinary), tuple(sports)


def sport_is_plannable(event: Event) -> bool:
    """Return whether an event belongs in proactive planning surfaces."""

    return event.occurrence_status is None
