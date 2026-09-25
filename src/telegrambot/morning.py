"""Collect the Morning Digest while isolating optional source failures."""

import asyncio
import logging
import re
import unicodedata
import urllib.parse
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
from .celebrations import celebrations_on
from .diagnostics import SourceDiagnostic, source_error
from .event_urls import normalize_ticket_url
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
from .library_agenda import LibraryAgendaError, fetch_today_library_events
from .am_guardamar import AmGuardamarError, fetch_today_am_guardamar_events
from .blood_donation import (
    BloodDonationError, fetch_today_blood_donation_events,
)
from .facv import FacvSourceError, fetch_today_facv_events
from .pesca_cv import PescaCvSourceError, fetch_today_pesca_cv_events
from .pharmacy import duty_pharmacies_on
from .sun import sun_times
from .environment import (
    EnvironmentError, fetch_cams, fetch_meteosalud, fetch_meteosalud_cold,
)
from .emergency_risks import EmergencyRiskError, EmergencyRiskState
from .models import ColdHealthRisk, HeatHealthRisk, MorningDigest

LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_ROUTINE_EVENT_TITLES = frozenset({
    "actividades del centro social juvenil",
    "actividades del centro social juvenil csj",
    "actividades centro social juvenil",
    "мероприятия центра социальнои молодежи",
    "мероприятия центра социальнои молодежи csj",
})


def _normalized_event_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[^\W_]+", normalized))


def _is_routine_event(event) -> bool:
    """Keep durable venue opening hours out of event publications."""

    return _normalized_event_title(event.title) in _ROUTINE_EVENT_TITLES


def _prefer_agenda_guardamar_venues(
    municipal_events,
    agenda_events,
):
    """Use a unique direct Agenda booking occurrence to repair venue/URL."""

    def words(value):
        aliases = {
            "todos": "todo",
            "llamamos": "llamar",
        }
        return {
            aliases.get(word, word)
            for word in _normalized_event_title(value).split()
            if len(word) > 2 and word != "guardamar"
        }

    def overlap(left, right):
        left_words = words(left)
        right_words = words(right)
        if not left_words or not right_words:
            return 0.0
        return len(left_words & right_words) / min(
            len(left_words), len(right_words)
        )

    def agenda_path(value):
        if value is None:
            return None
        normalized = normalize_ticket_url(value)
        if normalized is None:
            return None
        parsed = urllib.parse.urlparse(normalized)
        if parsed.hostname not in {
            "agendaguardamar.com",
            "www.agendaguardamar.com",
        }:
            return None
        return parsed.path, normalized

    def agenda_event_key(ticket):
        """Use Agenda's path key, never the non-unique number by itself."""

        if ticket is None:
            return None
        match = re.match(
            r"^/(?:espectaculo|entradas)/(\d+)/([^/?#]+\.html)$",
            ticket[0],
            re.IGNORECASE,
        )
        return (
            match.group(1),
            match.group(2).casefold(),
        ) if match is not None else None

    def route_from_title(value):
        match = re.match(
            r"^Экскурсия(?:\s+«[^»]{1,80}»)?\s*:\s*(.{3,160})$",
            value.strip(),
            re.IGNORECASE,
        )
        return match.group(1).strip(" .") if match is not None else None

    result = []
    for current in municipal_events:
        if current.starts_at is None:
            result.append(current)
            continue

        current_ticket = agenda_path(current.ticket_url)
        current_event_key = agenda_event_key(current_ticket)
        generic_agenda_reservation = (
            current_ticket is not None
            and current_ticket[0] in {"", "/"}
        )
        direct_candidates = []
        current_words = words(current.title)

        for candidate in agenda_events:
            if (
                candidate.starts_at != current.starts_at
                or candidate.ticket_url is None
            ):
                continue
            candidate_ticket = agenda_path(candidate.ticket_url)
            if (
                candidate_ticket is None
                or not candidate_ticket[0].startswith("/entradas/")
            ):
                continue
            shared = current_words & words(candidate.title)
            same_event_identity = (
                current_event_key is not None
                and current_event_key == agenda_event_key(candidate_ticket)
            )
            same_place = (
                current.place is not None
                and candidate.place is not None
                and _normalized_event_title(candidate.place)
                != "guardamar del segura"
                and overlap(current.place, candidate.place) >= 0.75
            )
            if (
                not same_event_identity
                and not (
                    len(shared) >= 2
                    and overlap(current.title, candidate.title) >= 0.75
                )
                and not (
                    generic_agenda_reservation
                    and same_place
                    and current.ticket_price_cents == 0
                    and candidate.ticket_price_cents == 0
                )
            ):
                continue
            direct_candidates.append((
                candidate,
                candidate_ticket[1],
                same_event_identity,
            ))

        if len(direct_candidates) != 1:
            if generic_agenda_reservation:
                current = replace(current, ticket_url=None)
            result.append(current)
            continue

        candidate, direct_url, same_event_identity = direct_candidates[0]

        # Keep existing non-Agenda ticket providers and already-direct Agenda
        # booking links untouched.
        may_upgrade_ticket = (
            current.ticket_url is None
            or generic_agenda_reservation
            or (
                current_ticket is not None
                and current_ticket[0].startswith("/espectaculo/")
            )
        )

        replacement_place = current.place
        if (
            current.place is not None
            and candidate.place is not None
            and _normalized_event_title(candidate.place)
            != "guardamar del segura"
            and overlap(current.place, candidate.place) < 0.5
            and current.ticket_url is None
        ):
            replacement_place = candidate.place

        replacement_ticket = (
            direct_url if may_upgrade_ticket else current.ticket_url
        )
        replacement_route = current.route
        if (
            replacement_route is None
            and same_event_identity
            and _normalized_event_title(current.title).startswith("экскурсия")
        ):
            replacement_route = route_from_title(candidate.title)

        current = replace(
            current,
            place=replacement_place,
            ticket_url=replacement_ticket,
            route=replacement_route,
        )
        result.append(current)

    return tuple(result)


