"""Lightweight next-day planning from fresh catalogs and reviewed local rules."""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from .agenda import recurring_events, requires_market_exception_check
from .branding import with_footer
from .digest import MONTHS_GENITIVE, build_complete_event_section
from .dated_publication import DatedPublicationState
from .fishing_enrichment import (
    DEFAULT_FEPYC_AUTHORITY_STATE_PATH,
    DEFAULT_FPCV_DETAILS_STATE_PATH,
)
from .holidays import official_holidays_on
from .mayor import MayorChannelError, market_is_cancelled
from .models import Event
from .planning_events import load_local_planning_events
from .sports_presentation import (
    SPORTS_SECTION_HEADING,
    split_sport_events,
    sport_is_plannable,
)

LOGGER = logging.getLogger(__name__)
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


def _scheduled_market(target: datetime) -> Optional[Event]:
    """Return the one reviewed La Redonda market for this target day."""

    if not requires_market_exception_check(target):
        return None
    events = recurring_events(target)
    if len(events) != 1:
        LOGGER.warning(
            "Tomorrow market schedule is ambiguous for %s; omitting it",
            target.date(),
        )
        return None
    return events[0]


def _is_scheduled_market(event: Event, scheduled: Event) -> bool:
    """Match the weekly market even if a catalog enriched its title/place."""

    title = event.title.casefold()
    return (
        event.starts_at == scheduled.starts_at
        and ("рынок" in title or "mercad" in title)
        and (
            event.place is None
            or "redonda" in event.place.casefold()
            or event.place == scheduled.place
        )
    )


def _moved_market_schedule_note(target_day: date) -> Optional[str]:
    """Explain the ordinance-driven Tuesday move without another source."""

    if target_day.weekday() != 1:
        return None
    holidays = official_holidays_on(target_day + timedelta(days=1))
    if not holidays:
        return None
    holiday = holidays[0]
    return (
        "Перенесён со среды: "
        f"{holiday.date.day} {MONTHS_GENITIVE[holiday.date.month]} — "
        f"{holiday.name}"
    )


def _sort_events(events: Sequence[Event]) -> tuple[Event, ...]:
    return tuple(sorted(
        events,
        key=lambda event: (
            event.starts_at is None,
            event.starts_at
            or datetime.max.replace(tzinfo=GUARDAMAR_TIMEZONE),
            event.title.casefold(),
        ),
    ))


async def _merge_verified_market(
    events: Sequence[Event],
    *,
    now: datetime,
    target: datetime,
    gemini_api_key: str,
) -> tuple[Event, ...]:
    """Add only the verified La Redonda market to the local planning stream."""

    scheduled = _scheduled_market(target)
    if scheduled is None:
        return tuple(events)

    try:
        cancelled = await market_is_cancelled(
            now,
            gemini_api_key,
            market_day=target.date(),
        )
    except MayorChannelError as exc:
        LOGGER.warning(
            "Tomorrow events omit municipal market; Mayor check unavailable: %s",
            exc,
        )
        cancelled = True

    if cancelled:
        return tuple(
            event
            for event in events
            if not _is_scheduled_market(event, scheduled)
        )

    note = _moved_market_schedule_note(target.date())
    result = []
    matched = False
    for event in events:
        if not _is_scheduled_market(event, scheduled):
            result.append(event)
            continue
        matched = True
        result.append(
            replace(event, schedule_note=note)
            if note is not None else event
        )
    if not matched:
        result.append(
            replace(scheduled, schedule_note=note)
            if note is not None else scheduled
        )
    return _sort_events(result)


def _render_message(
    events: Sequence[Event],
    unit_count: int,
    target_day: date,
) -> str:
    render_events = tuple(events)
    if unit_count > 1:
        # A multi-event planning post is scan-first; optional prose is not
        # allowed to crowd out another verified planning item.
        render_events = tuple(
            replace(event, teaser=None)
            for event in render_events
        )

    ordinary, sports = split_sport_events(render_events)
    heading = (
        "📅 <b>Завтра в Гуардамаре — "
        f"{target_day.day} {MONTHS_GENITIVE[target_day.month]}</b>"
    )

    lines: list[str] = []
    if ordinary:
        section = build_complete_event_section(
            ordinary,
            heading,
        )
        lines.extend(section[1:])
    else:
        lines.append(heading)

    if sports:
        lines.extend(build_complete_event_section(
            sports,
            SPORTS_SECTION_HEADING,
            prefix_length=len("\n".join(lines)),
        ))

    if not ordinary and not sports:
        raise ValueError("tomorrow event section is empty")
    message = with_footer("\n".join(lines))
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
    gemini_api_key: str = "",
) -> Optional[TomorrowEventPublication]:
    """Build tomorrow's proactive announcement from reviewed local facts."""

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
    merged = await _merge_verified_market(
        merged,
        now=now,
        target=target,
        gemini_api_key=gemini_api_key,
    )
    eligible = tuple(
        event
        for event in merged
        if (
            sport_is_plannable(event)
            and _eligible_tomorrow_event(event, target_day)
        )
    )
    if not eligible:
        return None

    ordinary, sports = split_sport_events(eligible)
    units = (
        *_editorial_units(ordinary),
        *_editorial_units(sports),
    )
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
