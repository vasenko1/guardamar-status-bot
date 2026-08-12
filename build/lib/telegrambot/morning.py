"""Collect the Morning Digest while isolating optional source failures."""

import asyncio
import logging
import re
import unicodedata
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional
from zoneinfo import ZoneInfo

from .agenda import (
    AgendaError,
    fetch_today_events,
    recurring_events,
    requires_market_exception_check,
)
from .aemet import AemetError, fetch_morning_digest
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
from .pharmacy import duty_pharmacies_on
from .police import PoliceTrafficError, fetch_traffic_notices
from .safebeach import SafeBeachError, fetch_beach_status
from .sun import sun_times
from .models import BeachNotice, BeachStatus, MorningDigest

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
            for word in re.findall(r"[^\W_]+", normalized)
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
            duplicate_index = next((
                index
                for index, current in enumerate(result)
                if (
                    current.starts_at is None
                    or event.starts_at is None
                    or current.starts_at == event.starts_at
                )
                and (
                    normalized_title == normalize_title(current.title)
                    or overlap(current.title, event.title) >= 0.5
                    or (
                        overlap(current.title, event.title) >= 0.2
                        and current.place is not None
                        and event.place is not None
                        and overlap(current.place, event.place) >= 0.5
                    )
                )
            ), None)
            if duplicate_index is not None:
                current = result[duplicate_index]
                result[duplicate_index] = replace(
                    current,
                    starts_at=current.starts_at or event.starts_at,
                    ends_at=current.ends_at or event.ends_at,
                    place=current.place or event.place,
                    ticket_price_cents=(
                        current.ticket_price_cents
                        if current.ticket_price_cents is not None
                        else event.ticket_price_cents
                    ),
                    ticket_url=current.ticket_url or event.ticket_url,
                    participation_note=(
                        current.participation_note
                        or event.participation_note
                    ),
                    registration_contact=(
                        current.registration_contact
                        or event.registration_contact
                    ),
                    capacity_limited=(
                        current.capacity_limited or event.capacity_limited
                    ),
                )
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
    translation_cache_path: Optional[Path] = None,
    aemet_digest: Optional[MorningDigest] = None,
    fetch_aemet: bool = True,
    aemet_fallback: Optional[MorningDigest] = None,
    aemet_observer: Optional[Callable[[MorningDigest], None]] = None,
    pharmacy_state_path: Optional[Path] = None,
) -> str:
    """Build a digest; SafeBeach failure must not block AEMET delivery."""

    beach_task = (
        asyncio.create_task(fetch_beach_status())
        if collect_beach and _safebeach_is_in_season(now)
        else None
    )
    agenda_task = asyncio.create_task(
        fetch_today_events(
            now,
            gemini_api_key,
            agenda_state_path,
            translation_cache_path,
        )
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
            translation_cache_path,
        )
    )
    traffic_task = asyncio.create_task(
        fetch_traffic_notices(now, gemini_api_key or None)
    )
    beach_failed = False
    digest = aemet_digest
    if digest is None and fetch_aemet:
        try:
            digest = await fetch_morning_digest(
                api_key=api_key,
                now=now,
                diagnostics=diagnostics,
            )
            if aemet_observer is not None:
                try:
                    aemet_observer(digest)
                except (OSError, ValueError) as exc:
                    LOGGER.warning(
                        "Current AEMET snapshot could not be saved: %s", exc
                    )
        except AemetError as exc:
            LOGGER.warning(
                "AEMET unavailable; publishing verified non-weather blocks: %s",
                exc.diagnostic_code,
            )
    if digest is None:
        digest = aemet_fallback or MorningDigest(
            weather=None,
            warnings=(),
            warnings_available=False,
        )

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
        digest.weather is not None
        and beach is not None
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
    if digest.weather is not None:
        sunrise, sunset = sun_times(now)
        digest = replace(
            digest,
            weather=replace(
                digest.weather, sunrise=sunrise, sunset=sunset
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

    pharmacies = ()
    if pharmacy_state_path is not None:
        try:
            pharmacies = await duty_pharmacies_on(now, pharmacy_state_path)
        except OSError as exc:
            LOGGER.warning(
                "Pharmacy catalog unavailable; omitting the row: %s", exc
            )

    return build_message(
        replace(
            digest,
            beach=beach,
            beach_notice=beach_notice,
            pharmacies=pharmacies,
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
