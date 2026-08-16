"""Monthly official municipal agenda poster with a small local snapshot."""

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import tempfile
import urllib.parse
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .gemini import (
    GeminiError,
    extract_agenda_events,
    extract_agenda_text_events,
    translate_event_titles,
    verify_agenda_poster_events,
)
from .event_translations import cached_title
from .event_urls import normalize_ticket_url
from .event_places import canonical_event_place
from .reviewed import (
    ReviewedDataError,
    normalized_title,
    reviewed_poster,
    schedule_rules,
)
from .models import Event
from .diagnostics import SourceDiagnostic, source_error
from .todo_cultura import (
    TodoCulturaAdmission,
    TodoCulturaError,
    TodoCulturaParticipation,
    _all_mentioned_dates,
    _admissions,
    fetch_program_window,
)

LOGGER = logging.getLogger(__name__)

AGENDA_PAGE_URL = "https://guardamarturismo.com/agenda-cultural/"
PAGE_HOSTS = {"guardamarturismo.com", "www.guardamarturismo.com"}
POSTER_HOSTS = {"guardamardelsegura.es", "www.guardamardelsegura.es"}
PAGE_LIMIT_BYTES = 500_000
POSTER_LIMIT_BYTES = 4_000_000
REQUEST_TIMEOUT_SECONDS = 15
MAX_EVENTS = 100
MAX_INDIVIDUAL_TRANSLATION_RECOVERY = 12
TRANSITION_HORIZON_DAYS = 7
TEXT_EXTRACTOR_VERSION = 2
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
class MunicipalAgendaError(RuntimeError):
    """An operator-safe municipal agenda failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID",
        status: Optional[int] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.server_status = status
        self.safe_description = description


@dataclass(frozen=True)
class SourceEvent:
    title_es: str
    start_date: date
    end_date: date
    start_time: Optional[str]
    end_time: Optional[str]
    place: Optional[str]
    category: str
    sources: Tuple[str, ...] = ()
    ticket_price_cents: Optional[int] = None
    ticket_url: Optional[str] = None
    participation_note: Optional[str] = None
    registration_contact: Optional[str] = None
    capacity_limited: bool = False
    admission_evidence: Optional[str] = None


class _PosterParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = dict(attrs)
        candidate = values.get("href") if tag.casefold() == "a" else None
        if tag.casefold() == "img":
            candidate = values.get("src")
        if candidate:
            self.urls.append(candidate)


def _is_allowed_url(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in allowed_hosts


_TRANSPORT_DESCRIPTIONS = {
    "URL-POLICY": "адрес не принадлежит официальной афише",
    "REDIRECT": "получен недопустимый адрес ответа официальной афиши",
    "CONTENT-TYPE": "официальная афиша вернула неожиданный формат",
    "TIMEOUT": "сервер не ответил до истечения тайм-аута",
    "NETWORK": "не удалось установить сетевое соединение",
    "TOO-LARGE": "ответ превысил допустимый размер",
}


def _read_url(
    url: str,
    allowed_hosts: set[str],
    limit: int,
) -> Tuple[bytes, str]:
    page_request = allowed_hosts == PAGE_HOSTS
    accepted_types = (
        frozenset({"text/html"})
        if page_request
        else frozenset({"image/jpeg", "image/png", "image/webp"})
    )
    try:
        payload, _, mime_type = fetch_bounded(
            url,
            is_allowed_url=lambda value: _is_allowed_url(
                value, allowed_hosts
            ),
            accepted_types=accepted_types,
            limit_bytes=limit,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": (
                    "text/html"
                    if page_request
                    else "image/jpeg,image/png,image/webp"
                ),
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise MunicipalAgendaError(
            f"Municipal agenda request failed: {exc.code}",
            code=exc.code,
            status=exc.status,
            description=(
                f"сервер вернул HTTP {exc.status}"
                if exc.status is not None
                else _TRANSPORT_DESCRIPTIONS.get(exc.code)
            ),
        ) from exc
    return payload, mime_type


def extract_poster_url(payload: bytes) -> str:
    """Find the official MUPI monthly poster linked by the tourism page."""

    parser = _PosterParser()
    parser.feed(payload.decode("utf-8", "replace"))
    for candidate in reversed(parser.urls):
        url = urllib.parse.urljoin(AGENDA_PAGE_URL, candidate)
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.casefold()
        if (
            parsed.scheme == "https"
            and parsed.hostname in POSTER_HOSTS
            and "/wp-content/uploads/" in path
            and "mupi-" in path
            and path.endswith((".jpg", ".jpeg", ".png", ".webp"))
        ):
            return url
    raise MunicipalAgendaError(
        "Official monthly poster was not found",
        code="NO-POSTER",
        description="на странице не найдена официальная месячная афиша",
    )


_SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def extract_official_agenda_text(payload: bytes) -> Tuple[str, str]:
    """Return the bounded monthly programme section and its declared month."""

    decoded = html.unescape(payload.decode("utf-8", "replace"))
    plain = " ".join(re.sub(r"<[^>]+>", " ", decoded).split())
    matches = list(re.finditer(
        r"AGENDA\s+CULTURAL(?:\s+GUARDAMAR)?\s+"
        r"(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|"
        r"SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)\s+"
        r"((?:19|20)\d{2})",
        plain,
        re.IGNORECASE,
    ))
    if not matches:
        raise MunicipalAgendaError(
            "Official text agenda month was not found",
            code="NO-TEXT-MONTH",
            description="в официальной текстовой программе не найден месяц",
        )
    match = matches[-1]
    month_number = _SPANISH_MONTHS[match.group(1).casefold()]
    month = f"{int(match.group(2)):04d}-{month_number:02d}"
    section = plain[match.start():]
    for marker in (" Ver Agenda ", " Guardamar del Segura Turisme Guardamar"):
        marker_index = section.find(marker)
        if marker_index >= 0:
            section = section[:marker_index]
    if not 100 <= len(section) <= 12_000:
        raise MunicipalAgendaError(
            "Official text agenda section has an invalid size",
            code="TEXT-SIZE",
            description="официальная текстовая программа пуста или слишком велика",
        )
    return section, month


def _normalized_words(value: str) -> set[str]:
    normalized = re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE)
    aliases = {
        "plaça": "plaza",
        "llauradors": "labradores",
        "pescadors": "pescadores",
        "castell": "castillo",
    }
    return {
        aliases.get(word, word)
        for word in normalized.split()
        if len(word) > 2
    }


def _word_overlap(left: str, right: str) -> float:
    left_words = _normalized_words(left)
    right_words = _normalized_words(right)
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / min(
        len(left_words), len(right_words)
    )


def _supported_title(title: str, evidence: str) -> bool:
    """Require every meaningful title word to occur in the exact quotation."""

    title_words = _claim_words(title)
    evidence_words = _claim_words(evidence)
    if not title_words:
        return False
    return title_words <= evidence_words


def _claim_words(value: str) -> set[str]:
    """Keep claim-bearing tokens, including short names such as DJ."""

    stop_words = {
        "a", "al", "de", "del", "el", "en", "la", "las", "los",
        "o", "para", "por", "un", "una", "y",
    }
    return {
        word
        for word in re.sub(
            r"[^\w]+", " ", value.casefold(), flags=re.UNICODE
        ).split()
        if len(word) >= 2 and word not in stop_words
    }


def _evidence_supports_date(value: date, evidence: str) -> bool:
    if value.isoformat() in evidence:
        return True
    return value in _all_mentioned_dates(evidence, value)


def _evidence_supports_time(value: str, evidence: str) -> bool:
    hour, minute = value.split(":")
    hour_value = str(int(hour))
    minute_value = str(int(minute))
    if int(minute) == 0:
        pattern = (
            rf"(?<!\d)(?:"
            rf"a\s+las\s+{hour_value}(?:[.,:]0{{1,2}})?"
            rf"(?:\s*h(?:oras?)?\.?)?"
            rf"|{hour_value}[.,:]0{{1,2}}(?:\s*h(?:oras?)?\.?)?"
            rf"|{hour_value}\s+a\s+\d{{1,2}}"
            rf"(?:[.,:]\d{{2}})?\s*h(?:oras?)?\.?"
            rf"|{hour_value}\s*h(?:oras?)?\.?)\b"
        )
    else:
        pattern = (
            rf"(?<!\d){hour_value}[.,:]{minute_value.zfill(2)}"
            rf"\s*(?:h(?:oras?)?\.?)?\b"
        )
    return re.search(pattern, evidence, re.IGNORECASE) is not None


def _evidence_supports_place(place: str, evidence: str) -> bool:
    place_words = _claim_words(place)
    return bool(place_words) and place_words <= _claim_words(evidence)


def _richer_title(current: str, candidate: str) -> str:
    """Use a corroborating superset title without replacing its identity."""

    current_words = _normalized_words(current)
    candidate_words = _normalized_words(candidate)
    if (
        len(candidate_words) >= len(current_words) + 2
        and current_words
        and len(current_words & candidate_words) / len(current_words) >= 0.75
    ):
        return candidate
    return current


def _same_occurrence(left: SourceEvent, right: SourceEvent) -> bool:
    if (
        left.start_date != right.start_date
        or left.end_date != right.end_date
        or left.start_time != right.start_time
    ):
        return False
    if (
        left.place is not None
        and right.place is not None
        and _word_overlap(left.place, right.place) < 0.5
    ):
        return False
    return _word_overlap(left.title_es, right.title_es) >= 0.5


def _poster_conflicts_with_text(
    text_event: SourceEvent,
    poster_event: SourceEvent,
) -> bool:
    """Detect a less reliable poster rendering of a text occurrence."""

    if (
        not set(text_event.sources) & {"turismo_html"}
        or not set(poster_event.sources) & {"mupi", "mupi_reviewed"}
    ):
        return False
    dates_overlap = not (
        poster_event.end_date < text_event.start_date
        or poster_event.start_date > text_event.end_date
    )
    if not dates_overlap:
        return False
    if (
        text_event.start_time is not None
        and poster_event.start_time is not None
        and text_event.start_time != poster_event.start_time
    ):
        return False
    if _word_overlap(text_event.title_es, poster_event.title_es) >= 0.5:
        return True
    same_time = (
        text_event.start_time is not None
        and text_event.start_time == poster_event.start_time
    )
    same_place = (
        text_event.place is not None
        and poster_event.place is not None
        and _word_overlap(text_event.place, poster_event.place) >= 0.5
    )
    return same_time and same_place


def merge_text_and_poster_events(
    text_events: Tuple[SourceEvent, ...],
    poster_events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Prefer official text facts and add only distinct poster occurrences."""

    merged = list(text_events)
    for poster_event in poster_events:
        duplicate_index = next((
            index
            for index, text_event in enumerate(merged)
            if _same_occurrence(text_event, poster_event)
            or _poster_conflicts_with_text(text_event, poster_event)
        ), None)
        if duplicate_index is None:
            merged.append(poster_event)
            continue
        current = merged[duplicate_index]
        same_occurrence = _same_occurrence(current, poster_event)
        candidate_is_text = bool(
            set(poster_event.sources) & {"todo_cultura", "todo_cultura_reviewed"}
        )
        merged[duplicate_index] = SourceEvent(
            **{
                **current.__dict__,
                "title_es": (
                    _richer_title(current.title_es, poster_event.title_es)
                    if same_occurrence and candidate_is_text
                    else current.title_es
                ),
                "sources": tuple(dict.fromkeys(
                    current.sources + poster_event.sources
                )),
                "ticket_price_cents": (
                    current.ticket_price_cents
                    if current.ticket_price_cents is not None
                    else (
                        poster_event.ticket_price_cents
                        if same_occurrence else None
                    )
                ),
                "ticket_url": current.ticket_url or (
                    poster_event.ticket_url if same_occurrence else None
                ),
                "participation_note": (
                    current.participation_note
                    or (poster_event.participation_note if same_occurrence else None)
                ),
                "registration_contact": (
                    current.registration_contact
                    or (poster_event.registration_contact if same_occurrence else None)
                ),
                "capacity_limited": (
                    current.capacity_limited
                    or (poster_event.capacity_limited if same_occurrence else False)
                ),
                "admission_evidence": current.admission_evidence or (
                    poster_event.admission_evidence if same_occurrence else None
                ),
            }
        )
    return tuple(merged[:MAX_EVENTS])


