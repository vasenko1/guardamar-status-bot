"""Current-day sports publication from fresh accepted local snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from .branding import with_footer
from .diagnostics import SourceDiagnostic
from .digest import MONTHS_GENITIVE, build_complete_event_section
from .fishing_enrichment import (
    DEFAULT_FEPYC_AUTHORITY_STATE_PATH,
    DEFAULT_FPCV_DETAILS_STATE_PATH,
)
from .models import Event
from .planning_events import load_local_planning_events
from .sports_presentation import sport_display_title


GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")


@dataclass(frozen=True)
class SportsTodayPublication:
    target_date: date
    message: str
    events: tuple[Event, ...]


def _current_day_event(
    event: Event,
    now: datetime,
) -> Optional[Event]:
    """Return one resident-facing current-day sport row, or omit it safely."""

    if event.sport is None:
        return None

    if event.occurrence_status == "cancelled":
        return replace(
            event,
            title="❌ " + sport_display_title(event),
            starts_at=None,
            ends_at=None,
            active_from=None,
            active_until=None,
            is_final_day=False,
            ticket_price_cents=None,
            ticket_price_is_from=False,
            ticket_url=None,
            participation_note=None,
            registration_contact=None,
            registration_url=None,
            capacity_limited=False,
            teaser=None,
            schedule_note=None,
            access_note=None,
            details=tuple(dict.fromkeys((
                "Событие отменено",
                *event.details,
            ))),
        )

    if event.occurrence_status is not None:
        # No other occurrence state is source-contracted yet. Silence is safer
        # than inventing wording for an unknown future status.
        return None

    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    starts_at = (
        event.starts_at.astimezone(GUARDAMAR_TIMEZONE)
        if event.starts_at is not None
        else None
    )
    ends_at = (
        event.ends_at.astimezone(GUARDAMAR_TIMEZONE)
        if event.ends_at is not None
        else None
    )

    if ends_at is not None and ends_at <= local_now:
        return None

    time_fact = None
    if starts_at is not None:
        if starts_at > local_now:
            time_fact = f"Начало в {starts_at:%H:%M}"
        elif ends_at is not None:
            time_fact = (
                f"Началось в {starts_at:%H:%M} · "
                f"окончание в {ends_at:%H:%M}"
            )
        else:
            time_fact = f"Сегодня с {starts_at:%H:%M}"

    details = event.details
    if time_fact is not None:
        details = tuple(dict.fromkeys((time_fact, *details)))

    return replace(
        event,
        title=sport_display_title(event),
        starts_at=None,
        ends_at=None,
        details=details,
    )


def _render_message(
    events: tuple[Event, ...],
    target_day: date,
) -> str:
    render_events = events
    if len(render_events) > 1:
        render_events = tuple(
            replace(event, teaser=None)
            if event.teaser is not None
            else event
            for event in render_events
        )

    heading = (
        "🏅 <b>Спортивные мероприятия сегодня — "
        f"{target_day.day} {MONTHS_GENITIVE[target_day.month]}</b>"
    )
    section = build_complete_event_section(
        render_events,
        heading,
    )
    if not section:
        raise ValueError("sports today section is empty")

    message = with_footer("\n".join(section[1:]))
    if len(message) > 4096:
        raise ValueError("sports today message exceeds Telegram limit")
    return message


async def produce_sports_today_publication(
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
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Optional[SportsTodayPublication]:
    """Build today's sports publication with zero source HTTP and zero AI."""

    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    local_day = local_now.date()
    merged = await load_local_planning_events(
        local_now,
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
        diagnostics=diagnostics,
        surface="Sports Today",
    )

    presented = tuple(
        candidate
        for event in merged
        if event.sport is not None
        for candidate in (_current_day_event(event, local_now),)
        if candidate is not None
    )
    if not presented:
        return None

    return SportsTodayPublication(
        target_date=local_day,
        message=_render_message(presented, local_day),
        events=presented,
    )