def _merge_municipal_admission_aliases(events):
    """Collapse translated aliases proven to be the same municipal occurrence."""

    def evidence_key(event):
        if not event.admission_evidence:
            return ""
        return _normalized_event_title(event.admission_evidence)

    def title_size(event):
        return len([
            word for word in _normalized_event_title(event.title).split()
            if len(word) > 2
        ])

    result = []
    for event in events:
        key = evidence_key(event)
        if event.starts_at is None or not key:
            result.append(event)
            continue

        duplicate_index = next((
            index
            for index, current in enumerate(result)
            if current.starts_at == event.starts_at
            and current.category == event.category
            and evidence_key(current) == key
            and not (
                current.ticket_price_cents is not None
                and event.ticket_price_cents is not None
                and current.ticket_price_cents != event.ticket_price_cents
            )
            and not (
                current.ticket_url is not None
                and event.ticket_url is not None
                and current.ticket_url != event.ticket_url
            )
        ), None)
        if duplicate_index is None:
            result.append(event)
            continue

        current = result[duplicate_index]
        preferred, alias = (
            (event, current)
            if title_size(event) > title_size(current)
            else (current, event)
        )
        result[duplicate_index] = replace(
            preferred,
            ticket_url=preferred.ticket_url or alias.ticket_url,
            place=preferred.place or alias.place,
            image_url=preferred.image_url or alias.image_url,
        )

    return tuple(result)