def _enrich_admissions(
    events: Tuple[SourceEvent, ...],
    admissions: Tuple[TodoCulturaAdmission, ...],
    detail_source: Optional[str] = "todo_cultura_detail",
) -> Tuple[SourceEvent, ...]:
    """Attach event-local admission facts to matching Todo Cultura events."""

    enriched = []
    generic_words = {
        "actividad", "baile", "concierto", "entrada", "evento",
        "exposicion", "exposición", "feria", "festival", "representacion",
        "representación", "sesion", "sesión",
        "taller", "teatro",
    }

    def matches(admission: TodoCulturaAdmission, event: SourceEvent):
        dates = admission.event_dates or (
            (admission.event_date,) if admission.event_date is not None else ()
        )
        if dates and not any(
            event.start_date <= candidate <= event.end_date for candidate in dates
        ):
            return None
        if (
            admission.start_time is not None
            and event.start_time != admission.start_time
        ):
            return None
        overlap = _word_overlap(event.title_es, admission.title_hint)
        shared = (
            _normalized_words(event.title_es)
            & _normalized_words(admission.title_hint)
        )
        discriminating = len(shared) >= 2 or bool(shared - generic_words)
        if overlap < 0.5 or not discriminating:
            return None
        return overlap

    for event in events:
        ranked = []
        for admission in admissions:
            overlap = matches(admission, event)
            if overlap is not None:
                ranked.append((overlap, admission))
        ranked.sort(key=lambda item: item[0], reverse=True)
        best = ranked[0][1] if ranked else None
        if best is not None:
            same_identity_sessions = {
                candidate.start_time
                for candidate in events
                if candidate.start_date == event.start_date
                and matches(best, candidate) is not None
            }
            tied = [
                candidate for overlap, candidate in ranked
                if overlap == ranked[0][0]
            ]
            ambiguous_facts = {
                (candidate.price_cents, candidate.ticket_url, candidate.start_time)
                for candidate in tied
            }
            if (
                best.start_time is None and len(same_identity_sessions) > 1
            ) or len(ambiguous_facts) > 1:
                best = None
        if best is not None:
            event = replace(
                event,
                sources=tuple(dict.fromkeys(
                    event.sources
                    + ((detail_source,) if detail_source is not None else ())
                )),
                ticket_price_cents=(
                    event.ticket_price_cents
                    if event.ticket_price_cents is not None
                    else best.price_cents
                ),
                ticket_url=event.ticket_url or best.ticket_url,
                admission_evidence=(
                    event.admission_evidence or best.evidence or None
                ),
            )
        enriched.append(event)
    return tuple(enriched)


