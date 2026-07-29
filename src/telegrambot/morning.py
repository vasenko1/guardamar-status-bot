"""Collect the Morning Digest while isolating optional source failures."""

import asyncio
import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from .agenda import (
    AgendaError,
    fetch_today_events,
    recurring_events,
    requires_market_exception_check,
)
from .aemet import (
    DAILY_FORECAST_ATTEMPTS,
    DAILY_FORECAST_RETRY_SECONDS,
    fetch_morning_digest,
)
from .digest import build_message
from .diagnostics import SourceDiagnostic, source_error
from .mayor import MayorChannelError, market_is_cancelled
from .municipal_agenda import (
    MunicipalAgendaError,
    fetch_today_municipal_events,
)
from .police import PoliceTrafficError, fetch_traffic_notices
from .safebeach import SafeBeachError, fetch_beach_status
from .models import BeachNotice, BeachStatus

LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
SAFEBEACH_SEASON_START = (6, 20)
SAFEBEACH_SEASON_END = (9, 14)


def _safebeach_is_in_season(now: datetime) -> bool:
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    month_day = (local.month, local.day)
    return SAFEBEACH_SEASON_START <= month_day <= SAFEBEACH_SEASON_END


def _merge_events(*groups):
    result = []
    seen = set()
    for group in groups:
        for event in group:
            key = (event.title.strip().casefold(), event.starts_at)
            if key in seen:
                continue
            seen.add(key)
            result.append(event)
            if len(result) == 2:
                return tuple(result)
    return tuple(result)


async def produce_message(
    api_key: str,
    now: datetime,
    gemini_api_key: str = "",
    municipal_agenda_state_path: Path = Path(
        "state/municipal_agenda.json"
    ),
    *,
    collect_beach: bool = True,
    beach_status: Optional[BeachStatus] = None,
    beach_notice: Optional[BeachNotice] = None,
    aemet_daily_attempts: int = DAILY_FORECAST_ATTEMPTS,
    aemet_retry_seconds: float = DAILY_FORECAST_RETRY_SECONDS,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> str:
    """Build a digest; SafeBeach failure must not block AEMET delivery."""

    beach_task = (
        asyncio.create_task(fetch_beach_status())
        if collect_beach and _safebeach_is_in_season(now)
        else None
    )
    agenda_task = asyncio.create_task(fetch_today_events(now))
    weekly_events = recurring_events(now)
    market_status_task = (
        asyncio.create_task(
            market_is_cancelled(now, gemini_api_key)
        )
        if weekly_events and requires_market_exception_check(now)
        else None
    )
    municipal_agenda_task = asyncio.create_task(
        fetch_today_municipal_events(
            now,
            gemini_api_key,
            municipal_agenda_state_path,
            diagnostics,
        )
    )
    traffic_task = asyncio.create_task(
        fetch_traffic_notices(now, gemini_api_key or None)
    )
    beach_failed = False
    try:
        digest = await fetch_morning_digest(
            api_key=api_key,
            now=now,
            daily_attempts=aemet_daily_attempts,
            daily_retry_seconds=aemet_retry_seconds,
            diagnostics=diagnostics,
        )
    except BaseException:
        if beach_task is not None:
            beach_task.cancel()
        agenda_task.cancel()
        municipal_agenda_task.cancel()
        traffic_task.cancel()
        if market_status_task is not None:
            market_status_task.cancel()
        raise

    try:
        beach = (
            await beach_task
            if beach_task is not None
            else beach_status
        )
    except SafeBeachError as exc:
        beach_failed = True
        LOGGER.warning(
            "SafeBeach unavailable; omitting beach status: %s",
            exc,
        )
        if diagnostics is not None:
            diagnostics.append(
                source_error("SB", "SafeBeach", exc)
            )
        beach = None
    if (
        diagnostics is not None
        and beach_task is not None
        and beach is None
        and not beach_failed
    ):
        diagnostics.append(
            SourceDiagnostic(
                "SB-NO-ACTIVE",
                "SafeBeach",
                "ответ получен, но активных данных выбранных пляжей нет",
            )
        )

    if (
        beach is not None
        and beach.wind_direction is not None
        and beach.wind_speed_kmh is not None
    ):
        digest = replace(
            digest,
            weather=replace(
                digest.weather,
                wind_direction=beach.wind_direction,
                wind_speed_kmh=beach.wind_speed_kmh,
            ),
        )

    try:
        events = await agenda_task
    except AgendaError as exc:
        LOGGER.warning(
            "Agenda Guardamar unavailable; omitting events: %s",
            exc,
        )
        if diagnostics is not None:
            diagnostics.append(
                source_error("AGENDA", "Agenda Guardamar", exc)
            )
        events = ()

    try:
        municipal_events = await municipal_agenda_task
    except MunicipalAgendaError as exc:
        LOGGER.warning(
            "Municipal agenda unavailable; omitting poster events: %s",
            exc,
        )
        if diagnostics is not None:
            diagnostics.append(
                source_error(
                    "MUNI-AGENDA",
                    "Agenda municipal",
                    exc,
                )
            )
        municipal_events = ()

    try:
        traffic_notices = await traffic_task
    except PoliceTrafficError as exc:
        LOGGER.warning(
            "Policía Local unavailable; omitting traffic notices: %s",
            exc,
        )
        if diagnostics is not None:
            diagnostics.append(
                source_error("POLICE", "Policía Local", exc)
            )
        traffic_notices = ()

    if market_status_task is not None:
        try:
            if await market_status_task:
                weekly_events = ()
                LOGGER.info(
                    "Scheduled market omitted after explicit cancellation"
                )
        except MayorChannelError as exc:
            weekly_events = ()
            LOGGER.warning(
                "Mayor channel unavailable; omitting regular market: %s",
                exc,
            )
            if diagnostics is not None:
                diagnostics.append(
                    source_error(
                        "MAYOR",
                        "@AlcaldeGuardamar",
                        exc,
                        stage="MARKET",
                    )
                )

    return build_message(
        replace(
            digest,
            beach=beach,
            beach_notice=beach_notice,
            traffic_notices=traffic_notices,
            events=_merge_events(
                weekly_events,
                events,
                municipal_events,
            ),
        )
    )
