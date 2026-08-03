"""Collect the Morning Digest while isolating optional source failures."""

import asyncio
import logging
import unicodedata
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
from .aemet import fetch_morning_digest
from .digest import build_message
from .diagnostics import SourceDiagnostic, source_error
from .holidays import official_holidays_on
from .mayor import (
    MayorChannelError,
    fetch_today_mayor_events,
    market_is_cancelled,
)
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

    def normalize_title(value):
        normalized = unicodedata.normalize("NFKD", value.strip().casefold())
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        if (
            "fiestas de barrio" in normalized
            or ("празд" in normalized and "район" in normalized)
        ):
            return "fiestas-de-barrio"
        return normalized

    def normalized_words(value):
        normalized = normalize_title(value)
        aliases = {"castell": "castillo"}
        return {
            aliases.get(word, word)
            for word in normalized.replace("/", " ").split()
            if len(word) > 2 and word != "guardamar"
        }

    def overlap(left, right):
        left_words = normalized_words(left)
        right_words = normalized_words(right)
        if not left_words or not right_words:
            return 0.0
        return len(left_words & right_words) / min(
            len(left_words), len(right_words)
        )

    for group in groups:
        for event in group:
            normalized_title = normalize_title(event.title)
            duplicate = any(
                current.starts_at == event.starts_at
                and (
                    normalized_title == normalize_title(current.title)
                    or overlap(current.title, event.title) >= 0.5
                    or (
                        current.place is not None
                        and event.place is not None
                        and overlap(current.place, event.place) >= 0.5
                    )
                )
                for current in result
            )
            if duplicate:
                continue
            result.append(event)
    result.sort(
        key=lambda event: (
            event.starts_at is None,
            event.starts_at or datetime.max.replace(
                tzinfo=GUARDAMAR_TIMEZONE
            ),
            event.title.casefold(),
        )
    )
    return tuple(result)


async def produce_message(
    api_key: str,
    now: datetime,
    gemini_api_key: str = "",
    municipal_agenda_state_path: Path = Path(
        "state/municipal_agenda.json"
    ),
    *,
    agenda_state_path: Path = Path("state/agenda_guardamar.json"),
    collect_beach: bool = True,
    beach_status: Optional[BeachStatus] = None,
    beach_notice: Optional[BeachNotice] = None,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> str:
    """Build a digest; SafeBeach failure must not block AEMET delivery."""

    beach_task = (
        asyncio.create_task(fetch_beach_status())
        if collect_beach and _safebeach_is_in_season(now)
        else None
    )
    agenda_task = asyncio.create_task(
        fetch_today_events(now, gemini_api_key, agenda_state_path)
    )
    mayor_events_task = asyncio.create_task(
        fetch_today_mayor_events(now)
    )
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
            diagnostics=diagnostics,
        )
    except BaseException:
        if beach_task is not None:
            beach_task.cancel()
        agenda_task.cancel()
        mayor_events_task.cancel()
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
            "SafeBeach %s; omitting beach status",
            exc.diagnostic_code,
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
        mayor_events = await mayor_events_task
    except MayorChannelError as exc:
        LOGGER.warning(
            "Mayor events unavailable; omitting events: %s",
            exc,
        )
        if diagnostics is not None:
            diagnostics.append(
                source_error(
                    "MAYOR",
                    "@AlcaldeGuardamar",
                    exc,
                    stage="EVENTS",
                )
            )
        mayor_events = ()

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
            holidays=official_holidays_on(
                now.astimezone(GUARDAMAR_TIMEZONE).date()
            ),
            events=_merge_events(
                weekly_events,
                mayor_events,
                municipal_events,
                events,
            ),
        ),
        now=now,
    )