def _enrich_todo_participation(
    events: Tuple[SourceEvent, ...],
    details: Tuple[TodoCulturaParticipation, ...],
    target_date: date,
) -> Tuple[SourceEvent, ...]:
    """Attach explicit event-local registration facts to one occurrence."""

    def matches(
        detail: TodoCulturaParticipation,
        event: SourceEvent,
    ) -> Optional[float]:
        if detail.event_dates and not any(
            event.start_date <= candidate <= event.end_date
            for candidate in detail.event_dates
        ):
            return None
        if (
            detail.start_time is not None
            and event.start_time != detail.start_time
        ):
            return None
        overlap = _word_overlap(event.title_es, detail.title_hint)
        return overlap if overlap >= 0.5 else None

    enriched = []
    for event in events:
        if not event.start_date <= target_date <= event.end_date:
            enriched.append(event)
            continue
        ranked = []
        for detail in details:
            candidate_overlap = matches(detail, event)
            if candidate_overlap is not None:
                ranked.append((candidate_overlap, detail))
        ranked.sort(key=lambda item: item[0], reverse=True)
        best = ranked[0][1] if ranked else None
        if best is not None:
            tied = [
                detail for overlap, detail in ranked
                if overlap == ranked[0][0]
            ]
            facts = {
                (
                    detail.registration_contact,
                    detail.participation_note,
                    detail.capacity_limited,
                    detail.start_time,
                )
                for detail in tied
            }
            matching_sessions = {
                candidate.start_time
                for candidate in events
                if candidate.start_date == event.start_date
                and matches(best, candidate) is not None
            }
            if (
                len(facts) > 1
                or (
                    best.start_time is None
                    and len(matching_sessions) > 1
                )
            ):
                best = None
        if best is None:
            enriched.append(event)
            continue
        enriched.append(replace(
            event,
            sources=tuple(dict.fromkeys(
                event.sources + ("todo_cultura_detail",)
            )),
            participation_note=(
                event.participation_note or best.participation_note
            ),
            registration_contact=(
                event.registration_contact or best.registration_contact
            ),
            capacity_limited=(
                event.capacity_limited or best.capacity_limited
            ),
        ))
    return tuple(enriched)


