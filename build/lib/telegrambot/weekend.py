"""Build the Friday-evening weekend events digest from local catalogs."""

import logging
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from .agenda import AgendaError, fetch_today_events, recurring_events
from .branding import with_footer
from .digest import MONTHS_GENITIVE, build_event_section
from .morning import _merge_events
from .municipal_agenda import (
    MunicipalAgendaError,
    fetch_today_municipal_events,
)

LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
HEADER = "🎭 <b>Афиша выходных</b>"
DAY_LABELS = {5: "Суббота", 6: "Воскресенье"}


def weekend_dates(now: datetime):
    """Return the nearest Saturday and Sunday local dates, today included."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    saturday = local_day + timedelta(days=(5 - local_day.weekday()) % 7)
    return saturday, saturday + timedelta(days=1)


async def _day_events(
    day: datetime,
    gemini_api_key: str,
    municipal_agenda_state_path: Path,
    agenda_state_path: Path,
    translation_cache_path: Path,
):
    """Collect one weekend day from the two catalogs and recurring rules."""

    try:
        agenda_events = await fetch_today_events(
            day,
            gemini_api_key,
            agenda_state_path,
            translation_cache_path,
        )
    except AgendaError as exc:
        LOGGER.warning(
            "Agenda Guardamar unavailable for %s; omitting: %s",
            day.date(),
            exc,
        )
        agenda_events = ()
    try:
        municipal_events = await fetch_today_municipal_events(
            day,
            gemini_api_key,
            municipal_agenda_state_path,
            translation_cache_path=translation_cache_path,
        )
    except MunicipalAgendaError as exc:
        LOGGER.warning(
            "Municipal agenda unavailable for %s; omitting: %s",
            day.date(),
            exc,
        )
        municipal_events = ()
    return _merge_events(
        recurring_events(day),
        municipal_events,
        agenda_events,
    )


async def produce_weekend_message(
    now: datetime,
    gemini_api_key: str,
    municipal_agenda_state_path: Path,
    *,
    agenda_state_path: Path,
    translation_cache_path: Path,
) -> Optional[str]:
    """Return the weekend digest, or None when no verified event exists."""

    lines: List[str] = [HEADER]
    for day in weekend_dates(now):
        day_moment = datetime.combine(
            day, time(12, 0), GUARDAMAR_TIMEZONE
        )
        events = await _day_events(
            day_moment,
            gemini_api_key,
            municipal_agenda_state_path,
            agenda_state_path,
            translation_cache_path,
        )
        if not events:
            continue
        heading = (
            f"📅 <b>{DAY_LABELS[day.weekday()]}, "
            f"{day.day} {MONTHS_GENITIVE[day.month]}:</b>"
        )
        lines.extend(build_event_section(
            events,
            heading,
            prefix_length=len("\n".join(lines)),
        ))
    if len(lines) == 1:
        return None
    return with_footer("\n".join(lines))
