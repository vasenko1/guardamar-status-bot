"""Lightweight next-day event announcement from fresh local catalogs."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from .branding import with_footer
from .digest import MONTHS_GENITIVE, build_complete_event_section
from .dated_publication import DatedPublicationState
from .fishing_enrichment import (
    DEFAULT_FEPYC_AUTHORITY_STATE_PATH,
    DEFAULT_FPCV_DETAILS_STATE_PATH,
)
from .models import Event
from .planning_events import load_local_planning_events

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_DUE_WEEKDAYS = frozenset({0, 1, 2, 3, 6})  # Sunday through Thursday.
_IMAGE_HOSTS = frozenset({
    "amguardamar.es",
    "www.amguardamar.es",
    "guardamarturismo.com",
    "www.guardamarturismo.com",
})


class TomorrowEventStateError(RuntimeError):
    """Raised when next-day publication state cannot be trusted."""


class TomorrowEventState(DatedPublicationState):
    """Compatibility wrapper over the shared dated-publication state."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            path,
            label="tomorrow-event",
            error_type=TomorrowEventStateError,
        )


@dataclass(frozen=True)
class TomorrowEventPublication:
    target_date: date
    message: str
    events: tuple[Event, ...]
    unit_count: int
    image_url: Optional[str] = None


def tomorrow_notice_due(now: datetime) -> bool:
    """Avoid Friday/Saturday duplication of the Friday weekend digest."""

    local = now.astimezone(GUARDAMAR_TIMEZONE)
    return local.weekday() in _DUE_WEEKDAYS


def _eligible_tomorrow_event(event: Event, target_day: date) -> bool:
    """Keep discrete occurrences plus only the first/final day of ranges."""

    if event.active_from is None and event.active_until is None:
        return True
    if event.active_from == target_day:
        return True
    return bool(event.is_final_day)


def _editorial_units(events: Sequence[Event]) -> tuple[tuple[Event, ...], ...]:
    """Collapse one named programme into one resident-facing unit."""

    units: list[tuple[Event, ...]] = []
    seen_programmes: set[str] = set()
    for event in events:
        programme = event.programme_title
        if programme:
            if programme in seen_programmes:
                continue
            seen_programmes.add(programme)
            members = tuple(
                sorted(
                    (
                        candidate
                        for candidate in events
                        if candidate.programme_title == programme
                    ),
                    key=lambda candidate: (
                        candidate.programme_order is None,
                        candidate.programme_order or 0,
                        candidate.starts_at is None,
                        candidate.starts_at
                        or datetime.max.replace(tzinfo=GUARDAMAR_TIMEZONE),
                    ),
                )
            )
            units.append(members)
        else:
            units.append((event,))
    return tuple(units)


def _approved_image_url(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    path = parsed.path.casefold()
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _IMAGE_HOSTS
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not path.startswith("/wp-content/uploads/")
        or not path.endswith((".jpg", ".jpeg", ".png", ".webp"))
    ):
        return None
    return urllib.parse.urlunsplit(parsed._replace(query="", fragment=""))


def _unit_image_url(unit: Sequence[Event]) -> Optional[str]:
    values = {
        normalized
        for event in unit
        if (normalized := _approved_image_url(event.image_url)) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def _render_message(
    events: Sequence[Event],
    unit_count: int,
    target_day: date,
) -> str:
    render_events = tuple(events)
    if unit_count > 1:
        # A multi-event planning post is scan-first; full prose stays for a
        # standalone event and in the next morning digest.
        render_events = tuple(
            replace(event, teaser=None)
            for event in render_events
        )
    section = build_complete_event_section(
        render_events,
        (
            "📅 <b>Завтра в Гуардамаре — "
            f"{target_day.day} {MONTHS_GENITIVE[target_day.month]}</b>"
        ),
    )
    if not section:
        raise ValueError("tomorrow event section is empty")
    message = with_footer("\n".join(section[1:]))
    if len(message) > 4096:
        raise ValueError("tomorrow event message exceeds Telegram limit")
    return message


async def produce_tomorrow_event_publication(
    now: datetime,
    *,
    municipal_agenda_state_path: Path,
    agenda_state_path: Path,
    library_agenda_state_path: Path,
    am_guardamar_state_path: Path,
    facv_state_path: Path,
    pesca_cv_state_path: Path,
    fepyc_authority_state_path: Path = Path(
        DEFAULT_FEPYC_AUTHORITY_STATE_PATH
    ),
    pesca_cv_details_state_path: Path = Path(
        DEFAULT_FPCV_DETAILS_STATE_PATH
    ),
    convega_state_path: Path = Path("state/convega_events.json"),
    translation_cache_path: Path,
) -> Optional[TomorrowEventPublication]:
    """Build tomorrow's proactive announcement with no source network I/O."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    target_day = local_day + timedelta(days=1)
    target = datetime.combine(target_day, time(12, 0), GUARDAMAR_TIMEZONE)

    merged = await load_local_planning_events(
        target,
        required_snapshot_day=local_day,
        include_recurring=False,
        municipal_agenda_state_path=municipal_agenda_state_path,
        agenda_state_path=agenda_state_path,
        library_agenda_state_path=library_agenda_state_path,
        am_guardamar_state_path=am_guardamar_state_path,
        facv_state_path=facv_state_path,
        pesca_cv_state_path=pesca_cv_state_path,
        fepyc_authority_state_path=fepyc_authority_state_path,
        pesca_cv_details_state_path=pesca_cv_details_state_path,
        convega_state_path=convega_state_path,
        translation_cache_path=translation_cache_path,
        surface="Tomorrow events",
    )
    eligible = tuple(
        event
        for event in merged
        if _eligible_tomorrow_event(event, target_day)
    )
    if not eligible:
        return None

    units = _editorial_units(eligible)
    if not units:
        return None
    image_url = _unit_image_url(units[0]) if len(units) == 1 else None
    return TomorrowEventPublication(
        target_date=target_day,
        message=_render_message(eligible, len(units), target_day),
        events=eligible,
        unit_count=len(units),
        image_url=image_url,
    )