def intersect_verified_poster_events(
    first: Tuple[SourceEvent, ...],
    verified: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Keep only independently repeated MUPI facts with matching key fields."""

    accepted = []
    embedded_digit = re.compile(r"[A-Za-zÀ-ÿ]\d|\d[A-Za-zÀ-ÿ]")
    for candidate in verified:
        if embedded_digit.search(candidate.title_es):
            continue
        if any(
            not embedded_digit.search(original.title_es)
            and
            original.start_date == candidate.start_date
            and original.end_date == candidate.end_date
            and original.start_time == candidate.start_time
            and len(
                _normalized_words(original.title_es)
                & _normalized_words(candidate.title_es)
            ) / max(
                1,
                min(
                    len(_normalized_words(original.title_es)),
                    len(_normalized_words(candidate.title_es)),
                ),
            ) >= 0.5
            for original in first
        ):
            accepted.append(candidate)
    return tuple(accepted)


def _clean_text(value: Any, maximum: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MunicipalAgendaError("invalid poster event text")
    result = " ".join(value.split())
    if not result or len(result) > maximum:
        raise MunicipalAgendaError("invalid poster event text")
    return result


def _poster_month(poster_url: str) -> str:
    filename = urllib.parse.unquote(
        urllib.parse.urlparse(poster_url).path.rsplit("/", 1)[-1]
    ).casefold()
    month_names = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "setiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12,
    }
    year_match = re.search(r"(?:19|20)\d{2}", filename)
    for name, month_number in month_names.items():
        if name in filename and year_match is not None:
            return f"{int(year_match.group()):04d}-{month_number:02d}"
    match = re.search(r"/wp-content/uploads/(\d{4})/(\d{2})/", poster_url)
    if match is None:
        raise MunicipalAgendaError(
            "Municipal poster URL has no month",
            code="POSTER-MONTH",
            description="в адресе официальной афиши не указан месяц",
        )
    year, month = (int(value) for value in match.groups())
    try:
        date(year, month, 1)
    except ValueError as exc:
        raise MunicipalAgendaError(
            "Municipal poster URL has an invalid month",
            code="POSTER-MONTH",
            description="в адресе официальной афиши указан неверный месяц",
        ) from exc
    return f"{year:04d}-{month:02d}"


def _month_window(month: str) -> Tuple[date, date]:
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise MunicipalAgendaError(
            "Municipal OCR returned an invalid month",
            code="MONTH",
            description="OCR вернул неверный месяц афиши",
        ) from exc
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_after_next = (
        next_month.replace(day=28) + timedelta(days=4)
    ).replace(day=1)
    return first, month_after_next - timedelta(days=1)


def normalize_extraction(
    result: Dict[str, Any],
    expected_month: Optional[str] = None,
    source: str = "mupi",
    source_text: Optional[str] = None,
) -> Tuple[SourceEvent, ...]:
    """Validate OCR output and discard routine non-event entries."""

    allowed_dates = None
    if expected_month is not None:
        if result.get("month") != expected_month:
            raise MunicipalAgendaError(
                "Municipal OCR month does not match the poster",
                code="MONTH",
                description="месяц в OCR не совпадает с месяцем афиши",
            )
        allowed_dates = _month_window(expected_month)
    raw_events = result.get("events")
    if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
        raise MunicipalAgendaError("invalid poster event list")
    events: List[SourceEvent] = []
    seen = set()
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise MunicipalAgendaError("invalid poster event")
        category = raw.get("category")
        if category not in {
            "event",
            "exhibition",
            "workshop",
            "municipal_service",
            "opening_hours",
        }:
            raise MunicipalAgendaError("invalid poster event category")
        if category in {"municipal_service", "opening_hours"}:
            continue
        start_raw = raw.get("start_date")
        end_raw = raw.get("end_date") or start_raw
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            raise MunicipalAgendaError("invalid poster event date")
        try:
            start_date = date.fromisoformat(start_raw)
            end_date = date.fromisoformat(end_raw)
        except ValueError as exc:
            raise MunicipalAgendaError("invalid poster event date") from exc
        if start_date > end_date or (end_date - start_date).days > 62:
            raise MunicipalAgendaError("invalid poster event range")
        if allowed_dates is not None and (
            start_date < allowed_dates[0] or end_date > allowed_dates[1]
        ):
            raise MunicipalAgendaError(
                "Municipal OCR event is outside the poster window",
                code="MONTH",
                description=(
                    "OCR вернул событие за пределами месяца афиши "
                    "и следующего месяца"
                ),
            )
        times = []
        for field in ("start_time", "end_time"):
            value = raw.get(field)
            if value is not None:
                if not isinstance(value, str) or not _TIME_PATTERN.match(value):
                    raise MunicipalAgendaError("invalid poster event time")
                try:
                    datetime.strptime(value, "%H:%M")
                except ValueError as exc:
                    raise MunicipalAgendaError(
                        "invalid poster event time"
                    ) from exc
            times.append(value)
        start_time, end_time = times
        if end_time is not None and start_time is None:
            raise MunicipalAgendaError("event end time has no start time")
        title_es = _clean_text(raw.get("title_es"), 120) or ""
        place = _clean_text(raw.get("place"), 120)
        if source_text is not None:
            evidence = _clean_text(raw.get("evidence_es"), 600)
            if (
                evidence is None
                or len(evidence) < 10
                or evidence not in " ".join(source_text.split())
                or not _supported_title(title_es, evidence)
                or not _evidence_supports_date(start_date, evidence)
                or not _evidence_supports_date(end_date, evidence)
                or (
                    start_time is not None
                    and not _evidence_supports_time(start_time, evidence)
                )
                or (
                    end_time is not None
                    and not _evidence_supports_time(end_time, evidence)
                )
                or (
                    place is not None
                    and not _evidence_supports_place(place, evidence)
                )
            ):
                raise MunicipalAgendaError(
                    "event facts have no exact source evidence"
                )
        if place is not None:
            place = canonical_event_place(place)
        normalized_title = title_es.casefold()
        if "actividades del centro social juvenil" in normalized_title:
            continue
        if category != "exhibition" and start_date != end_date:
            # A date range does not prove that an activity happens every day.
            # Dated programme rows must be expanded into separate occurrences.
            continue
        ticket_price_cents = raw.get("ticket_price_cents")
        if ticket_price_cents is not None and (
            not isinstance(ticket_price_cents, int)
            or not 0 <= ticket_price_cents <= 100_000
        ):
            raise MunicipalAgendaError("invalid event ticket price")
        ticket_url = raw.get("ticket_url")
        if ticket_url is not None:
            if not isinstance(ticket_url, str):
                raise MunicipalAgendaError("invalid event ticket URL")
            normalized_ticket_url = normalize_ticket_url(ticket_url)
            if normalized_ticket_url is None:
                raise MunicipalAgendaError("invalid event ticket URL")
            ticket_url = normalized_ticket_url
        participation_note = _clean_text(raw.get("participation_note"), 180)
        registration_contact = _clean_text(
            raw.get("registration_contact"), 180
        )
        capacity_limited = raw.get("capacity_limited", False)
        if not isinstance(capacity_limited, bool):
            raise MunicipalAgendaError("invalid event capacity flag")
        admission_evidence = _clean_text(raw.get("admission_evidence"), 600)
        event = SourceEvent(
            title_es=title_es,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            place=place,
            category="event" if category == "workshop" else category,
            sources=(source,),
            ticket_price_cents=ticket_price_cents,
            ticket_url=ticket_url,
            participation_note=participation_note,
            registration_contact=registration_contact,
            capacity_limited=capacity_limited,
            admission_evidence=admission_evidence,
        )
        key = (event.title_es.casefold(), event.start_date, event.start_time)
        if key not in seen:
            seen.add(key)
            events.append(event)
    return tuple(events)


def normalize_extraction_candidates(
    result: Dict[str, Any],
    expected_month: str,
    source: str,
    source_text: Optional[str] = None,
) -> Tuple[SourceEvent, ...]:
    """Validate candidates independently so one bad card cannot erase a month."""

    if result.get("month") != expected_month:
        raise MunicipalAgendaError(
            "Municipal extraction month does not match its source",
            code="MONTH",
            description="месяц результата не совпадает с официальным источником",
        )
    raw_events = result.get("events")
    if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
        raise MunicipalAgendaError("invalid municipal event list")
    accepted: List[SourceEvent] = []
    for raw in raw_events:
        try:
            accepted.extend(normalize_extraction(
                {"month": expected_month, "events": [raw]},
                expected_month,
                source,
                source_text,
            ))
        except MunicipalAgendaError:
            continue
    if raw_events and not accepted:
        raise MunicipalAgendaError(
            "Every municipal event candidate was invalid",
            code="NO-VALID-EVENTS",
            description="все извлечённые мероприятия не прошли проверку",
        )
    return tuple(accepted)


def _snapshot_data(
    poster_url: str,
    poster_hash: str,
    fetched_at: datetime,
    events: Tuple[SourceEvent, ...],
    sources: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "version": 4,
        "poster_url": poster_url,
        "poster_sha256": poster_hash,
        "fetched_at": fetched_at.isoformat(),
        "sources": sources or {},
        "events": [
            {
                "title_es": event.title_es,
                "start_date": event.start_date.isoformat(),
                "end_date": event.end_date.isoformat(),
                "start_time": event.start_time,
                "end_time": event.end_time,
                "place": event.place,
                "category": event.category,
                "sources": list(event.sources),
                "ticket_price_cents": event.ticket_price_cents,
                "ticket_url": event.ticket_url,
                "participation_note": event.participation_note,
                "registration_contact": event.registration_contact,
                "capacity_limited": event.capacity_limited,
                "admission_evidence": event.admission_evidence,
            }
            for event in events
        ],
    }


def _source_event_key(event: SourceEvent) -> Tuple[Any, ...]:
    return (
        event.title_es.casefold(),
        event.start_date,
        event.start_time,
    )


def _merge_transition_events(
    new_events: Tuple[SourceEvent, ...],
    prior_events: Tuple[SourceEvent, ...],
    local_day: date,
) -> Tuple[SourceEvent, ...]:
    """Retain the prior poster's still-relevant one-week transition facts."""

    horizon = local_day + timedelta(days=TRANSITION_HORIZON_DAYS)
    merged = list(new_events)
    seen = {_source_event_key(event) for event in merged}
    for event in prior_events:
        if event.end_date < local_day or event.start_date > horizon:
            continue
        if any(
            _same_occurrence(current, event)
            or _poster_conflicts_with_text(current, event)
            for current in merged
        ):
            continue
        key = _source_event_key(event)
        if key not in seen:
            seen.add(key)
            merged.append(event)
    return tuple(merged[:MAX_EVENTS])


def _write_snapshot(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_snapshot(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") not in {1, 2, 3, 4}:
            raise ValueError
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if fetched_at.tzinfo is None:
            raise ValueError
        events = []
        for raw in data["events"]:
            normalized_events = normalize_extraction(
                {"events": [raw]},
                source=(
                    raw.get("sources", ["mupi"])[0]
                    if isinstance(raw, dict)
                    and isinstance(raw.get("sources", ["mupi"]), list)
                    and raw.get("sources", ["mupi"])
                    else "mupi"
                ),
            )
            if not normalized_events:
                continue
            normalized = normalized_events[0]
            raw_sources = raw.get("sources") if isinstance(raw, dict) else None
            if (
                isinstance(raw_sources, list)
                and raw_sources
                and all(isinstance(item, str) for item in raw_sources)
            ):
                normalized = SourceEvent(
                    **{
                        **normalized.__dict__,
                        "sources": tuple(dict.fromkeys(raw_sources)),
                    }
                )
            events.append(normalized)
        return {
            **data,
            "_events": tuple(events),
            "_fetched_at": fetched_at,
        }
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        MunicipalAgendaError,
    ) as exc:
        raise MunicipalAgendaError(
            "Municipal agenda snapshot is invalid",
            code="CORRUPT",
            description="локальный снимок афиши повреждён",
        ) from exc


_POSTER_SOURCES = frozenset({"mupi", "mupi_reviewed"})
_TEXT_SOURCES = frozenset({"turismo_html", "todo_cultura",
                           "todo_cultura_reviewed"})


def _is_poster_only(event: SourceEvent) -> bool:
    """Report whether OCR is the sole provenance behind this event."""

    sources = set(event.sources)
    return bool(sources & _POSTER_SOURCES) and not (sources & _TEXT_SOURCES)


def _reviewed_matches_text(
    current: SourceEvent,
    correction: SourceEvent,
) -> bool:
    """Match one reviewed recovery fact without collapsing distinct acts."""

    if (
        not set(current.sources) & _TEXT_SOURCES
        or current.start_date != correction.start_date
        or current.end_date != correction.end_date
        or (
            current.start_time is not None
            and correction.start_time is not None
            and current.start_time != correction.start_time
        )
    ):
        return False
    title_overlap = _word_overlap(current.title_es, correction.title_es)
    place_compatible = (
        current.place is None
        or correction.place is None
        or _word_overlap(current.place, correction.place) >= 0.5
    )
    if title_overlap >= 0.5 and place_compatible:
        return True
    return bool(
        current.start_time == correction.start_time
        and current.place is not None
        and correction.place is not None
        and _word_overlap(current.place, correction.place) >= 0.5
        and title_overlap >= 0.2
    )


def _merge_reviewed_details(
    current: SourceEvent,
    correction: SourceEvent,
) -> SourceEvent:
    """Fill absent bounded facts while preserving the text event identity."""

    return replace(
        current,
        start_time=current.start_time or correction.start_time,
        end_time=current.end_time or correction.end_time,
        place=current.place or correction.place,
        sources=tuple(dict.fromkeys(
            current.sources + correction.sources
        )),
        ticket_price_cents=(
            current.ticket_price_cents
            if current.ticket_price_cents is not None
            else correction.ticket_price_cents
        ),
        ticket_url=current.ticket_url or correction.ticket_url,
        participation_note=(
            current.participation_note or correction.participation_note
        ),
        registration_contact=(
            current.registration_contact or correction.registration_contact
        ),
        capacity_limited=(
            current.capacity_limited or correction.capacity_limited
        ),
        admission_evidence=(
            current.admission_evidence or correction.admission_evidence
        ),
    )


def _reviewed_source_event(entry: dict) -> SourceEvent:
    return SourceEvent(
        title_es=entry["title_es"],
        start_date=date.fromisoformat(entry["start_date"]),
        end_date=date.fromisoformat(entry["end_date"]),
        start_time=entry.get("start_time"),
        end_time=entry.get("end_time"),
        place=entry.get("place"),
        category=entry["category"],
        sources=tuple(entry.get("sources", ())),
        ticket_price_cents=entry.get("ticket_price_cents"),
        ticket_url=entry.get("ticket_url"),
        participation_note=entry.get("participation_note"),
        registration_contact=entry.get("registration_contact"),
        capacity_limited=bool(entry.get("capacity_limited", False)),
        admission_evidence=entry.get("admission_evidence"),
    )


def _apply_reviewed_corrections(
    poster_url: str,
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Repair facts manually verified against a specific official poster."""

    parsed = urllib.parse.urlparse(poster_url)
    poster_name = parsed.path.rsplit("/", 1)[-1].casefold()
    try:
        poster = reviewed_poster(poster_name)
    except ReviewedDataError as exc:
        # The drop filter exists because some poster rows are known to be
        # wrong. Without it those rows cannot be told apart, so every
        # poster-only event is withheld; text-corroborated facts survive.
        LOGGER.warning(
            "Reviewed poster data rejected; withholding poster-only "
            "events: %s",
            exc,
        )
        return tuple(
            event for event in events if not _is_poster_only(event)
        )
    if (
        poster is None
        or parsed.scheme != "https"
        or parsed.hostname not in POSTER_HOSTS
        or poster.upload_path not in parsed.path.casefold()
    ):
        return events
    # Expired reviewed occurrences are removed after their final date; the
    # drop filter still discards their known-bad OCR rows.
    reviewed = tuple(
        _reviewed_source_event(entry) for entry in poster.events
    )
    filtered = [
        event
        for event in events
        if not (
            _is_poster_only(event)
            and any(
                all(
                    term in normalized_title(event.title_es)
                    for term in clause
                )
                for clause in poster.drop_titles
            )
        )
    ]

    result = list(filtered)
    for correction in reviewed:
        match_index = next((
            index
            for index, current in enumerate(result)
            if _reviewed_matches_text(current, correction)
        ), None)
        if match_index is None:
            result.append(correction)
            continue
        result[match_index] = _merge_reviewed_details(
            result[match_index], correction
        )
    return tuple(result[:MAX_EVENTS])


def _rule_matches(rule, event: SourceEvent, local_day: date) -> bool:
    normalized = normalized_title(event.title_es)
    if not all(term in normalized for term in rule.match):
        return False
    for field, value in rule.requires.items():
        if field in {"start_date", "end_date"}:
            expected = (
                local_day if value == "today" else date.fromisoformat(value)
            )
            if getattr(event, field) != expected:
                return False
        elif getattr(event, field) != value:
            return False
    return True


def _apply_reviewed_daily_schedules(
    events: Tuple[SourceEvent, ...],
    local_day: date,
) -> Tuple[SourceEvent, ...]:
    """Apply event-specific hours published in the official text agenda."""

    try:
        rules = schedule_rules()
    except ReviewedDataError as exc:
        LOGGER.warning("Reviewed data rejected; schedules skipped: %s", exc)
        return events

    scheduled = []
    for event in events:
        rule = next(
            (
                candidate
                for candidate in rules
                if _rule_matches(candidate, event, local_day)
            ),
            None,
        )
        if rule is None:
            scheduled.append(event)
            continue
        changes = dict(rule.set_fields)
        if rule.weekday_windows is not None:
            day_key = (
                "sunday"
                if local_day.weekday() == 6
                else "saturday" if local_day.weekday() == 5 else "weekday"
            )
            window = rule.weekday_windows[day_key]
            if window is None:
                # The official agenda publishes no visits for this day.
                continue
            changes["start_time"], changes["end_time"] = window
        scheduled.append(replace(event, **changes))
    return tuple(scheduled)


async def refresh_municipal_catalog(
    api_key: str,
    now: datetime,
    state_path: Path,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Tuple[SourceEvent, ...]:
    """Refresh changed official text/poster inputs and atomically save facts."""

    snapshot_failure = None
    try:
        snapshot = await asyncio.to_thread(_load_snapshot, state_path)
    except MunicipalAgendaError as exc:
        snapshot = None
        snapshot_failure = exc
        if diagnostics is not None:
            diagnostics.append(
                source_error(
                    "MUNI-AGENDA",
                    "Agenda municipal",
                    exc,
                    stage="SNAPSHOT",
                )
            )
    try:
        page, _ = await asyncio.to_thread(
            _read_url, AGENDA_PAGE_URL, PAGE_HOSTS, PAGE_LIMIT_BYTES
        )
        local_now = now.astimezone(GUARDAMAR_TIMEZONE)
        try:
            page_text, text_month = extract_official_agenda_text(page)
        except MunicipalAgendaError as exc:
            if exc.diagnostic_code != "NO-TEXT-MONTH":
                raise
            page_text = ""
            text_month = ""
        try:
            poster_url = extract_poster_url(page)
        except MunicipalAgendaError:
            poster_url = ""
        page_hash = (
            hashlib.sha256(page_text.encode("utf-8")).hexdigest()
            if page_text
            else ""
        )
        old_sources = (
            snapshot.get("sources", {})
            if snapshot is not None
            and isinstance(snapshot.get("sources", {}), dict)
            else {}
        )
        old_events = snapshot["_events"] if snapshot is not None else ()
        transition_events = (
            _apply_reviewed_corrections(
                str(snapshot.get("poster_url", "")), old_events
            )
            if snapshot is not None
            else ()
        )
        old_text_events = tuple(
            event for event in old_events if "turismo_html" in event.sources
        )
        old_poster_events = tuple(
            event
            for event in old_events
            if "mupi" in event.sources
            and "turismo_html" not in event.sources
        )
        old_todo_events = tuple(
            event
            for event in old_events
            if "todo_cultura" in event.sources
            and not any(
                source in event.sources
                for source in ("turismo_html", "mupi", "mupi_reviewed")
            )
        )

        text_source = old_sources.get("turismo_html", {})
        if not page_text:
            text_events = old_text_events
        elif (
            old_text_events
            and isinstance(text_source, dict)
            and text_source.get("sha256") == page_hash
            and text_source.get("extractor_version") == TEXT_EXTRACTOR_VERSION
        ):
            text_events = old_text_events
        else:
            extracted_text = await extract_agenda_text_events(
                api_key, page_text
            )
            extracted_text = {**extracted_text, "month": text_month}
            text_events = normalize_extraction_candidates(
                extracted_text,
                text_month,
                "turismo_html",
                page_text,
            )
            if not text_events:
                raise MunicipalAgendaError(
                    "Official text agenda extraction was empty",
                    code="EMPTY-TEXT",
                    description="официальная текстовая программа не дала событий",
                )

        text_events = _enrich_admissions(
            text_events,
            _admissions(page.decode("utf-8", "replace"), local_now.date()),
            None,
        )

        poster_source = old_sources.get("mupi", {})
        poster_events = old_poster_events
        poster_hash = (
            str(poster_source.get("sha256", ""))
            if isinstance(poster_source, dict)
            else ""
        )
        poster_checked = False
        poster_failure: Optional[Exception] = None
        try:
            if not poster_url:
                raise MunicipalAgendaError(
                    "Official poster URL was not found",
                    code="NO-POSTER",
                    description="ссылка на официальную афишу не найдена",
                )
            if not (
                old_poster_events
                and isinstance(poster_source, dict)
                and poster_source.get("url") == poster_url
            ):
                poster, mime_type = await asyncio.to_thread(
                    _read_url, poster_url, POSTER_HOSTS, POSTER_LIMIT_BYTES
                )
                poster_hash = hashlib.sha256(poster).hexdigest()
                extracted = await extract_agenda_events(
                    api_key, poster, mime_type
                )
                first_poster_events = normalize_extraction_candidates(
                    extracted,
                    _poster_month(poster_url),
                    "mupi",
                )
                verified_result = await verify_agenda_poster_events(
                    api_key,
                    poster,
                    mime_type,
                )
                verified_result = {
                    **verified_result,
                    "month": _poster_month(poster_url),
                }
                verified_events = normalize_extraction_candidates(
                    verified_result,
                    _poster_month(poster_url),
                    "mupi",
                )
                poster_events = intersect_verified_poster_events(
                    first_poster_events,
                    verified_events,
                )
            poster_checked = True
        except (MunicipalAgendaError, GeminiError) as exc:
            poster_failure = exc
            if diagnostics is not None:
                failure = source_error(
                    "MUNI-AGENDA-MUPI",
                    "Муниципальная афиша MUPI",
                    exc,
                    stage="OPTIONAL",
                )
                diagnostics.append(
                    SourceDiagnostic(
                        failure.code,
                        failure.source,
                        (
                            f"{failure.description}; использованы только "
                            "проверенные текстовые данные"
                        ),
                    )
                )

        todo_source = old_sources.get("todo_cultura", {})
        todo_horizon = local_now.date() + timedelta(days=44)
        prior_todo_events = tuple(
            event
            for event in old_todo_events
            if event.end_date >= local_now.date()
            and event.start_date <= todo_horizon
        )
        todo_events = prior_todo_events
        todo_window = None
        try:
            todo_window = await fetch_program_window(
                local_now.date(),
                todo_source if isinstance(todo_source, dict) else None,
            )
            for todo_program in todo_window.programs:
                todo_result = await extract_agenda_text_events(
                    api_key,
                    todo_program.text,
                )
                todo_month = (
                    todo_program.dates[0].strftime("%Y-%m")
                    if todo_program.dates
                    else local_now.strftime("%Y-%m")
                )
                todo_result = {**todo_result, "month": todo_month}
                new_todo_events = normalize_extraction_candidates(
                    todo_result,
                    todo_month,
                    "todo_cultura",
                    todo_program.text,
                )
                new_todo_events = _enrich_admissions(
                    new_todo_events,
                    todo_program.admissions,
                )
                for target_date in todo_program.dates:
                    new_todo_events = _enrich_todo_participation(
                        new_todo_events,
                        todo_program.participation,
                        target_date,
                    )
                if not new_todo_events:
                    continue
                refreshed_dates = set(todo_program.dates)
                retained = tuple(
                    event
                    for event in todo_events
                    if not any(
                        event.start_date <= target <= event.end_date
                        and candidate.start_date <= target <= candidate.end_date
                        and _word_overlap(
                            event.title_es, candidate.title_es
                        ) >= 0.5
                        for target in refreshed_dates
                        for candidate in new_todo_events
                    )
                )
                todo_events = merge_text_and_poster_events(
                    retained,
                    new_todo_events,
                )
        except (TodoCulturaError, GeminiError, MunicipalAgendaError) as exc:
            # Do not advance the incremental cursor or processed dates unless
            # every selected section was normalized successfully.
            todo_window = None
            todo_events = prior_todo_events
            if old_todo_events:
                LOGGER.warning("Todo Cultura supplement unavailable: %s", exc)
            else:
                LOGGER.info("Todo Cultura supplement unavailable: %s", exc)
            if diagnostics is not None and old_todo_events:
                failure = source_error(
                    "TODO-CULTURA",
                    "Todo Cultura Vega Baja",
                    exc,
                    stage="SUPPLEMENTAL",
                )
                diagnostics.append(SourceDiagnostic(
                    failure.code,
                    failure.source,
                    (
                        f"{failure.description}; использован предыдущий "
                        "дополнительный снимок"
                    ),
                ))

        events = merge_text_and_poster_events(text_events, poster_events)
        events = merge_text_and_poster_events(events, todo_events)
        if not events:
            if isinstance(poster_failure, GeminiError):
                raise MunicipalAgendaError(
                    "Municipal poster extraction failed",
                    code=poster_failure.diagnostic_code,
                    status=poster_failure.server_status,
                    description=poster_failure.safe_description,
                ) from poster_failure
            if isinstance(poster_failure, MunicipalAgendaError):
                raise poster_failure
            raise MunicipalAgendaError(
                "Municipal agenda extraction was empty",
                code="EMPTY",
                description="официальные источники не дали мероприятий",
            )
        local_month = local_now.strftime("%Y-%m")
        source_month = (
            _poster_month(poster_url) if poster_url else text_month
        )
        if source_month > local_month:
            events = _merge_transition_events(
                events,
                transition_events,
                local_now.date(),
            )
        source_state = {
            "turismo_html": {
                "url": AGENDA_PAGE_URL,
                "sha256": page_hash,
                "month": text_month or None,
                "extractor_version": TEXT_EXTRACTOR_VERSION,
                "checked_at": now.isoformat(),
            },
        }
        if poster_checked:
            source_state["mupi"] = {
                "url": poster_url,
                "sha256": poster_hash,
                "month": _poster_month(poster_url),
                "checked_at": now.isoformat(),
            }
        elif isinstance(poster_source, dict) and poster_source:
            source_state["mupi"] = poster_source
        if todo_window is not None:
            evidence = [
                detail
                for program in todo_window.programs
                for detail in program.participation
            ]
            admission_evidence = [
                admission
                for program in todo_window.programs
                for admission in program.admissions
                if admission.evidence
            ]
            source_state["todo_cultura"] = {
                **todo_window.source_state,
                "checked_at": now.isoformat(),
                "participation_evidence": [
                    {
                        "title_hint": detail.title_hint,
                        "evidence": detail.evidence,
                    }
                    for detail in evidence[:12]
                ],
                "admission_evidence": [
                    {
                        "title_hint": detail.title_hint,
                        "evidence": detail.evidence,
                    }
                    for detail in admission_evidence[:20]
                ],
            }
        elif isinstance(todo_source, dict) and todo_source:
            source_state["todo_cultura"] = todo_source
        try:
            await asyncio.to_thread(
                _write_snapshot,
                state_path,
                _snapshot_data(
                    poster_url,
                    poster_hash,
                    now,
                    events,
                    source_state,
                ),
            )
        except OSError as exc:
            if diagnostics is not None:
                diagnostics.append(source_error(
                    "MUNI-AGENDA",
                    "Agenda municipal",
                    MunicipalAgendaError(
                        "Municipal snapshot could not be written",
                        code="WRITE",
                        description="не удалось сохранить локальный каталог",
                    ),
                    stage="SNAPSHOT",
                ))
    except (MunicipalAgendaError, GeminiError) as exc:
        if snapshot is None:
            if snapshot_failure is not None:
                raise MunicipalAgendaError(
                    "Municipal agenda recovery failed",
                    code="RECOVERY",
                    description=(
                        "локальный снимок повреждён, а официальный источник "
                        "недоступен"
                    ),
                ) from exc
            if isinstance(exc, GeminiError):
                raise MunicipalAgendaError(
                    "Municipal poster extraction failed",
                    code=exc.diagnostic_code,
                    status=exc.server_status,
                    description=exc.safe_description,
                ) from exc
            raise
        if diagnostics is not None:
            failure = source_error(
                "MUNI-AGENDA",
                "Agenda municipal",
                exc,
                stage="FALLBACK",
            )
            diagnostics.append(
                SourceDiagnostic(
                    failure.code,
                    failure.source,
                    f"{failure.description}; использован локальный снимок",
                )
            )
        events = snapshot["_events"]
        return tuple(events)
    return tuple(events)


async def _cached_current_events(
    now: datetime,
    state_path: Path,
) -> Tuple[SourceEvent, ...]:
    """Read current events from the last atomic catalog without network I/O."""

    snapshot = await asyncio.to_thread(_load_snapshot, state_path)
    if snapshot is None:
        raise MunicipalAgendaError(
            "Municipal agenda catalog does not exist",
            code="NO-SNAPSHOT",
            description="локальный каталог мероприятий ещё не создан",
        )
    events = snapshot["_events"]
    poster_url = str(snapshot.get("poster_url", ""))
    events = _apply_reviewed_corrections(poster_url, events)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    events = _apply_reviewed_daily_schedules(events, local_day)
    active = [
        event
        for event in events
        if event.start_date <= local_day <= event.end_date
    ]
    active.sort(
        key=lambda event: (
            event.start_date != event.end_date,
            event.start_time or "99:99",
            event.title_es.casefold(),
        )
    )
    return tuple(active)


async def _current_events(
    api_key: str,
    now: datetime,
    state_path: Path,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Tuple[SourceEvent, ...]:
    """Compatibility wrapper for an explicit catalog refresh."""

    return await refresh_municipal_catalog(
        api_key, now, state_path, diagnostics
    )


async def fetch_today_municipal_events(
    now: datetime,
    api_key: str,
    state_path: Path,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
    translation_cache_path: Optional[Path] = None,
) -> Tuple[Event, ...]:
    """Return today's translated events from the local catalog."""

    if not api_key and translation_cache_path is None:
        raise MunicipalAgendaError(
            "Gemini key is required for municipal agenda",
            code="CONFIG",
            description="не настроен ключ Gemini для муниципальной афиши",
        )
    source_events = await _cached_current_events(now, state_path)
    if not source_events:
        return ()
    translated_events = []
    if translation_cache_path is not None:
        translated_events = [
            (
                source,
                cached_title(
                    translation_cache_path,
                    "municipal_agenda",
                    source.title_es,
                ),
            )
            for source in source_events
        ]
    else:
        try:
            titles = await translate_event_titles(
                api_key, [event.title_es for event in source_events]
            )
            translated_events = list(zip(source_events, titles))
        except GeminiError as batch_error:
            failed_translations = 0
            for source in source_events[
                :MAX_INDIVIDUAL_TRANSLATION_RECOVERY
            ]:
                try:
                    title = (await translate_event_titles(
                        api_key, [source.title_es]
                    ))[0]
                except GeminiError:
                    failed_translations += 1
                    continue
                translated_events.append((source, title))
            failed_translations += max(
                0,
                len(source_events) - MAX_INDIVIDUAL_TRANSLATION_RECOVERY,
            )
            if failed_translations and diagnostics is not None:
                diagnostics.append(SourceDiagnostic(
                    "MUNI-AGENDA-TRANSLATION-PARTIAL",
                    "Agenda municipal",
                    (
                        "не удалось перевести событий: "
                        f"{failed_translations}; они исключены из "
                        "предпросмотра"
                    ),
                ))
            if not translated_events:
                raise MunicipalAgendaError(
                    "Event translation failed",
                    code=batch_error.diagnostic_code,
                    status=batch_error.server_status,
                    description=batch_error.safe_description,
                ) from batch_error
    result = []
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for source, title in translated_events:
        starts_at = None
        ends_at = None
        if source.start_time:
            hour, minute = (int(part) for part in source.start_time.split(":"))
            starts_at = datetime.combine(
                local_day,
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=GUARDAMAR_TIMEZONE,
            )
            if source.end_time:
                end_hour, end_minute = (
                    int(part) for part in source.end_time.split(":")
                )
                ends_at = datetime.combine(
                    local_day,
                    datetime.min.time().replace(
                        hour=end_hour,
                        minute=end_minute,
                    ),
                    tzinfo=GUARDAMAR_TIMEZONE,
                )
                if ends_at <= starts_at:
                    ends_at += timedelta(days=1)
        result.append(
            Event(
                title=title,
                starts_at=starts_at,
                ends_at=ends_at,
                place=source.place,
                active_until=source.end_date,
                category=source.category,
                ticket_price_cents=source.ticket_price_cents,
                ticket_url=source.ticket_url,
                participation_note=source.participation_note,
                registration_contact=source.registration_contact,
                capacity_limited=source.capacity_limited,
                is_final_day=(
                    source.start_date != source.end_date
                    and local_day == source.end_date
                ),
            )
        )
    return tuple(result)


async def municipal_translation_items(
    now: datetime,
    state_path: Path,
) -> Tuple[Tuple[str, str], ...]:
    """Return source identities and exact titles from the local catalog."""

    events = await _cached_current_events(now, state_path)
    return tuple(("municipal_agenda", event.title_es) for event in events)
