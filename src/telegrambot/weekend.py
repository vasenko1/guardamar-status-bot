"""Build the Friday-evening weekend events digest from local catalogs."""

import logging
from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from .branding import with_footer
from .digest import MONTHS_GENITIVE, build_complete_event_section
from .diagnostics import SourceDiagnostic
from .fishing_enrichment import (
    DEFAULT_FEPYC_AUTHORITY_STATE_PATH,
    DEFAULT_FPCV_DETAILS_STATE_PATH,
)
from .planning_events import load_local_planning_events
from .sports_presentation import (
    SPORTS_SECTION_HEADING,
    split_sport_events,
    sport_is_plannable,
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
    *,
    required_snapshot_day,
    municipal_agenda_state_path: Path,
    agenda_state_path: Path,
    library_agenda_state_path: Path,
    am_guardamar_state_path: Path,
    facv_state_path: Path,
    pesca_cv_state_path: Path,
    fepyc_authority_state_path: Path,
    pesca_cv_details_state_path: Path,
    convega_state_path: Path,
    translation_cache_path: Path,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
):
    """Collect one weekend day from fresh local catalogs and recurring rules."""

    return await load_local_planning_events(
        day,
        required_snapshot_day=required_snapshot_day,
        include_recurring=True,
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
        surface="Weekend",
    )


async def produce_weekend_message(
    now: datetime,
    gemini_api_key: str,
    municipal_agenda_state_path: Path,
    *,
    agenda_state_path: Path,
    library_agenda_state_path: Path = Path("state/library_agenda.json"),
    am_guardamar_state_path: Path = Path("state/am_guardamar.json"),
    facv_state_path: Path = Path("state/facv_events.json"),
    pesca_cv_state_path: Path = Path("state/pesca_cv_events.json"),
    fepyc_authority_state_path: Path = Path(
        DEFAULT_FEPYC_AUTHORITY_STATE_PATH
    ),
    pesca_cv_details_state_path: Path = Path(
        DEFAULT_FPCV_DETAILS_STATE_PATH
    ),
    convega_state_path: Path = Path("state/convega_events.json"),
    translation_cache_path: Path = Path("state/event_translations.json"),
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Optional[str]:
    """Return the weekend digest, or None when no verified event exists."""

    required_snapshot_day = now.astimezone(
        GUARDAMAR_TIMEZONE
    ).date()
    day_events = []
    for day in weekend_dates(now):
        day_moment = datetime.combine(
            day, time(12, 0), GUARDAMAR_TIMEZONE
        )
        events = await _day_events(
            day_moment,
            required_snapshot_day=required_snapshot_day,
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
        )
        events = tuple(
            event for event in events
            if sport_is_plannable(event)
        )
        if events:
            day_events.append((day, events))

    if not day_events:
        return None

    def render(*, compact_teasers: bool) -> List[str]:
        lines: List[str] = [HEADER]
        for day, events in day_events:
            render_events = (
                tuple(
                    replace(event, teaser=None)
                    if event.teaser is not None
                    else event
                    for event in events
                )
                if compact_teasers
                else events
            )
            ordinary, sports = split_sport_events(render_events)
            heading = (
                f"📅 <b>{DAY_LABELS[day.weekday()]}, "
                f"{day.day} {MONTHS_GENITIVE[day.month]}:</b>"
            )

            if ordinary:
                lines.extend(build_complete_event_section(
                    ordinary,
                    heading,
                    prefix_length=len("\n".join(lines)),
                ))
            else:
                lines.extend(("", heading))

            if sports:
                lines.extend(build_complete_event_section(
                    sports,
                    SPORTS_SECTION_HEADING,
                    prefix_length=len("\n".join(lines)),
                ))
        return lines

    try:
        lines = render(compact_teasers=False)
    except ValueError:
        lines = render(compact_teasers=True)
    return with_footer("\n".join(lines))