def _merge_events(*groups):
    result = []

    def richer_title(current, candidate):
        """Only a clear token-prefix expansion may replace a matched title."""

        def tokens(value):
            normalized = unicodedata.normalize("NFKD", value.casefold())
            normalized = "".join(
                character for character in normalized
                if not unicodedata.combining(character)
            )
            return re.findall(r"[^\W_]+", normalized)

        base, expanded = tokens(current), tokens(candidate)
        generic = len(base) <= 3 and not any(
            marker in current for marker in (":", "«", "»", '"')
        )
        return (
            candidate if generic and len(expanded) > len(base)
            and expanded[:len(base)] == base else current
        )

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

    def agenda_booking_identity(value):
        """Return one occurrence-specific Agenda booking identity."""

        if value is None:
            return None
        normalized = normalize_ticket_url(value)
        if normalized is None:
            return None
        parsed = urllib.parse.urlparse(normalized)
        if (
            parsed.hostname not in {
                "agendaguardamar.com",
                "www.agendaguardamar.com",
            }
            or not parsed.path.startswith("/entradas/")
        ):
            return None
        query = urllib.parse.parse_qs(parsed.query)
        event_date = (query.get("webfecha") or [None])[0]
        event_time = (query.get("webhora") or [None])[0]
        if not isinstance(event_date, str) or not isinstance(event_time, str):
            return None
        return (
            parsed.path.casefold(),
            tuple(sorted(urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            ))),
        )

    def richer_place(current, candidate):
        """Prefer a strictly more specific compatible venue label."""

        if current is None:
            return candidate
        if candidate is None:
            return current
        current_words = normalized_words(current)
        candidate_words = normalized_words(candidate)
        added_words = candidate_words - current_words
        venue_detail_words = {
            "hall", "sala", "salon", "salón", "auditorio",
            "patio", "terraza", "vestibulo", "vestíbulo", "exposiciones",
        }
        if (
            current_words
            and current_words < candidate_words
            and added_words <= venue_detail_words
        ):
            return candidate
        return current

    for group in groups:
        for event in group:
            if _is_routine_event(event):
                continue
            normalized_title = normalize_title(event.title)
            event_booking = agenda_booking_identity(event.ticket_url)
            duplicate_index = None
            for index, current in enumerate(result):
                current_booking = agenda_booking_identity(current.ticket_url)
                if (
                    current_booking is not None
                    and event_booking is not None
                    and current_booking != event_booking
                ):
                    continue
                if not (
                    current.starts_at is None
                    or event.starts_at is None
                    or current.starts_at == event.starts_at
                ):
                    continue
                if (
                    normalized_title == normalize_title(current.title)
                    or overlap(current.title, event.title) >= 0.5
                    or (
                        current_booking is not None
                        and current_booking == event_booking
                    )
                    or (
                        overlap(current.title, event.title) >= 0.2
                        and current.place is not None
                        and event.place is not None
                        and overlap(current.place, event.place) >= 0.5
                    )
                ):
                    duplicate_index = index
                    break
            if duplicate_index is not None:
                current = result[duplicate_index]
                current_booking = agenda_booking_identity(current.ticket_url)
                same_booking = (
                    current_booking is not None
                    and current_booking == agenda_booking_identity(event.ticket_url)
                )
                title_or_place_match = (
                    normalized_title == normalize_title(current.title)
                    or overlap(current.title, event.title) >= 0.5
                    or (
                        overlap(current.title, event.title) >= 0.2
                        and current.place is not None
                        and event.place is not None
                        and overlap(current.place, event.place) >= 0.5
                    )
                )
                if same_booking and not title_or_place_match:
                    # The booking occurrence proves identity, but not that every
                    # loosely parsed Agenda detail should override the richer
                    # earlier event.  Deduplicate only.
                    continue
                result[duplicate_index] = replace(
                    current,
                    title=richer_title(current.title, event.title),
                    starts_at=current.starts_at or event.starts_at,
                    ends_at=current.ends_at or event.ends_at,
                    place=richer_place(current.place, event.place),
                    ticket_price_cents=(
                        current.ticket_price_cents
                        if current.ticket_price_cents is not None
                        else event.ticket_price_cents
                    ),
                    ticket_price_is_from=(
                        current.ticket_price_is_from
                        if current.ticket_price_cents is not None
                        else event.ticket_price_is_from
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
                    teaser=current.teaser or event.teaser,
                    duration_minutes=(
                        current.duration_minutes or event.duration_minutes
                    ),
                    audience_label=(
                        current.audience_label or event.audience_label
                    ),
                    details=tuple(dict.fromkeys(
                        (*current.details, *event.details)
                    )),
                    place_query=current.place_query or event.place_query,
                    meeting_point=current.meeting_point or event.meeting_point,
                    schedule_note=current.schedule_note or event.schedule_note,
                    access_note=current.access_note or event.access_note,
                    route=current.route or event.route,
                    active_until=current.active_until or event.active_until,
                    active_from=current.active_from or event.active_from,
                    is_final_day=current.is_final_day or event.is_final_day,
                    image_url=current.image_url or event.image_url,
                    programme_title=(
                        current.programme_title or event.programme_title
                    ),
                    programme_order=(
                        current.programme_order
                        if current.programme_order is not None
                        else event.programme_order
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
    library_agenda_state_path: Path = Path("state/library_agenda.json"),
    am_guardamar_state_path: Path = Path("state/am_guardamar.json"),
    facv_state_path: Path = Path("state/facv_events.json"),
    pesca_cv_state_path: Path = Path("state/pesca_cv_events.json"),
    blood_donation_state_path: Path = Path("state/blood_donation.json"),
    diagnostics: Optional[List[SourceDiagnostic]] = None,
    translation_cache_path: Optional[Path] = None,
    aemet_digest: Optional[MorningDigest] = None,
    fetch_aemet: bool = True,
    aemet_fallback: Optional[MorningDigest] = None,
    aemet_observer: Optional[Callable[[MorningDigest], None]] = None,
    pharmacy_state_path: Optional[Path] = None,
    cams_data_url: str = "",
    cams_cache_path: Path = Path("state/cams.json"),
    fetch_cams_remote: bool = True,
    fetch_meteosalud_data: bool = True,
    heat_health_fallback: Optional[HeatHealthRisk] = None,
    cold_health_fallback: Optional[ColdHealthRisk] = None,
    environment_observer: Optional[
        Callable[[Optional[HeatHealthRisk], Optional[ColdHealthRisk], Optional[datetime]], None]
    ] = None,
    environment_detail_observer: Optional[Callable] = None,
    fetch_environment: bool = True,
    emergency_risk_state_path: Path = Path("state/emergency_risks.json"),
) -> str:
    """Build the Morning Digest without beach-status collection."""

    translation_path = translation_cache_path or Path("state/event_translations.json")
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
    library_agenda_task = asyncio.create_task(
        fetch_today_library_events(
            now,
            library_agenda_state_path,
            translation_path,
        )
    )
    am_guardamar_task = asyncio.create_task(
        fetch_today_am_guardamar_events(
            now,
            am_guardamar_state_path,
            translation_path,
        )
    )
    facv_task = asyncio.create_task(
        fetch_today_facv_events(
            now,
            facv_state_path,
            translation_path,
        )
    )
    pesca_cv_task = asyncio.create_task(
        fetch_today_pesca_cv_events(
            now,
            pesca_cv_state_path,
            translation_path,
        )
    )
    blood_donation_task = asyncio.create_task(
        fetch_today_blood_donation_events(
            now,
            blood_donation_state_path,
        )
    )
    meteosalud_task = (
        asyncio.create_task(fetch_meteosalud(now))
        if fetch_environment
        and fetch_meteosalud_data
        and heat_health_fallback is None
        else None
    )
    meteosalud_cold_task = (
        asyncio.create_task(fetch_meteosalud_cold(now))
        if fetch_environment
        and fetch_meteosalud_data
        and cold_health_fallback is None
        else None
    )
    cams_task = (
        asyncio.create_task(
            fetch_cams(
                cams_data_url,
                cams_cache_path,
                now,
                allow_remote=fetch_cams_remote,
                diagnostics=diagnostics,
            )
        )
        if fetch_environment and (cams_data_url or not fetch_cams_remote)
        else None
    )
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
    # Beach status has its own later daily lifecycle. Never let a stale or
    # caller-provided beach payload leak back into the Morning Digest.
    digest = replace(digest, beach=None, beach_notice=None)

    if digest.weather is not None:
        sunrise, sunset = sun_times(now)
        digest = replace(
            digest,
            weather=replace(
                digest.weather, sunrise=sunrise, sunset=sunset
            ),
        )

    heat_health_risk = heat_health_fallback
    if meteosalud_task is not None:
        try:
            heat_health_risk = await meteosalud_task
        except EnvironmentError as exc:
            LOGGER.warning("Meteosalud unavailable; omitting health risk: %s", exc)
            if diagnostics is not None:
                diagnostics.append(source_error(
                    "METEOSALUD", "Meteosalud", exc
                ))
    cold_health_risk = cold_health_fallback
    if meteosalud_cold_task is not None:
        try:
            cold_health_risk = await meteosalud_cold_task
        except EnvironmentError as exc:
            LOGGER.warning("Meteosalud frío unavailable; omitting cold risk: %s", exc)
            if diagnostics is not None:
                diagnostics.append(source_error(
                    "METEOSALUD-COLD", "Meteosalud frío", exc
                ))
    air_quality = pollen = None
    cams_forecast_base = None
    if cams_task is not None:
        try:
            air_quality, pollen, cams_forecast_base = await cams_task
        except EnvironmentError as exc:
            LOGGER.warning("CAMS unavailable; omitting air and pollen: %s", exc)
            if diagnostics is not None:
                diagnostics.append(source_error("CAMS", "CAMS", exc))
    if environment_observer is not None:
        try:
            environment_observer(
                heat_health_risk, cold_health_risk, cams_forecast_base
            )
        except (OSError, ValueError) as exc:
            LOGGER.warning("Morning environment state could not be saved: %s", exc)
    if environment_detail_observer is not None:
        try:
            environment_detail_observer(
                heat_health_risk, cold_health_risk, air_quality, pollen,
                cams_forecast_base,
            )
        except (OSError, ValueError) as exc:
            LOGGER.warning("Detailed environment state could not be saved: %s", exc)

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
        library_events = await library_agenda_task
    except LibraryAgendaError as exc:
        LOGGER.warning("Library agenda unavailable; omitting events: %s", exc)
        if diagnostics is not None:
            diagnostics.append(source_error(
                "LIBRARY", "Biblioteca Municipal", exc
            ))
        library_events = ()
    try:
        am_guardamar_events = await am_guardamar_task
    except AmGuardamarError as exc:
        LOGGER.warning("AM Guardamar unavailable; omitting events: %s", exc)
        if diagnostics is not None:
            diagnostics.append(source_error(
                "AM-GUARDAMAR", "AM Guardamar", exc
            ))
        am_guardamar_events = ()
    try:
        facv_events = await facv_task
    except FacvSourceError as exc:
        LOGGER.warning("FACV local catalog unavailable; omitting events: %s", exc)
        if diagnostics is not None:
            diagnostics.append(source_error("FACV", "FACV", exc))
        facv_events = ()
    try:
        pesca_cv_events = await pesca_cv_task
    except PescaCvSourceError as exc:
        LOGGER.warning("Pesca CV local catalog unavailable; omitting events: %s", exc)
        if diagnostics is not None:
            diagnostics.append(source_error(
                "PESCA-CV", "Federación Pesca CV", exc
            ))
        pesca_cv_events = ()
    try:
        blood_donation_events = await blood_donation_task
    except BloodDonationError as exc:
        LOGGER.warning(
            "Blood-donation snapshot unavailable; omitting events: %s",
            exc,
        )
        if diagnostics is not None:
            diagnostics.append(source_error(
                "BLOOD-DONATION", "Донорство крови", exc
            ))
        blood_donation_events = ()

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
            if not pharmacies and diagnostics is not None:
                diagnostics.append(SourceDiagnostic(
                    "PHARMACY-NO-TODAY",
                    "Дежурные аптеки",
                    "в локальном каталоге нет дежурства на текущую дату",
                ))
        except OSError as exc:
            LOGGER.warning(
                "Pharmacy catalog unavailable; omitting the row: %s", exc
            )
            if diagnostics is not None:
                diagnostics.append(source_error(
                    "PHARMACY", "Дежурные аптеки", exc
                ))

    municipal_events = _prefer_agenda_guardamar_venues(
        municipal_events,
        events,
    )
    municipal_events = _merge_municipal_admission_aliases(
        municipal_events
    )

    fire_risk_level = None
    dry_thunderstorm_risk_level = None
    hydrology_state = None
    try:
        (
            fire_risk_level,
            dry_thunderstorm_risk_level,
            hydrology_state,
        ) = EmergencyRiskState(emergency_risk_state_path).morning_values(now)
    except EmergencyRiskError as exc:
        LOGGER.warning(
            "Official risk state unavailable; omitting compact risk lines: %s",
            exc.diagnostic_code,
        )

    return build_message(
        replace(
            digest,
            pharmacies=pharmacies,
            holidays=official_holidays_on(
                now.astimezone(GUARDAMAR_TIMEZONE).date()
            ),
            celebrations=celebrations_on(
                now.astimezone(GUARDAMAR_TIMEZONE).date()
            ),
            events=_merge_events(
                weekly_events,
                mayor_events,
                municipal_events,
                events,
                library_events,
                am_guardamar_events,
                facv_events,
                pesca_cv_events,
                blood_donation_events,
            ),
            heat_health_risk=heat_health_risk,
            cold_health_risk=cold_health_risk,
            air_quality=air_quality,
            pollen=pollen,
            fire_risk_level=fire_risk_level,
            dry_thunderstorm_risk_level=dry_thunderstorm_risk_level,
            hydrology_state=hydrology_state,
        ),
        now=now,
    )
