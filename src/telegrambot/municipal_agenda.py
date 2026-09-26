"""Monthly official municipal agenda poster with a small local snapshot."""

from __future__ import annotations

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
    extract_guardamar_standalone_events,
    translate_event_titles,
    verify_agenda_poster_events,
)
from .event_translations import (
    cached_title, cached_translation, reviewed_translation, spanish_fallback,
)
from .event_urls import normalize_registration_url, normalize_ticket_url
from .event_places import canonical_event_place, event_place_is_map_safe
from .event_facts import ROUTE_DIFFICULTY_PREFIX
from .facebook import FacebookError, FacebookPost, fetch_facebook_posts
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
    TodoCulturaSummary,
    _all_mentioned_dates,
    _admissions,
    _event_time,
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
TEXT_EXTRACTOR_VERSION = 4
FACEBOOK_SOURCE_PREFIX = "facebook:"
MAX_FACEBOOK_POSTS = 12
MAX_TODO_ROW_RECOVERIES = 8
_SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
TURISMO_POSTS_URL = (
    "https://guardamarturismo.com/wp-json/wp/v2/posts"
    "?search=Fiestas%20del%20Campo&per_page=10"
    "&_fields=id,date,modified,link,title,content"
)
TURISMO_PROGRAMME_INDEX_URL = (
    "https://guardamarturismo.com/wp-json/wp/v2/posts"
    "?per_page=20&orderby=modified&order=desc"
    "&_fields=id,modified,link,title,excerpt"
)
TURISMO_PROGRAMME_TEXT_SOURCE = "turismo_programme_text"
MAX_TURISMO_PROGRAMME_ARTICLES = 3
TURISMO_PROGRAMME_HORIZON_DAYS = 44
TURISMO_PROGRAMME_PAST_GRACE_DAYS = 14
CULTURA_GUARDAMAR_PAGE_URL = "https://www.facebook.com/culturaguardamar"
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")

_SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "setembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_EXHIBITION_DATE = re.compile(
    r"\b(?:(?:Hasta\s+el\s+(?P<until_day>\d{1,2})\s+de\s+"
    r"(?P<until_month>[a-záéíóúñ]+))|"
    r"(?:Del\s+(?P<start_day>\d{1,2})(?:\s+de\s+"
    r"(?P<start_month>[a-záéíóúñ]+))?\s+al\s+"
    r"(?P<end_day>\d{1,2})\s+de\s+"
    r"(?P<end_month>[a-záéíóúñ]+)))\s*\.",
    re.IGNORECASE,
)
_EXHIBITION_OPENING = re.compile(
    r"\bInauguraci[oó]n\s*:\s*"
    r"(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
    r",?\s+)?"
    r"(?P<day>\d{1,2})\s+de\s+(?P<month>[a-záéíóúñ]+)"
    r"(?:\s+de\s+(?P<year>\d{4}))?\s+a\s+las\s+"
    r"(?P<hour>\d{1,2})[:.](?P<minute>\d{2})\s*h?\.?",
    re.IGNORECASE,
)


_CINEMA_SECTION = re.compile(
    r"\bCINE\b(?P<body>.*?)(?=\b(?:EXPOSICIONES|TEATRO|CONCIERTO|"
    r"FIESTAS|TALLERES|BALL\s+D[’']ESTIU|VISITAS\s+GUIADAS)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_CINEMA_ROW = re.compile(
    r"\b(?P<weekday>lunes|martes|mi[eé]rcoles|jueves|viernes|"
    r"s[aá]bado|domingo|dilluns|dimarts|dimecres|dijous|divendres|"
    r"dissabte|diumenge),?\s+(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>[a-záéíóú]+)\s+a\s+(?:las|les|la)\s+"
    r"(?P<hour>\d{1,2})[:.](?P<minute>\d{2})\s*h\.?",
    re.IGNORECASE,
)
_CINEMA_IDENTITY = re.compile(
    r"(?P<place>[^.]{3,120})\.\s+"
    r"(?P<title>[^()]{2,120}?)\s*\([^()]{3,180}\)",
    re.IGNORECASE,
)
_CINEMA_GENRES = {
    "drama": "Драма",
    "drama-comedia": "Драма-комедия",
    "tragicomedia": "Трагикомедия",
    "comedia": "Комедия",
    "documental": "Документальный фильм",
}
_CINEMA_WEEKDAYS = {
    "lunes": 0,
    "dilluns": 0,
    "martes": 1,
    "dimarts": 1,
    "miércoles": 2,
    "miercoles": 2,
    "dimecres": 2,
    "jueves": 3,
    "dijous": 3,
    "viernes": 4,
    "divendres": 4,
    "sábado": 5,
    "sabado": 5,
    "dissabte": 5,
    "domingo": 6,
    "diumenge": 6,
}
_SYNOPSIS_MARKER = re.compile(
    r"\bLa\s+sinopsis\b[^:\n]{0,200}\bes\s+(?:la|el)\s+siguiente\s*:\s*(.+)$",
    re.IGNORECASE,
)


def _detail_label(value: str) -> str:
    return _CINEMA_GENRES.get(value.casefold(), value)


def _sanitize_generic_agenda_ticket_url(
    event: "SourceEvent",
) -> "SourceEvent":
    """Drop navigation-only Agenda URLs; keep real ticket providers intact."""

    if event.ticket_url is None:
        return event
    normalized = normalize_ticket_url(event.ticket_url)
    if normalized is None:
        return replace(event, ticket_url=None)
    parsed = urllib.parse.urlparse(normalized)
    if (
        parsed.hostname in {
            "agendaguardamar.com",
            "www.agendaguardamar.com",
        }
        and not parsed.path.startswith(("/entradas/", "/espectaculo/"))
    ):
        return replace(event, ticket_url=None)
    return replace(event, ticket_url=normalized)


def _cinema_title(value: str) -> str:
    """Mark verified cinema while preserving the established Monday label."""

    value = " ".join(value.split()).strip()
    folded = value.casefold()
    monday_prefix = "cine de los lunes: "
    if folded.startswith(monday_prefix):
        film = spanish_fallback(value[len(monday_prefix):].strip())
        return f"Кино по понедельникам: «{film}»"
    if folded.startswith("кино по понедельникам:"):
        film = value.partition(":")[2].strip()
        if film.startswith("«") and film.endswith("»"):
            film = film[1:-1].strip()
        if film:
            return f"Кино по понедельникам: «{film}»"
    for prefix in ("cine: ", "кино: "):
        if folded.startswith(prefix):
            return "🎬 " + value[len(prefix):].strip()
    return "🎬 " + value


def extract_official_cinema(
    programme: str, expected_month: str,
) -> Tuple["SourceEvent", ...]:
    """Read every explicit row from the already fetched official CINE section."""

    section = _CINEMA_SECTION.search(programme)
    if section is None:
        return ()
    try:
        year, base_month = map(int, expected_month.split("-"))
        date(year, base_month, 1)
    except ValueError:
        return ()
    markers = list(_CINEMA_ROW.finditer(section.group("body")))
    events = []
    for index, marker in enumerate(markers):
        month = _SPANISH_MONTHS.get(marker.group("month").casefold())
        weekday = _CINEMA_WEEKDAYS.get(marker.group("weekday").casefold())
        if month is None or weekday is None:
            continue
        event_year = year + (month < base_month)
        try:
            event_day = date(event_year, month, int(marker.group("day")))
            starts_at = datetime(
                event_year, month, event_day.day,
                int(marker.group("hour")), int(marker.group("minute")),
            )
        except ValueError:
            continue
        if event_day.weekday() != weekday or len(events) == MAX_EVENTS:
            continue
        window_start, window_end = _month_window(expected_month)
        if not window_start <= event_day <= window_end:
            continue
        body = section.group("body")[marker.end(): (
            markers[index + 1].start() if index + 1 < len(markers)
            else len(section.group("body"))
        )]
        identity = _CINEMA_IDENTITY.search(body)
        if identity is None:
            continue
        place = canonical_event_place(" ".join(identity.group("place").split()))
        title = " ".join(identity.group("title").split()).strip(" .")
        attributes = body[identity.end():]
        age_match = re.search(r"\+\s*(\d{1,2})\s*/", attributes)
        genre_match = re.search(
            r"(?:\+\s*\d{1,2}\s*/\s*)?"
            r"([A-Za-zÁÉÍÓÚáéíóú -]{2,50})\s*/\s*\d{1,3}\s*min\b",
            attributes,
        )
        duration_match = re.search(r"\b(\d{1,3})\s*min\b", attributes)
        duration = int(duration_match.group(1)) if duration_match else None
        if (
            not place
            or not event_place_is_map_safe(place)
            or not 1 <= len(title) <= 90
            or duration is not None and not 1 <= duration <= 720
        ):
            continue
        admission = attributes
        free_capacity = re.search(
            r"\bEntrada\s+libre\s+hasta\s+completar\s+aforo\b",
            admission, re.IGNORECASE,
        ) is not None
        free_invitation = re.search(
            r"\bEntrada\s+(?:libre|gratuita)\s+con\s+invitaci[oó]n\b",
            admission, re.IGNORECASE,
        ) is not None
        price_match = re.search(
            r"\bPrecio\s*:\s*(\d{1,3})(?:[,.](\d{1,2}))?\s*€",
            admission, re.IGNORECASE,
        )
        price = None
        if free_capacity or free_invitation:
            price = 0
        elif price_match:
            price = (
                int(price_match.group(1)) * 100
                + int((price_match.group(2) or "0").ljust(2, "0"))
            )
        monday_series = (
            weekday == 0 and "biblioteca" in place.casefold()
        )
        events.append(SourceEvent(
            title_es=(
                f"Cine de los Lunes: {title}"
                if monday_series else f"Cine: {title}"
            ),
            start_date=event_day,
            end_date=event_day,
            start_time=starts_at.strftime("%H:%M"),
            end_time=None,
            place=place,
            category="event",
            sources=("turismo_html", "turismo_cinema"),
            ticket_price_cents=price,
            capacity_limited=free_capacity,
            duration_minutes=duration,
            audience_label=(
                f"{int(age_match.group(1))}+" if age_match else None
            ),
            details=((" ".join(genre_match.group(1).split()),)
                     if genre_match else ()),
            access_note="до заполнения зала" if free_capacity else None,
        ))
    return tuple(events)


def _month_date(year: int, month_name: str, day: str) -> Optional[date]:
    month = _SPANISH_MONTHS.get(month_name.casefold())
    if month is None:
        return None
    try:
        return date(year, month, int(day))
    except ValueError:
        return None


def extract_official_exhibitions(
    programme: str,
    expected_month: str,
) -> Tuple["SourceEvent", ...]:
    """Recover explicit exhibition ranges from the official text agenda.

    The official page is compact and stable enough for a deterministic
    fallback.  This keeps current exhibitions when the optional structured
    reader omits a block or returns only invalid candidates.
    """

    try:
        agenda_month = date.fromisoformat(f"{expected_month}-01")
    except ValueError:
        return ()
    section_match = re.search(
        r"\bEXPOSICIONES\b(?P<body>.*?)(?=\bTEATRO\b|\bCINE\b|"
        r"\bCONCIERTO\b|\bFIESTAS\b|\bTALLERES\b|"
        r"\bBALL\s+D[’']ESTIU\b|\bVISITAS\s+GUIADAS\b|$)",
        programme,
        re.IGNORECASE | re.DOTALL,
    )
    if section_match is None:
        return ()
    section = section_match.group("body")
    markers = list(_EXHIBITION_DATE.finditer(section))
    events = []
    for index, marker in enumerate(markers):
        block_end = (
            markers[index + 1].start()
            if index + 1 < len(markers)
            else len(section)
        )
        block = " ".join(section[marker.end():block_end].split())
        identity = re.match(
            r"(?P<place>[^.]{3,160})\.\s+"
            r"(?P<title>[^.]{2,120}?)\s+"
            r"(?:Exposición|Exposicion|Muestra)\b",
            block,
            re.IGNORECASE,
        )
        if identity is None:
            continue
        if marker.group("until_day"):
            until_month = marker.group("until_month")
            until_month_number = _SPANISH_MONTHS.get(
                until_month.casefold()
            )
            until_year = agenda_month.year + (
                1
                if until_month_number is not None
                and until_month_number < agenda_month.month
                else 0
            )
            end_date = _month_date(
                until_year,
                until_month,
                marker.group("until_day"),
            )
            start_date = agenda_month
        else:
            end_month = marker.group("end_month")
            start_month = marker.group("start_month") or end_month
            end_month_number = _SPANISH_MONTHS.get(end_month.casefold())
            start_month_number = _SPANISH_MONTHS.get(start_month.casefold())
            end_year = agenda_month.year + (
                1
                if end_month_number is not None
                and end_month_number < agenda_month.month
                else 0
            )
            start_year = agenda_month.year + (
                1
                if start_month_number is not None
                and start_month_number < agenda_month.month
                else 0
            )
            start_date = _month_date(
                start_year, start_month, marker.group("start_day")
            )
            end_date = _month_date(
                end_year, end_month, marker.group("end_day")
            )
        if (
            start_date is None
            or end_date is None
            or start_date > end_date
            or (end_date - start_date).days > 62
            or end_date < agenda_month
            or start_date > agenda_month + timedelta(days=62)
        ):
            continue
        title_es = " ".join(identity.group("title").split())
        place = canonical_event_place(identity.group("place"))
        events.append(SourceEvent(
            title_es=title_es,
            start_date=start_date,
            end_date=end_date,
            start_time=None,
            end_time=None,
            place=place,
            category="exhibition",
            sources=("turismo_html",),
        ))
        opening = _EXHIBITION_OPENING.search(block)
        if opening is None:
            continue
        opening_month = _SPANISH_MONTHS.get(opening.group("month").casefold())
        if opening_month is None:
            continue
        opening_year = (
            int(opening.group("year"))
            if opening.group("year")
            else agenda_month.year + (1 if opening_month < agenda_month.month else 0)
        )
        try:
            opening_day = date(
                opening_year, opening_month, int(opening.group("day"))
            )
            opening_time = datetime(
                opening_year,
                opening_month,
                opening_day.day,
                int(opening.group("hour")),
                int(opening.group("minute")),
            ).strftime("%H:%M")
        except ValueError:
            continue
        if not start_date <= opening_day <= end_date:
            continue
        events.append(SourceEvent(
            title_es=f"Inauguración de la exposición {title_es}",
            start_date=opening_day,
            end_date=opening_day,
            start_time=opening_time,
            end_time=None,
            place=place,
            category="exhibition_opening",
            sources=("turismo_html", "turismo_exhibition_opening"),
        ))
    return tuple(events)


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
    registration_url: Optional[str] = None
    capacity_limited: bool = False
    admission_evidence: Optional[str] = None
    teaser_es: Optional[str] = None
    duration_minutes: Optional[int] = None
    audience_label: Optional[str] = None
    details: Tuple[str, ...] = ()
    place_query: Optional[str] = None
    meeting_point: Optional[str] = None
    schedule_note: Optional[str] = None
    access_note: Optional[str] = None
    programme_title: Optional[str] = None
    programme_order: Optional[int] = None
    session_source_key: Optional[str] = None
    session_parent_title_es: Optional[str] = None
    image_url: Optional[str] = None


_SESSION_MARKER = (
    r"(?:(?:primer(?:a|o)?|segund(?:a|o|0)|tercer(?:a|o)?|cuart[oa]|"
    r"quint[oa]|sext[oa]|s[eé]ptim[oa]|octav[oa]|noven[oa]|d[eé]cim[oa]|"
    r"[1-9]\d?(?:[.ºª]|er|ra)?)\s+"
    r"(?:turno|sesi[oó]n|pase)|"
    r"(?:turno|sesi[oó]n|pase)\s*"
    r"(?:n[úu]m(?:ero)?\.?\s*)?[1-9]\d?)"
)
_SESSION_PREFIX_TITLE = re.compile(
    rf"^\s*{_SESSION_MARKER}\b"
    r"\s*(?:[-:–—]\s*)?(?:para\s+|de\s+)?"
    r"(?P<base>.+?)\s*$",
    re.IGNORECASE,
)
_SESSION_SUFFIX_TITLE = re.compile(
    rf"^\s*(?P<base>.+?)\s*"
    rf"(?:[\(\[]\s*)?{_SESSION_MARKER}\b\s*(?:[\)\]]\s*)?$",
    re.IGNORECASE,
)
_TODO_ROW_TITLE_LINE = re.compile(
    r"^\s*[–—-]\s*(?:de\s+)?"
    r"\d{1,2}(?:[,:.]\d{2})?"
    r"(?:\s*(?:a|[-–—])\s*\d{1,2}(?:[,:.]\d{2})?)?"
    r"\s*(?:h(?:oras?)?\.?)?\s*:\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)

def _session_base_title(title: str) -> Optional[str]:
    """Strip only an explicit numbered session marker from a source title."""

    value = " ".join(title.split())
    match = _SESSION_PREFIX_TITLE.fullmatch(value)
    if match is None:
        match = _SESSION_SUFFIX_TITLE.fullmatch(value)
    if match is None:
        return None
    base = match.group("base").strip(" .,:;–—-")
    if not 5 <= len(base) <= 180:
        return None
    return base


def _session_base_key(value: str) -> str:
    """Normalize source identity punctuation; never fuzzy-match activities."""

    value = html.unescape(value).casefold()
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"')
    value = re.sub(r"[‐‑‒–—-]+", "-", value)
    return " ".join(value.split()).strip(" .,:;-")


def _todo_session_parent_from_row(row: str) -> Optional[str]:
    """Read an explicit session relationship from the raw Todo row only."""

    lines = [" ".join(line.split()) for line in row.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    title_match = _TODO_ROW_TITLE_LINE.fullmatch(lines[1])
    if title_match is None:
        return None
    return _session_base_title(title_match.group("title"))


def _match_todo_rows(
    rows: Tuple[Tuple[date, str, str], ...],
    events: Tuple[SourceEvent, ...],
) -> Tuple[Tuple[Tuple[date, str, str], Optional[int]], ...]:
    """Bind each raw row to at most one verified occurrence by date/time/title."""

    available = set(range(len(events)))
    matched = []
    for row_info in rows:
        day, start_time, row = row_info
        candidates = sorted(
            (
                (_word_overlap(event.title_es, row), index)
                for index, event in enumerate(events)
                if index in available
                and event.start_date == day
                and event.start_time == start_time
            ),
            reverse=True,
        )
        event_index = (
            candidates[0][1]
            if candidates and candidates[0][0] >= 0.5
            else None
        )
        if event_index is not None:
            available.remove(event_index)
        matched.append((row_info, event_index))
    return tuple(matched)


def _strict_session_row_matches(
    rows: Tuple[Tuple[date, str, str], ...],
    events: Tuple[SourceEvent, ...],
) -> Tuple[Tuple[Tuple[date, str, str], Optional[int]], ...]:
    """Fail open unless one occurrence uniquely matches each session row."""

    available = set(range(len(events)))
    matched = []
    for row_info in rows:
        day, start_time, row = row_info
        candidates = [
            index
            for index, event in enumerate(events)
            if index in available
            and event.start_date == day
            and event.start_time == start_time
            and _word_overlap(event.title_es, row) >= 0.5
        ]
        event_index = candidates[0] if len(candidates) == 1 else None
        if event_index is not None:
            available.remove(event_index)
        matched.append((row_info, event_index))
    return tuple(matched)


def _session_display_title(
    events: Tuple[SourceEvent, ...],
    indexes: List[int],
    raw_parent: str,
) -> str:
    """Choose one pre-translation display title after identity is already fixed."""

    candidates = []
    for index in indexes:
        event_title = events[index].title_es
        cleaned = _session_base_title(event_title) or event_title
        if (
            len(_normalized_words(cleaned) & _normalized_words(raw_parent)) >= 2
            and _word_overlap(cleaned, raw_parent) >= 0.35
        ):
            candidates.append(cleaned)
    if not candidates:
        candidates = [events[index].title_es for index in indexes]
    return min(candidates, key=lambda value: (len(value), value.casefold()))


def _annotate_todo_source_sessions(
    events: Tuple[SourceEvent, ...],
    rows: Tuple[Tuple[date, str, str], ...],
) -> Tuple[SourceEvent, ...]:
    """Persist relationships proven by raw Todo rows before any source merge."""

    row_matches = _strict_session_row_matches(rows, events)
    refreshed_indexes = {
        event_index
        for _, event_index in row_matches
        if event_index is not None
    }
    annotated = [
        replace(
            event,
            session_source_key=None,
            session_parent_title_es=None,
        )
        if index in refreshed_indexes
        else event
        for index, event in enumerate(events)
    ]

    families: Dict[tuple, List[Tuple[int, str]]] = {}
    for (day, start_time, row), event_index in row_matches:
        if event_index is None:
            continue
        event = events[event_index]
        if event.programme_title is not None:
            continue
        raw_parent = _todo_session_parent_from_row(row)
        if raw_parent is None:
            continue
        shared_words = (
            _normalized_words(event.title_es)
            & _normalized_words(raw_parent)
        )
        if (
            len(shared_words) < 2
            or _word_overlap(event.title_es, raw_parent) < 0.35
        ):
            continue
        key = (
            day,
            event.category,
            _session_base_key(raw_parent),
        )
        families.setdefault(key, []).append((event_index, raw_parent))

    for key, members in families.items():
        indexes = [index for index, _ in members]
        if len(indexes) < 2:
            continue
        start_times = [events[index].start_time for index in indexes]
        if (
            any(value is None for value in start_times)
            or len(set(start_times)) != len(start_times)
        ):
            continue
        known_places = {
            canonical_event_place(events[index].place).casefold()
            for index in indexes
            if events[index].place is not None
        }
        if len(known_places) > 1:
            continue

        raw_parent = members[0][1]
        source_key = "todo_cultura:" + hashlib.sha256(
            key[2].encode("utf-8")
        ).hexdigest()
        parent_title = _session_display_title(events, indexes, raw_parent)
        for index in indexes:
            annotated[index] = replace(
                events[index],
                session_source_key=source_key,
                session_parent_title_es=parent_title,
            )
    return tuple(annotated)


def _session_source_plan(
    events: Tuple[SourceEvent, ...],
) -> Tuple[Tuple[str, Optional[str]], ...]:
    """Build translation/display groups from source relationships fixed upstream."""

    plan: List[Tuple[str, Optional[str]]] = [
        (event.title_es, None) for event in events
    ]
    families: Dict[tuple, List[int]] = {}
    for index, event in enumerate(events):
        if (
            event.session_source_key is None
            or event.session_parent_title_es is None
            or event.programme_title is not None
            or event.start_date != event.end_date
            or event.start_time is None
        ):
            continue
        key = (
            event.start_date,
            event.category,
            event.session_source_key,
        )
        families.setdefault(key, []).append(index)

    for key, indexes in families.items():
        if len(indexes) < 2:
            continue
        start_times = [events[index].start_time for index in indexes]
        if len(set(start_times)) != len(start_times):
            continue
        group_key = "session:" + "|".join((
            key[0].isoformat(),
            key[1],
            key[2],
        ))
        parent_titles = {
            event.session_parent_title_es
            for event in (events[index] for index in indexes)
            if event.session_parent_title_es is not None
        }
        if not parent_titles:
            continue
        parent_title = min(
            parent_titles,
            key=lambda value: (len(value), value.casefold()),
        )
        for index in indexes:
            plan[index] = (parent_title, group_key)
    return tuple(plan)

def _display_ticket_price(
    source: SourceEvent,
) -> Tuple[Optional[int], bool]:
    """Return a fixed price or a safe lower bound for explicit tariff sets."""

    if source.ticket_price_cents is None or not source.admission_evidence:
        return source.ticket_price_cents, False
    if source.ticket_price_cents == 0:
        return 0, False
    prices = {
        int(match.group(1)) * 100
        + int((match.group(2) or "0").ljust(2, "0"))
        for match in re.finditer(
            r"\b(\d{1,4})(?:[,.](\d{1,2}))?\s*(?:€|euros?)\b",
            source.admission_evidence,
            re.IGNORECASE,
        )
    }
    if len(prices) > 1:
        return min(prices), True
    return source.ticket_price_cents, False


def _display_ticket_price_cents(source: SourceEvent) -> Optional[int]:
    """Backward-compatible scalar accessor for tests and callers."""

    return _display_ticket_price(source)[0]


_CAMPO_PROGRAMME_ORDER = {
    "Disparo de cohetes": 10,
    "Entrada de bandas": 20,
    "Desfile Multicolor": 30,
    "Fuegos artificiales": 40,
    "Fiesta del Vino": 50,
    "Actuaciones nocturnas de las Fiestas del Campo": 60,
    "Chocolate con mona de madrugada": 10,
    "Despertà": 20,
    "Charanga": 30,
}


def _programme_source_metadata(
    event: SourceEvent,
    programme_title: Optional[str] = None,
    image_url: Optional[str] = None,
) -> SourceEvent:
    """Keep the narrow Campo article's programme identity at its adapter."""

    if (
        "turismo_programme" not in event.sources
        or event.title_es not in _CAMPO_PROGRAMME_ORDER
    ):
        return event
    return replace(
        event,
        programme_title=(
            event.programme_title or programme_title
            or "Fiestas del Campo — Campo de Guardamar"
        ),
        programme_order=(
            event.programme_order if event.programme_order is not None
            else _CAMPO_PROGRAMME_ORDER.get(event.title_es)
        ),
        image_url=event.image_url or image_url,
    )


def _normalized_turismo_image_url(value: Any) -> Optional[str]:
    """Accept only one official event-specific Turismo upload URL."""

    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in PAGE_HOSTS
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.casefold().startswith("/wp-content/uploads/")
        or not parsed.path.casefold().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ):
        return None
    return urllib.parse.urlunsplit(parsed._replace(query="", fragment=""))


def _explicit_venue_and_address(event: SourceEvent) -> SourceEvent:
    """Separate an address from the venue explicitly named in its source row."""

    if not event.place or not event_place_is_map_safe(event.place):
        return event
    if not re.match(r"^(?:calle|carrer|avenida|av\.)\b", event.place, re.I):
        return event
    venue = re.search(r"\bCentro Social Juvenil\b", event.title_es, re.I)
    if venue is None:
        return event
    return replace(
        event, place=venue.group(0), place_query=event.place_query or event.place
    )


def _is_contentless_generic_event(event: SourceEvent) -> bool:
    """Reject only institutional placeholders with no event-specific fact."""

    words = _normalized_words(event.title_es)
    generic_words = {
        "actividad", "actividades", "apertura", "centro", "csj", "del",
        "cultural", "culturales", "juvenil", "jovenes", "programa",
        "programacion", "social",
    }
    if not words or words.isdisjoint({"actividad", "actividades", "apertura"}):
        return False
    if not words <= generic_words:
        return False
    detail = " ".join((event.participation_note or "").split()).casefold()
    specific_participation = any(term in detail for term in (
        "настольн", "пинг-понг", "аэрохоккей", "игровой автомат",
    ))
    return not (
        event.teaser_es
        or specific_participation
        or event.ticket_price_cents is not None
        or event.ticket_url
        or event.admission_evidence
    )


_ROUTINE_YOUTH_CENTRE_TITLES = frozenset({
    "actividades del centro social juvenil",
    "actividades del centro social juvenil (csj)",
})


def _is_editorially_hidden_daily_event(event: SourceEvent) -> bool:
    """Keep the explicitly excluded routine opening out of daily events."""

    return (
        event.place == "Centro Social Juvenil"
        and normalized_title(event.title_es) in _ROUTINE_YOUTH_CENTRE_TITLES
    )


def _facebook_source(post: FacebookPost) -> str:
    return FACEBOOK_SOURCE_PREFIX + post.source_id


def _facebook_fingerprint(post: FacebookPost) -> str:
    stable_images = []
    for image in post.image_urls:
        parsed = urllib.parse.urlparse(image)
        stable_images.append(urllib.parse.urlunparse(
            parsed._replace(query="", fragment="")
        ))
    value = "\n".join((post.text or "", *stable_images))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _facebook_prior_posts(value: Any) -> Dict[str, Dict[str, str]]:
    """Read only bounded post metadata from the municipal snapshot."""

    if not isinstance(value, dict) or not isinstance(value.get("posts"), list):
        return {}
    result = {}
    for raw in value["posts"][:MAX_FACEBOOK_POSTS]:
        if not isinstance(raw, dict):
            continue
        source_id = raw.get("source_id")
        fingerprint = raw.get("fingerprint")
        if isinstance(source_id, str) and isinstance(fingerprint, str):
            result[source_id] = {"fingerprint": fingerprint}
    return result


def _facebook_source_events(events: Tuple[SourceEvent, ...]) -> Tuple[SourceEvent, ...]:
    return tuple(
        event for event in events
        if any(source.startswith(FACEBOOK_SOURCE_PREFIX) for source in event.sources)
    )


def _cultura_teaser(title: str, text: str) -> Optional[str]:
    """Keep one short explicit sentence after a matching event title."""
    words = _normalized_words(title)
    if not words or not words <= _normalized_words(text):
        return None
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    title_index = next((i for i, sentence in enumerate(sentences)
                        if words <= _normalized_words(sentence)), None)
    if title_index is None:
        return None
    for sentence in sentences[title_index + 1:]:
        candidate = sentence.strip()
        if 35 <= len(candidate) <= 220 and not re.search(r"\d{1,2}[:/]\d{2}", candidate):
            return candidate
    return None


def _enrich_cultura_teasers(events, posts, prior):
    """Attach Cultura prose only to an already-confirmed event identity."""
    result = []
    for event in events:
        teaser = event.teaser_es or next((old.teaser_es for old in prior
            if _same_occurrence(event, old) and old.teaser_es), None)
        if teaser is None:
            for post in posts:
                if post.text:
                    teaser = _cultura_teaser(event.title_es, post.text)
                    if teaser:
                        break
        result.append(replace(event, teaser_es=teaser, sources=tuple(dict.fromkeys(
            event.sources + (("cultura_guardamar",) if teaser else ())
        ))))
    return tuple(result)


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


def _expand_explicit_todo_dates(
    events: Tuple[SourceEvent, ...],
    rows: Tuple[Tuple[date, str, str], ...],
) -> Tuple[SourceEvent, ...]:
    """Keep future occurrences explicitly named inside a dated source row.

    Some municipal programme rows describe one Saturday and then name the
    remaining Saturdays in the same paragraph. The rolling collector need not
    fetch those distant sections, but the explicit dates must survive now.
    """

    expanded = list(events)
    for source_day, start_time, row in rows:
        match = re.search(
            r"el resto de las fechas ser[aá]n los (s[aá]bados|domingos) "
            r"([0-9, y]+) de ([a-záéíóú]+)",
            row.casefold(),
        )
        if match is None:
            continue
        month = _SPANISH_MONTHS.get(match.group(3))
        if month is None:
            continue
        weekday = 5 if match.group(1).startswith("s") else 6
        candidates = [
            event for event in events
            if event.start_date == source_day
            and event.end_date == source_day
            and event.start_time == start_time
            and _word_overlap(event.title_es, row) >= 0.5
        ]
        if len(candidates) != 1:
            continue
        source = candidates[0]
        for day_number in re.findall(r"\d{1,2}", match.group(2)):
            try:
                target_day = date(source_day.year, month, int(day_number))
            except ValueError:
                continue
            if not (
                source_day < target_day <= source_day + timedelta(days=44)
                and target_day.weekday() == weekday
            ):
                continue
            if any(
                event.start_date == target_day
                and event.start_time == source.start_time
                and _word_overlap(event.title_es, source.title_es) >= 0.8
                for event in expanded
            ):
                continue
            expanded.append(replace(
                source, start_date=target_day, end_date=target_day
            ))
    return tuple(expanded)


def _strict_quoted_todo_activity(
    source_day: date, start_time: str, row: str
) -> Optional[SourceEvent]:
    """Recover an explicitly dated, quoted activity when model parsing fails."""

    lines = row.splitlines()
    if len(lines) < 2 or lines[0] != source_day.isoformat():
        return None
    first = lines[1]
    title = re.search(
        r"\bActividad (?:con el t[ií]tulo )?[‘'\"]([^’'\"]{5,120})[’'\"]",
        first,
        re.IGNORECASE,
    )
    if title is None:
        return None
    interval = re.match(
        r"\s*[–—-]\s*\d{1,2}(?:[,:.]\d{2})?\s+a\s+"
        r"(\d{1,2})(?:[,:.]([0-5]\d))?\s*h",
        first,
        re.IGNORECASE,
    )
    end_time = (
        f"{int(interval.group(1)):02d}:{interval.group(2) or '00'}"
        if interval is not None else None
    )
    if end_time is not None and end_time <= start_time:
        return None
    place = next((
        value for value in (
            "Centro Social Juvenil", "Auditorio del Parque Reina Sofía"
        ) if value.casefold() in first.casefold()
    ), None)
    if place is None:
        return None
    return SourceEvent(
        title_es=title.group(1).strip(),
        start_date=source_day,
        end_date=source_day,
        start_time=start_time,
        end_time=end_time,
        place=place,
        category="event",
        sources=("todo_cultura",),
    )


def _unmatched_todo_rows(
    rows: Tuple[Tuple[date, str, str], ...],
    events: Tuple[SourceEvent, ...],
) -> Tuple[Tuple[date, str, str], ...]:
    """Require a distinct evidence-matching occurrence for each timed row."""

    return tuple(
        row_info
        for row_info, event_index in _match_todo_rows(rows, events)
        if event_index is None
    )


def _merge_todo_incremental_state(
    previous: Dict[str, Any],
    attempted: Dict[str, Any],
    completed_candidate_ids: set[int],
    failed_candidate_ids: set[int],
) -> Dict[str, Any]:
    """Persist safe Todo discovery while rolling back incomplete extraction."""

    previous = previous if isinstance(previous, dict) else {}
    attempted = attempted if isinstance(attempted, dict) else {}
    previous_candidates = {
        candidate.get("id"): candidate
        for candidate in previous.get("candidates", [])
        if isinstance(candidate, dict) and isinstance(candidate.get("id"), int)
    }
    successful_ids = set(completed_candidate_ids) - set(failed_candidate_ids)
    merged_candidates = []
    for candidate in attempted.get("candidates", []):
        if not isinstance(candidate, dict) or not isinstance(
            candidate.get("id"), int
        ):
            continue
        identifier = candidate["id"]
        if identifier in successful_ids:
            merged_candidates.append(dict(candidate))
            continue
        prior_candidate = previous_candidates.get(identifier, {})
        same_revision = (
            isinstance(prior_candidate, dict)
            and prior_candidate.get("modified_gmt")
            == candidate.get("modified_gmt")
        )
        merged = dict(candidate)
        merged["processed_dates"] = list(
            prior_candidate.get("processed_dates", [])
            if same_revision else []
        )
        merged["processed_chunks"] = dict(
            prior_candidate.get("processed_chunks", {})
            if same_revision
            and isinstance(prior_candidate.get("processed_chunks", {}), dict)
            else {}
        )
        merged_candidates.append(merged)

    covered = {
        value
        for value in previous.get("covered_dates", [])
        if isinstance(value, str)
    }
    for candidate in merged_candidates:
        identifier = candidate.get("id")
        prior_candidate = previous_candidates.get(identifier, {})
        if (
            isinstance(prior_candidate, dict)
            and prior_candidate.get("modified_gmt")
            != candidate.get("modified_gmt")
        ):
            covered.difference_update(
                value
                for value in (
                    *prior_candidate.get("dates", []),
                    *candidate.get("dates", []),
                )
                if isinstance(value, str)
            )
        if identifier in successful_ids:
            covered.update(
                value
                for value in candidate.get("processed_dates", [])
                if isinstance(value, str)
            )

    result = {**previous, **attempted}
    result["cursor_modified_gmt"] = previous.get("cursor_modified_gmt")
    result["covered_dates"] = sorted(covered)
    result["candidates"] = merged_candidates
    return result


def _plain_wordpress_text(value: Any, maximum: int = 12_000) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())
    if not text:
        return None
    return text[:maximum]


def _is_spanish_turismo_article(link: str) -> bool:
    if not _is_allowed_url(link, PAGE_HOSTS):
        return False
    path = urllib.parse.urlparse(link).path.strip("/").casefold()
    first = path.split("/", 1)[0] if path else ""
    return first not in {"ca", "en", "fr"}


def _read_turismo_programme_candidates(
    local_day: date,
) -> Optional[Tuple[Dict[str, Any], ...]]:
    """Discover a few recent official programme-shaped Turismo posts."""

    try:
        payload, _, _ = fetch_bounded(
            TURISMO_PROGRAMME_INDEX_URL,
            is_allowed_url=lambda value: _is_allowed_url(value, PAGE_HOSTS),
            accepted_types=frozenset({"application/json"}),
            limit_bytes=300_000,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
        posts = json.loads(payload)
    except (BoundedFetchError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(posts, list):
        return None

    horizon = local_day + timedelta(days=TURISMO_PROGRAMME_HORIZON_DAYS)
    earliest = local_day - timedelta(days=TURISMO_PROGRAMME_PAST_GRACE_DAYS)
    candidates = []
    for post in posts[:20]:
        if not isinstance(post, dict) or not isinstance(post.get("id"), int):
            continue
        title = _plain_wordpress_text(post.get("title", {}).get("rendered"), 180)
        excerpt = _plain_wordpress_text(
            post.get("excerpt", {}).get("rendered"), 2_000
        )
        link = post.get("link")
        modified = post.get("modified")
        if not all(isinstance(value, str) for value in (link, modified)):
            continue
        if (
            title is None
            or excerpt is None
            or str(local_day.year) not in title
            or not _is_spanish_turismo_article(link)
        ):
            continue
        folded_title = title.casefold()
        if "fiestas del campo" in folded_title:
            # Keep the existing evidence-complete Campo adapter independent.
            continue
        if re.search(
            r"\b(?:programa|fiestas?|feria|hogueras)\b",
            folded_title,
            re.IGNORECASE,
        ) is None:
            continue
        hints = _all_mentioned_dates(f"{title} {excerpt}", local_day)
        relevant = tuple(day for day in hints if earliest <= day <= horizon)
        if not relevant:
            continue
        future = tuple(day for day in relevant if day >= local_day)
        distance = (
            min((day - local_day).days for day in future)
            if future
            else min((local_day - day).days for day in relevant)
            + TURISMO_PROGRAMME_HORIZON_DAYS
        )
        candidates.append({
            "id": post["id"],
            "link": link,
            "modified": modified,
            "title": title,
            "distance": distance,
        })
    candidates.sort(key=lambda item: (item["distance"], item["link"]))
    return tuple(candidates[:MAX_TURISMO_PROGRAMME_ARTICLES])


def _read_turismo_programme_article(
    candidate: Dict[str, Any],
) -> Optional[Tuple[str, str, str, str]]:
    identifier = candidate.get("id")
    if not isinstance(identifier, int):
        return None
    url = (
        "https://guardamarturismo.com/wp-json/wp/v2/posts/"
        f"{identifier}?_fields=id,modified,link,title,content"
    )
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=lambda value: _is_allowed_url(value, PAGE_HOSTS),
            accepted_types=frozenset({"application/json"}),
            limit_bytes=250_000,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
        post = json.loads(payload)
    except (BoundedFetchError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(post, dict) or post.get("id") != identifier:
        return None
    link = post.get("link")
    modified = post.get("modified")
    title = _plain_wordpress_text(post.get("title", {}).get("rendered"), 120)
    text = _plain_wordpress_text(post.get("content", {}).get("rendered"))
    if (
        title is None
        or text is None
        or not all(isinstance(value, str) for value in (link, modified))
        or not _is_spanish_turismo_article(link)
        or link != candidate.get("link")
    ):
        return None
    return link, modified, title, text


def _normalize_turismo_programme_text(
    result: Dict[str, Any],
    source_text: str,
) -> Tuple[SourceEvent, ...]:
    """Validate a programme article without forcing one calendar month."""

    raw_events = result.get("events")
    if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
        raise MunicipalAgendaError("invalid Turismo programme event list")
    accepted: List[SourceEvent] = []
    for raw in raw_events:
        try:
            accepted.extend(normalize_extraction(
                {"events": [raw]},
                None,
                TURISMO_PROGRAMME_TEXT_SOURCE,
                source_text,
            ))
        except MunicipalAgendaError:
            continue
    if raw_events and not accepted:
        raise MunicipalAgendaError(
            "Every Turismo programme event candidate was invalid",
            code="NO-VALID-EVENTS",
            description="все события официальной программы не прошли проверку",
        )
    return tuple(accepted)


def _programme_article_metadata(
    events: Tuple[SourceEvent, ...],
    programme_title: str,
) -> Tuple[SourceEvent, ...]:
    ordered = sorted(
        events,
        key=lambda event: (
            event.start_date,
            event.start_time is None,
            event.start_time or "",
            normalized_title(event.title_es),
        ),
    )
    return tuple(
        replace(
            event,
            programme_title=programme_title,
            programme_order=index * 10,
        )
        for index, event in enumerate(ordered, start=1)
    )


async def _turismo_text_programme_events(
    api_key: str,
    local_day: date,
    previous: Tuple[SourceEvent, ...],
    previous_state: Dict[str, Any],
) -> Tuple[Tuple[SourceEvent, ...], Dict[str, Any]]:
    """Collect a few official Turismo programme articles text-first."""

    horizon = local_day + timedelta(days=TURISMO_PROGRAMME_HORIZON_DAYS)
    previous = tuple(
        event
        for event in previous
        if event.end_date >= local_day and event.start_date <= horizon
    )
    prior_articles = (
        previous_state.get("articles", {})
        if isinstance(previous_state.get("articles", {}), dict)
        else {}
    )
    previous_by_title: Dict[str, Tuple[SourceEvent, ...]] = {}
    for article in prior_articles.values():
        if not isinstance(article, dict):
            continue
        title = article.get("programme_title")
        if not isinstance(title, str):
            continue
        previous_by_title[title] = tuple(
            event for event in previous if event.programme_title == title
        )

    candidates = await asyncio.to_thread(
        _read_turismo_programme_candidates, local_day
    )
    if candidates is None:
        return previous, previous_state

    events: List[SourceEvent] = []
    next_articles: Dict[str, Dict[str, Any]] = {}
    seen_titles = set()
    for candidate in candidates:
        link = candidate["link"]
        previous_article = prior_articles.get(link, {})
        previous_title = (
            previous_article.get("programme_title")
            if isinstance(previous_article, dict)
            else None
        )
        prior_events = (
            previous_by_title.get(previous_title, ())
            if isinstance(previous_title, str)
            else ()
        )
        if (
            prior_events
            and isinstance(previous_article, dict)
            and previous_article.get("modified") == candidate["modified"]
            and previous_article.get("extractor_version") == 1
        ):
            events.extend(prior_events)
            next_articles[link] = dict(previous_article)
            seen_titles.add(previous_title)
            continue

        detail = await asyncio.to_thread(
            _read_turismo_programme_article, candidate
        )
        if detail is None:
            if prior_events and isinstance(previous_article, dict):
                events.extend(prior_events)
                next_articles[link] = dict(previous_article)
                seen_titles.add(previous_title)
            continue
        article_url, modified, programme_title, article_text = detail
        fingerprint = hashlib.sha256(article_text.encode("utf-8")).hexdigest()
        if (
            prior_events
            and isinstance(previous_article, dict)
            and previous_article.get("sha256") == fingerprint
            and previous_article.get("extractor_version") == 1
        ):
            events.extend(prior_events)
            next_articles[article_url] = {
                **previous_article,
                "modified": modified,
            }
            seen_titles.add(previous_title)
            continue

        try:
            extracted = await extract_agenda_text_events(api_key, article_text)
            article_events = _normalize_turismo_programme_text(
                extracted, article_text
            )
            article_events = tuple(
                event
                for event in article_events
                if event.end_date >= local_day and event.start_date <= horizon
            )
            if len(article_events) < 2:
                raise MunicipalAgendaError(
                    "Official Turismo programme article was not programme-shaped",
                    code="PROGRAMME-SHAPE",
                    description=(
                        "официальная статья не дала нескольких будущих "
                        "мероприятий"
                    ),
                )
            article_events = _programme_article_metadata(
                article_events, programme_title
            )
        except (GeminiError, MunicipalAgendaError) as exc:
            LOGGER.warning(
                "Official Turismo programme article unavailable: %s", exc
            )
            if prior_events and isinstance(previous_article, dict):
                events.extend(prior_events)
                next_articles[link] = dict(previous_article)
                seen_titles.add(previous_title)
            continue

        events.extend(article_events)
        next_articles[article_url] = {
            "modified": modified,
            "sha256": fingerprint,
            "programme_title": programme_title,
            "extractor_version": 1,
        }
        seen_titles.add(programme_title)

    # A programme may fall out of the recent-post index before its last
    # occurrence. Retain only its still-relevant verified facts until expiry.
    for link, article in prior_articles.items():
        if not isinstance(article, dict):
            continue
        title = article.get("programme_title")
        if not isinstance(title, str) or title in seen_titles:
            continue
        retained = previous_by_title.get(title, ())
        if not retained:
            continue
        events.extend(retained)
        next_articles[link] = dict(article)
        seen_titles.add(title)

    deduped = []
    seen = set()
    for event in sorted(
        events,
        key=lambda item: (
            item.start_date,
            item.start_time is None,
            item.start_time or "",
            normalized_title(item.title_es),
        ),
    ):
        key = (
            event.programme_title,
            normalized_title(event.title_es),
            event.start_date,
            event.start_time,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return tuple(deduped[:MAX_EVENTS]), {
        "version": 1,
        "articles": next_articles,
    }


def _read_turismo_programme(local_day: date) -> Optional[Tuple[str, str, str, str]]:
    """Find the current official festival article and its full-size poster.

    The monthly agenda only links a tiny inset of this programme.  WordPress
    exposes the primary article and the linked poster through a bounded public
    JSON endpoint, without a new credential or persistent raw cache.
    """

    try:
        payload, _, _ = fetch_bounded(
            TURISMO_POSTS_URL,
            is_allowed_url=lambda value: _is_allowed_url(value, PAGE_HOSTS),
            accepted_types=frozenset({"application/json"}),
            limit_bytes=500_000,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={"Accept": "application/json", "User-Agent": "GuardamarMorningDigest/0.12"},
        )
        posts = json.loads(payload)
    except (BoundedFetchError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(posts, list):
        return None
    for post in posts[:10]:
        if not isinstance(post, dict):
            continue
        title = post.get("title", {}).get("rendered", "")
        content = post.get("content", {}).get("rendered", "")
        link = post.get("link")
        if not all(isinstance(value, str) for value in (title, content, link)):
            continue
        if (
            "fiestas del campo" not in html.unescape(title).casefold()
            or str(local_day.year) not in title
            or not _is_allowed_url(link, PAGE_HOSTS)
        ):
            continue
        decoded = urllib.parse.unquote(html.unescape(content))
        poster_urls = re.findall(
            r"https://(?:www\.)?guardamarturismo\.com/"
            r"wp-content/uploads/[^\s\"'<>]+?\.(?:jpe?g|png)"
            r"(?=[\s\"'<>?|»)]|$)",
            decoded,
            re.IGNORECASE,
        )
        poster_url = next(
            (
                url for url in poster_urls
                if "cartel" in url.casefold()
                and "fiestas-del-campo" in url.casefold()
                and str(local_day.year) in url
            ),
            None,
        )
        if poster_url is None:
            continue
        article_text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", content)).split())
        programme_name = re.search(
            r"Fiestas del Campo(?: de Guardamar)?\s+\d{4}",
            html.unescape(title), re.IGNORECASE,
        )
        if programme_name is None:
            continue
        return link, poster_url, article_text[:12_000], programme_name.group(0)
    return None


def _explicit_fiesta_article_events(
    article_text: str, year: int
) -> Tuple[SourceEvent, ...]:
    """Read the complete dated finale printed in the official article text.

    The linked poster is useful corroboration, but its OCR is not a reliable
    prerequisite for these facts already stated verbatim in the HTML article.
    If the source wording changes, return nothing rather than infer a date.
    """

    saturday = re.search(
        r"El s[aá]bado (\d{1,2}) de septiembre\b(.*?)El domingo",
        article_text, re.IGNORECASE,
    )
    sunday = re.search(
        r"El domingo (\d{1,2}) habr[aá]\b(.*?)(?:Es importante|$)",
        article_text, re.IGNORECASE,
    )
    if saturday is None or sunday is None:
        return ()
    try:
        saturday_day = date(year, 9, int(saturday.group(1)))
        sunday_day = date(year, 9, int(sunday.group(1)))
    except ValueError:
        return ()
    if sunday_day != saturday_day + timedelta(days=1):
        return ()
    sat_text, sun_text = saturday.group(2), sunday.group(2)
    evidence = (
        (saturday_day, sat_text, r"disparo de cohetes de las (\d{1,2}:\d{2})", "Disparo de cohetes"),
        (saturday_day, sat_text, r"entrada de bandas comenzar[aá] a las (\d{1,2}:\d{2})", "Entrada de bandas"),
        (saturday_day, sat_text, r"Desfile Multicolor saldr[aá] a las (\d{1,2}:\d{2})", "Desfile Multicolor"),
        (saturday_day, sat_text, r"fuegos artificiales", "Fuegos artificiales"),
        (saturday_day, sat_text, r"Fiesta del Vino a las (\d{1,2}:\d{2})", "Fiesta del Vino"),
        (saturday_day, sat_text, r"actuaciones desde las (\d{1,2}:\d{2})", "Actuaciones nocturnas de las Fiestas del Campo"),
        (sunday_day, sun_text, r"chocolate con mona de madrugada", "Chocolate con mona de madrugada"),
        (sunday_day, sun_text, r"Despert[aà] a las (\d{1,2}:\d{2})", "Despertà"),
        (sunday_day, sun_text, r"Charanga a las (\d{1,2}:\d{2})", "Charanga"),
    )
    events = []
    for event_day, section, pattern, title in evidence:
        match = re.search(pattern, section, re.IGNORECASE)
        if match is None:
            return ()
        raw_time = match.group(1) if match.lastindex else None
        start_time = (
            f"{int(raw_time.split(':')[0]):02d}:{raw_time.split(':')[1]}"
            if raw_time is not None else None
        )
        teaser = None
        if title.startswith("Actuaciones nocturnas"):
            roster = re.search(
                r"(Participar[aá]n\s+[^.]{30,240}\.)", section,
                re.IGNORECASE,
            )
            if roster is None:
                return ()
            teaser = roster.group(1)
        events.append(SourceEvent(
            title_es=title,
            start_date=event_day,
            end_date=event_day,
            start_time=start_time,
            end_time=None,
            place=None,
            category="event",
            sources=("turismo_programme",),
            teaser_es=teaser,
        ))
    return tuple(events)


async def _turismo_programme_events(
    api_key: str,
    local_day: date,
    previous: Tuple[SourceEvent, ...],
    previous_state: Dict[str, Any],
) -> Tuple[Tuple[SourceEvent, ...], Dict[str, Any]]:
    programme = await asyncio.to_thread(_read_turismo_programme, local_day)
    if programme is None:
        return previous, previous_state
    article_url, poster_url, article_text = programme[:3]
    programme_name = programme[3] if len(programme) > 3 else None
    explicit_events = _explicit_fiesta_article_events(
        article_text, local_day.year
    )
    fingerprint = hashlib.sha256(article_text.encode("utf-8")).hexdigest()
    try:
        image, _, mime_type = await asyncio.to_thread(
            fetch_bounded,
            poster_url,
            is_allowed_url=lambda value: _is_allowed_url(value, PAGE_HOSTS),
            accepted_types=frozenset({"image/jpeg", "image/png"}),
            limit_bytes=POSTER_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={"Accept": "image/jpeg,image/png", "User-Agent": "GuardamarMorningDigest/0.12"},
        )
        poster_fingerprint = hashlib.sha256(image).hexdigest()
        if (
            previous
            and previous_state.get("article_url") == article_url
            and previous_state.get("poster_url") == poster_url
            and previous_state.get("sha256") == fingerprint
            and previous_state.get("poster_sha256") == poster_fingerprint
            and previous_state.get("extractor_version") == 2
        ):
            return tuple(
                _programme_source_metadata(event, programme_name, poster_url)
                for event in previous
            ), previous_state
        month = local_day.strftime("%Y-%m")
        first = await extract_agenda_events(api_key, image, mime_type)
        second = await verify_agenda_poster_events(api_key, image, mime_type)
        first_events = normalize_extraction_candidates(
            {**first, "month": month}, month, "turismo_programme"
        )
        second_events = normalize_extraction_candidates(
            {**second, "month": month}, month, "turismo_programme"
        )
        verified = intersect_verified_poster_events(first_events, second_events)
        article_result = await extract_agenda_text_events(api_key, article_text)
        article_events = normalize_extraction_candidates(
            {**article_result, "month": month},
            month,
            "turismo_programme",
            article_text,
        )
        # A primary article can corroborate a detail that one visual reading
        # missed.  Require the actual words and time to exist in its text.
        corroborated = tuple(
            event for event in (*first_events, *second_events)
            if (
                _word_overlap(event.title_es, article_text) >= 0.5
                and (event.start_time is None or _evidence_supports_time(
                    event.start_time, article_text
                ))
            )
        )
        events = merge_text_and_poster_events(verified, article_events)
        events = merge_text_and_poster_events(events, corroborated)
        saturday = re.search(
            r"El s[aá]bado\s+(\d{1,2})\s+de septiembre.*?"
            r"actuaciones desde las 23:00 horas\s*\.\s*"
            r"(Participar[aá]n\s+[^.]{30,240}\.)",
            article_text,
            re.IGNORECASE,
        )
        if saturday is not None:
            festival_day = date(local_day.year, 9, int(saturday.group(1)))
            events = tuple(
                event for event in events
                if not (
                    event.start_date == festival_day
                    and event.start_time == "23:00"
                )
            ) + (SourceEvent(
                title_es="Actuaciones nocturnas de las Fiestas del Campo",
                start_date=festival_day,
                end_date=festival_day,
                start_time="23:00",
                end_time=None,
                place=None,
                category="event",
                sources=("turismo_programme",),
                teaser_es=saturday.group(2),
            ),)
        sunday = re.search(
            r"El domingo\s+(\d{1,2})\s+habr[aá]\s+"
            r"chocolate con mona de madrugada",
            article_text,
            re.IGNORECASE,
        )
        if sunday is not None:
            festival_day = date(local_day.year, 9, int(sunday.group(1)))
            events = tuple(
                event for event in events
                if not (
                    event.start_date == festival_day
                    and "chocolate con mona" in normalized_title(event.title_es)
                )
            ) + (SourceEvent(
                title_es="Chocolate con mona de madrugada",
                start_date=festival_day,
                end_date=festival_day,
                start_time=None,
                end_time=None,
                place=None,
                category="event",
                sources=("turismo_programme",),
            ),)
        cleaned = []
        seen_charanga = set()
        for event in events:
            title = normalized_title(event.title_es)
            if "fuegos artificiales" in title or "chocolate con mona" in title:
                # The official programme says "after the parade" and
                # "during the night", not an exact clock time.
                event = replace(event, start_time=None, end_time=None)
            if "charanga" in title:
                key = (event.start_date, event.start_time)
                if key in seen_charanga:
                    continue
                seen_charanga.add(key)
            cleaned.append(event)
        events = tuple(cleaned)
        if explicit_events:
            # The article states the parade time but leaves the fireworks
            # untimed. A vision candidate sometimes combines both under
            # 19:00; the article's separate facts take precedence.
            charanga_place = next((
                event.place for event in events
                if "charanga" in normalized_title(event.title_es)
                and event.place is not None
            ), None)
            events = tuple(
                replace(event, place=charanga_place)
                if event.title_es == "Charanga" and charanga_place else event
                for event in explicit_events
            )
        events = tuple(
            event for event in events
            if local_day <= event.end_date <= local_day + timedelta(days=44)
        )
        if not events:
            return previous, previous_state
        return tuple(
            _programme_source_metadata(event, programme_name, poster_url)
            for event in events
        ), {
            "article_url": article_url,
            "poster_url": poster_url,
            "sha256": fingerprint,
            "poster_sha256": poster_fingerprint,
            "extractor_version": 2,
        }
    except (BoundedFetchError, GeminiError, MunicipalAgendaError) as exc:
        LOGGER.warning("Official Turismo programme unavailable: %s", exc)
        if (
            previous and previous_state.get("sha256") == fingerprint
            and previous_state.get("article_url") == article_url
        ):
            return tuple(
                _programme_source_metadata(event, programme_name, poster_url)
                for event in previous
            ), previous_state
        if explicit_events:
            return tuple(
                _programme_source_metadata(event, programme_name, poster_url)
                for event in explicit_events
            ), {
                "article_url": article_url,
                "poster_url": poster_url,
                "sha256": fingerprint,
                # Try the poster again on a later run for venue/details.
                "extractor_version": 1,
            }
        return previous, previous_state


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
    "septiembre": 9, "setiembre": 9, "setembre": 9, "octubre": 10,
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


def _supported_title(
    title: str,
    evidence: str,
    *,
    allow_source_digit_typo: bool = False,
) -> bool:
    """Require source-supported title words, tolerating one obvious digit typo."""

    title_words = _claim_words(title)
    evidence_words = _claim_words(evidence)
    if not title_words:
        return False
    if title_words <= evidence_words:
        return True
    if not allow_source_digit_typo:
        return False
    missing = title_words - evidence_words
    if len(missing) != 1:
        return False
    target = next(iter(missing))
    if not target.isalpha():
        return False
    return any(
        len(candidate) == len(target)
        and any(char.isdigit() for char in candidate)
        and sum(left != right for left, right in zip(target, candidate)) == 1
        for candidate in evidence_words - title_words
    )


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
        or (
            left.start_time is not None
            and right.start_time is not None
            and left.start_time != right.start_time
        )
    ):
        return False
    if (
        left.place is not None
        and right.place is not None
        and left.place.casefold() != "guardamar del segura"
        and right.place.casefold() != "guardamar del segura"
        and _word_overlap(left.place, right.place) < 0.5
    ):
        return False
    required_overlap = (
        0.8 if left.start_time is None or right.start_time is None else 0.5
    )
    return _word_overlap(left.title_es, right.title_es) >= required_overlap


def _opening_matches_exhibition(
    opening: SourceEvent,
    exhibition: SourceEvent,
) -> bool:
    """Match one explicit inauguration to the exhibition it opens."""

    if (
        opening.category != "exhibition_opening"
        or exhibition.category != "exhibition"
        or opening.start_date != exhibition.start_date
        or opening.end_date != opening.start_date
        or opening.start_time is None
    ):
        return False
    if (
        opening.place is not None
        and exhibition.place is not None
        and _word_overlap(opening.place, exhibition.place) < 0.5
    ):
        return False
    return _word_overlap(opening.title_es, exhibition.title_es) >= 0.5


def _normalize_exhibition_opening_times(
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Keep an inauguration time from becoming a daily exhibition time."""

    openings = tuple(
        event for event in events if event.category == "exhibition_opening"
    )
    normalized = []
    for event in events:
        if (
            event.category == "exhibition"
            and event.start_time is not None
            and event.end_time is None
            and any(
                _opening_matches_exhibition(opening, event)
                and opening.start_time == event.start_time
                for opening in openings
            )
        ):
            event = replace(event, start_time=None)
        normalized.append(event)
    return tuple(normalized)


def _prefer_openings_for_day(
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """On opening day show the inauguration instead of the generic range."""

    openings = tuple(
        event for event in events if event.category == "exhibition_opening"
    )
    if not openings:
        return events
    return tuple(
        event
        for event in events
        if not (
            event.category == "exhibition"
            and any(
                _opening_matches_exhibition(opening, event)
                for opening in openings
            )
        )
    )


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
        current_session_key = current.session_source_key
        candidate_session_key = (
            poster_event.session_source_key if same_occurrence else None
        )
        current_parent = current.session_parent_title_es
        candidate_parent = (
            poster_event.session_parent_title_es if same_occurrence else None
        )
        if current_session_key is None:
            session_source_key = candidate_session_key
            session_parent_title_es = candidate_parent
        elif candidate_session_key is None:
            session_source_key = current_session_key
            session_parent_title_es = current_parent
        elif current_session_key == candidate_session_key:
            session_source_key = current_session_key
            parent_candidates = [
                value for value in (current_parent, candidate_parent) if value
            ]
            session_parent_title_es = (
                min(
                    parent_candidates,
                    key=lambda value: (len(value), value.casefold()),
                )
                if parent_candidates else None
            )
        else:
            session_source_key = None
            session_parent_title_es = None
        merged[duplicate_index] = SourceEvent(
            **{
                **current.__dict__,
                "title_es": (
                    _richer_title(current.title_es, poster_event.title_es)
                    if same_occurrence and candidate_is_text
                    else current.title_es
                ),
                "start_time": current.start_time or poster_event.start_time,
                "end_time": current.end_time or poster_event.end_time,
                "place": (
                    poster_event.place
                    if current.place is None or (
                        current.place.casefold() == "guardamar del segura"
                        and poster_event.place is not None
                    )
                    else current.place
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
                "registration_url": (
                    current.registration_url
                    or (poster_event.registration_url if same_occurrence else None)
                ),
                "capacity_limited": (
                    current.capacity_limited
                    or (poster_event.capacity_limited if same_occurrence else False)
                ),
                "admission_evidence": current.admission_evidence or (
                    poster_event.admission_evidence if same_occurrence else None
                ),
                "teaser_es": current.teaser_es or (
                    poster_event.teaser_es if same_occurrence else None
                ),
                "duration_minutes": (
                    current.duration_minutes or poster_event.duration_minutes
                ),
                "audience_label": (
                    current.audience_label or poster_event.audience_label
                ),
                "details": tuple(dict.fromkeys(
                    (*current.details, *poster_event.details)
                )),
                "place_query": current.place_query or poster_event.place_query,
                "meeting_point": current.meeting_point or poster_event.meeting_point,
                "schedule_note": current.schedule_note or poster_event.schedule_note,
                "access_note": current.access_note or poster_event.access_note,
                "programme_title": current.programme_title or poster_event.programme_title,
                "programme_order": (
                    current.programme_order if current.programme_order is not None
                    else poster_event.programme_order
                ),
                "session_source_key": session_source_key,
                "session_parent_title_es": session_parent_title_es,
                "image_url": current.image_url or poster_event.image_url,
            }
        )
    return tuple(merged[:MAX_EVENTS])


def _bounded_synopsis_excerpt(value: str) -> Optional[str]:
    """Keep a source-only synopsis excerpt; never generate or infer prose."""

    value = " ".join(value.split()).strip()
    if len(value) < 20:
        return None
    if len(value) <= 220:
        return value
    sentences = [
        sentence.strip()
        for sentence in re.split(
            r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ¿¡0-9])",
            value,
        )
        if sentence.strip()
    ]
    if not sentences:
        sentences = [value]
    selected = sentences[0]
    index = 1
    while len(selected) < 80 and index < len(sentences):
        candidate = selected + " " + sentences[index]
        if len(candidate) > 220:
            break
        selected = candidate
        index += 1
    if len(selected) <= 220:
        return selected
    clipped = selected[:210].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (clipped or selected[:210].rstrip()) + "…"


def _todo_cinema_synopsis_candidates(
    programs: Tuple[object, ...],
) -> Tuple[Tuple[date, str, str, str], ...]:
    """Extract only unambiguous explicit synopsis paragraphs from event rows."""

    result = []
    seen = set()
    for program in programs:
        for event_day, start_time, row in getattr(program, "event_rows", ()):
            lines = [line.strip() for line in row.splitlines() if line.strip()]
            synopsis_matches = [
                (line, match)
                for line in lines
                for match in _SYNOPSIS_MARKER.finditer(line)
            ]
            marker_count = sum(
                len(re.findall(r"\bLa\s+sinopsis\b", line, re.IGNORECASE))
                for line in lines
            )
            if marker_count != 1 or len(synopsis_matches) != 1:
                continue
            synopsis_line, synopsis_match = synopsis_matches[0]
            synopsis = _bounded_synopsis_excerpt(synopsis_match.group(1))
            if synopsis is None:
                continue
            event_line = next(
                (
                    line for line in lines
                    if re.search(
                        r"\b(?:sesi[oó]n\s+de\s+cine|pel[ií]cula)\b",
                        line,
                        re.IGNORECASE,
                    )
                    and _event_time(line) == start_time
                ),
                None,
            )
            if event_line is None:
                continue
            key = (event_day, start_time, event_line.casefold(), synopsis)
            if key in seen:
                continue
            seen.add(key)
            result.append((event_day, start_time, event_line[:300], synopsis))
    return tuple(result)


def _enrich_todo_cinema_synopses(
    events: Tuple[SourceEvent, ...],
    programs: Tuple[object, ...],
) -> Tuple[SourceEvent, ...]:
    """Attach a source excerpt only to a uniquely matched verified cinema event."""

    candidates = _todo_cinema_synopsis_candidates(programs)
    enriched = []
    for event in events:
        if "turismo_cinema" not in event.sources or event.teaser_es:
            enriched.append(event)
            continue
        matches = []
        for event_day, start_time, title_hint, synopsis in candidates:
            if event.start_date != event_day or event.start_time != start_time:
                continue
            overlap = _word_overlap(event.title_es, title_hint)
            shared = _normalized_words(event.title_es) & _normalized_words(title_hint)
            if overlap >= 0.5 and len(shared) >= 2:
                matches.append((overlap, synopsis))
        if not matches:
            enriched.append(event)
            continue
        best_overlap = max(value[0] for value in matches)
        best_synopses = {
            synopsis for overlap, synopsis in matches if overlap == best_overlap
        }
        if len(best_synopses) != 1:
            enriched.append(event)
            continue
        synopsis = next(iter(best_synopses))
        enriched.append(replace(
            event,
            teaser_es=synopsis,
            sources=tuple(dict.fromkeys(
                event.sources + ("todo_cultura_synopsis",)
            )),
        ))
    return tuple(enriched)


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
        if overlap >= 0.5 and discriminating:
            return overlap
        place_overlap = _word_overlap(
            event.place or "", admission.title_hint
        )
        if (
            admission.start_time is not None
            and place_overlap >= 0.75
            and discriminating
        ):
            return place_overlap
        return None

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
                details=tuple(dict.fromkeys((
                    *event.details,
                    *((best.distance_label,) if best.distance_label else ()),
                ))),
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
                    detail.registration_url,
                    detail.participation_note,
                    detail.capacity_limited,
                    detail.start_time,
                    detail.difficulty_label,
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
        enriched_details = event.details
        if (
            best.difficulty_label
            and best.difficulty_label not in enriched_details
            and len(enriched_details) < 3
        ):
            enriched_details = (*enriched_details, best.difficulty_label)
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
            registration_url=(
                event.registration_url or best.registration_url
            ),
            capacity_limited=(
                event.capacity_limited or best.capacity_limited
            ),
            details=enriched_details,
        ))
    return tuple(enriched)


def _enrich_todo_summaries(
    events: Tuple[SourceEvent, ...],
    details: Tuple[TodoCulturaSummary, ...],
    target_date: date,
) -> Tuple[SourceEvent, ...]:
    """Attach one short event-local source summary without guessing."""

    def matches(detail: TodoCulturaSummary, event: SourceEvent) -> Optional[float]:
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
        title_overlap = _word_overlap(event.title_es, detail.title_hint)
        if title_overlap >= 0.5:
            return title_overlap
        place_overlap = _word_overlap(event.place or "", detail.title_hint)
        if (
            detail.start_time is not None
            and bool(
                _claim_words(event.title_es)
                & _claim_words(detail.title_hint)
            )
            and place_overlap >= 0.75
        ):
            return place_overlap
        return None

    enriched = []
    for event in events:
        if (
            event.teaser_es
            or not event.start_date <= target_date <= event.end_date
        ):
            enriched.append(event)
            continue
        ranked = []
        for detail in details:
            candidate_overlap = matches(detail, event)
            if candidate_overlap is not None:
                ranked.append((candidate_overlap, detail))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            enriched.append(event)
            continue
        tied = [
            detail for overlap, detail in ranked
            if overlap == ranked[0][0]
        ]
        if len({detail.teaser_es for detail in tied}) != 1:
            enriched.append(event)
            continue
        best = tied[0]
        matching_sessions = {
            candidate.start_time
            for candidate in events
            if candidate.start_date == event.start_date
            and matches(best, candidate) is not None
        }
        if best.start_time is None and len(matching_sessions) > 1:
            enriched.append(event)
            continue
        enriched.append(replace(
            event,
            teaser_es=best.teaser_es,
            sources=tuple(dict.fromkeys(
                event.sources + ("todo_cultura_summary",)
            )),
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
            "exhibition_opening",
            "workshop",
            "municipal_service",
            "opening_hours",
        }:
            raise MunicipalAgendaError("invalid poster event category")
        if category == "opening_hours":
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
                or not _supported_title(
                    title_es,
                    evidence,
                    allow_source_digit_typo=(source == "todo_cultura"),
                )
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
        if (
            category not in {"exhibition", "municipal_service"}
            and start_date != end_date
        ):
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
        registration_url = raw.get("registration_url")
        if registration_url is not None:
            if not isinstance(registration_url, str):
                raise MunicipalAgendaError("invalid event registration URL")
            registration_url = normalize_registration_url(registration_url)
            if registration_url is None:
                raise MunicipalAgendaError("invalid event registration URL")
        capacity_limited = raw.get("capacity_limited", False)
        if not isinstance(capacity_limited, bool):
            raise MunicipalAgendaError("invalid event capacity flag")
        admission_evidence = _clean_text(raw.get("admission_evidence"), 600)
        duration_minutes = raw.get("duration_minutes")
        if duration_minutes is not None and (
            type(duration_minutes) is not int
            or not 1 <= duration_minutes <= 720
        ):
            raise MunicipalAgendaError("invalid event duration")
        audience_label = _clean_text(raw.get("audience_label"), 40)
        raw_details = raw.get("details", ())
        if (
            not isinstance(raw_details, (list, tuple))
            or len(raw_details) > 3
        ):
            raise MunicipalAgendaError("invalid event details")
        details = tuple(_clean_text(item, 60) for item in raw_details)
        if any(item is None for item in details):
            raise MunicipalAgendaError("invalid event details")
        place_query = _clean_text(raw.get("place_query"), 120)
        if place_query and not event_place_is_map_safe(place_query):
            raise MunicipalAgendaError("invalid event map query")
        meeting_point = _clean_text(raw.get("meeting_point"), 120)
        schedule_note = _clean_text(raw.get("schedule_note"), 160)
        access_note = _clean_text(raw.get("access_note"), 100)
        programme_title = _clean_text(raw.get("programme_title"), 120)
        programme_order = raw.get("programme_order")
        if programme_order is not None and (
            type(programme_order) is not int or not 0 <= programme_order <= 999
        ):
            raise MunicipalAgendaError("invalid programme order")
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
            registration_url=registration_url,
            capacity_limited=capacity_limited,
            admission_evidence=admission_evidence,
            duration_minutes=duration_minutes,
            audience_label=audience_label,
            details=details,
            place_query=place_query,
            meeting_point=meeting_point,
            schedule_note=schedule_note,
            access_note=access_note,
            programme_title=programme_title,
            programme_order=programme_order,
        )
        event = _explicit_venue_and_address(event)
        key = (event.title_es.casefold(), event.start_date, event.start_time)
        if category == "municipal_service" and start_date == end_date:
            # One-day routine services (for example, a generic youth-centre
            # opening row) are not useful event entries. Keep dated ranges,
            # which represent an activity or campaign active today.
            continue
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
                "registration_url": event.registration_url,
                "capacity_limited": event.capacity_limited,
                "admission_evidence": event.admission_evidence,
                "teaser_es": event.teaser_es,
                "duration_minutes": event.duration_minutes,
                "audience_label": event.audience_label,
                "details": list(event.details),
                "place_query": event.place_query,
                "meeting_point": event.meeting_point,
                "schedule_note": event.schedule_note,
                "access_note": event.access_note,
                "programme_title": event.programme_title,
                "programme_order": event.programme_order,
                "session_source_key": event.session_source_key,
                "session_parent_title_es": event.session_parent_title_es,
                "image_url": event.image_url,
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
            if isinstance(raw, dict) and isinstance(raw.get("teaser_es"), str):
                normalized = replace(normalized, teaser_es=raw["teaser_es"])
            raw_session_key = (
                raw.get("session_source_key")
                if isinstance(raw, dict) else None
            )
            raw_session_parent = (
                raw.get("session_parent_title_es")
                if isinstance(raw, dict) else None
            )
            if raw_session_key is not None:
                if (
                    not isinstance(raw_session_key, str)
                    or not re.fullmatch(
                        r"[a-z][a-z0-9_]{1,31}:[0-9a-f]{64}",
                        raw_session_key,
                    )
                    or not isinstance(raw_session_parent, str)
                ):
                    raise ValueError
                raw_session_parent = " ".join(raw_session_parent.split()).strip()
                if not 5 <= len(raw_session_parent) <= 180:
                    raise ValueError
                normalized = replace(
                    normalized,
                    session_source_key=raw_session_key,
                    session_parent_title_es=raw_session_parent,
                )
            elif raw_session_parent is not None and not isinstance(
                raw_session_parent, str
            ):
                raise ValueError
            raw_image = raw.get("image_url") if isinstance(raw, dict) else None
            if raw_image is not None:
                image_url = _normalized_turismo_image_url(raw_image)
                if image_url is None:
                    raise ValueError
                normalized = replace(normalized, image_url=image_url)
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
            if _is_contentless_generic_event(normalized):
                continue
            # Older snapshots predate access_note. This source marker is set
            # only by the deterministic official row whose free admission is
            # explicitly qualified by "hasta completar aforo".
            if (
                "turismo_cinema" in normalized.sources
                and normalized.ticket_price_cents == 0
                and normalized.capacity_limited
                and normalized.access_note is None
            ):
                normalized = replace(normalized, access_note="до заполнения зала")
            events.append(_explicit_venue_and_address(
                _programme_source_metadata(normalized)
            ))
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
_TEXT_SOURCES = frozenset({
    "turismo_html",
    "turismo_programme_text",
    "todo_cultura",
    "todo_cultura_reviewed",
})


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
        place_query=current.place_query or correction.place_query,
        meeting_point=current.meeting_point or correction.meeting_point,
        schedule_note=current.schedule_note or correction.schedule_note,
        access_note=current.access_note or correction.access_note,
        duration_minutes=current.duration_minutes or correction.duration_minutes,
        audience_label=current.audience_label or correction.audience_label,
        details=tuple(dict.fromkeys((*current.details, *correction.details))),
        programme_title=current.programme_title or correction.programme_title,
        programme_order=(
            current.programme_order if current.programme_order is not None
            else correction.programme_order
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
        old_events = (
            tuple(
                _sanitize_generic_agenda_ticket_url(event)
                for event in snapshot["_events"]
            )
            if snapshot is not None else ()
        )
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
        old_facebook_events = _facebook_source_events(old_events)
        old_programme_events = tuple(
            event for event in old_events
            if "turismo_programme" in event.sources
        )
        old_programme_text_events = tuple(
            event for event in old_events
            if TURISMO_PROGRAMME_TEXT_SOURCE in event.sources
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
            deterministic_exhibitions = extract_official_exhibitions(
                page_text, text_month
            )
            extracted_text = await extract_agenda_text_events(
                api_key, page_text
            )
            extracted_text = {**extracted_text, "month": text_month}
            try:
                text_events = normalize_extraction_candidates(
                    extracted_text,
                    text_month,
                    "turismo_html",
                    page_text,
                )
            except MunicipalAgendaError:
                if not deterministic_exhibitions:
                    raise
                LOGGER.warning(
                    "Structured official agenda was invalid; using "
                    "deterministic exhibition facts"
                )
                text_events = ()
            text_events = merge_text_and_poster_events(
                text_events, deterministic_exhibitions
            )
            if not text_events:
                raise MunicipalAgendaError(
                    "Official text agenda extraction was empty",
                    code="EMPTY-TEXT",
                    description="официальная текстовая программа не дала событий",
                )

        if page_text:
            text_events = merge_text_and_poster_events(
                extract_official_cinema(page_text, text_month), text_events
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
        todo_state_complete = True
        todo_completed_candidate_ids: set[int] = set()
        todo_failed_candidate_ids: set[int] = set()
        todo_enrichment_programs: Tuple[object, ...] = ()
        todo_explicit_rows: Tuple[Tuple[date, str, str], ...] = ()
        try:
            todo_window = await fetch_program_window(
                local_now.date(),
                todo_source if isinstance(todo_source, dict) else None,
            )
            todo_enrichment_programs = todo_window.programs
            for todo_program in todo_window.programs:
                todo_explicit_rows += todo_program.event_rows
                if todo_program.standalone:
                    todo_result = await extract_guardamar_standalone_events(
                        api_key,
                        todo_program.text,
                        todo_program.dates,
                    )
                else:
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
                try:
                    new_todo_events = normalize_extraction_candidates(
                        todo_result,
                        todo_month,
                        "todo_cultura",
                        todo_program.text,
                    )
                except MunicipalAgendaError as exc:
                    if exc.diagnostic_code != "NO-VALID-EVENTS":
                        raise
                    new_todo_events = ()
                if todo_program.standalone:
                    new_todo_events = tuple(
                        event
                        for event in new_todo_events
                        if any(
                            event.start_date <= target_date <= event.end_date
                            for target_date in todo_program.dates
                        )
                    )
                corroborating_events = (
                    *text_events, *poster_events, *prior_todo_events
                )
                pending_rows = _unmatched_todo_rows(
                    todo_program.event_rows,
                    (*new_todo_events, *corroborating_events),
                )
                if pending_rows:
                    if len(pending_rows) <= MAX_TODO_ROW_RECOVERIES:
                        for row_day, row_time, row in pending_rows:
                            row_result = await extract_agenda_text_events(
                                api_key, row
                            )
                            try:
                                recovered = normalize_extraction_candidates(
                                    {**row_result, "month": todo_month},
                                    todo_month,
                                    "todo_cultura",
                                    row,
                                )
                            except MunicipalAgendaError as exc:
                                if exc.diagnostic_code != "NO-VALID-EVENTS":
                                    raise
                                recovered = ()
                            new_todo_events = merge_text_and_poster_events(
                                new_todo_events, recovered
                            )
                            if not any(
                                event.start_date == row_day
                                and event.start_time == row_time
                                and _word_overlap(event.title_es, row) >= 0.5
                                for event in new_todo_events
                            ):
                                strict = _strict_quoted_todo_activity(
                                    row_day, row_time, row
                                )
                                if strict is not None:
                                    new_todo_events = merge_text_and_poster_events(
                                        new_todo_events, (strict,)
                                    )
                    pending_rows = _unmatched_todo_rows(
                        todo_program.event_rows,
                        (*new_todo_events, *corroborating_events),
                    )
                program_complete = not pending_rows
                if program_complete:
                    todo_completed_candidate_ids.update(
                        todo_program.candidate_ids
                    )
                else:
                    todo_failed_candidate_ids.update(
                        todo_program.candidate_ids
                    )
                if pending_rows:
                    todo_state_complete = False
                    missing = ", ".join(
                        f"{day.isoformat()} {start_time}"
                        for day, start_time, _ in pending_rows
                    )
                    LOGGER.warning(
                        "Todo Cultura extraction incomplete; keeping verified "
                        "rows without advancing source state: %s",
                        missing,
                    )
                    if diagnostics is not None:
                        diagnostics.append(SourceDiagnostic(
                            "TODO-CULTURA-TODO-INCOMPLETE",
                            "Todo Cultura Vega Baja",
                            (
                                "не все строки программы распознаны; "
                                f"не подтверждено время {missing}; "
                                "проверенные строки сохранены, источник "
                                "будет перечитан"
                            ),
                        ))
                new_todo_events = _expand_explicit_todo_dates(
                    new_todo_events, todo_program.event_rows
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
                    new_todo_events = _enrich_todo_summaries(
                        new_todo_events,
                        todo_program.summaries,
                        target_date,
                    )
                if not new_todo_events:
                    continue
                refreshed_dates = set(todo_program.dates)
                retained = (
                    tuple(
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
                    if program_complete
                    else todo_events
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

        # A previously verified occurrence can still carry source-explicit
        # future dates when an unrelated programme row fails model parsing.
        # Keep the cursor unchanged, but do not discard those deterministic
        # recurring dates from the newly fetched official-attributed text.
        if todo_window is not None and todo_explicit_rows:
            todo_events = _annotate_todo_source_sessions(
                todo_events,
                todo_explicit_rows,
            )
        if todo_explicit_rows:
            todo_events = _expand_explicit_todo_dates(
                todo_events, todo_explicit_rows
            )

        facebook_source = old_sources.get("facebook", {})
        prior_facebook_posts = _facebook_prior_posts(facebook_source)
        prior_facebook_by_source = {
            source: tuple(
                event
                for event in old_facebook_events
                if source in event.sources
            )
            for source in {
                source
                for event in old_facebook_events
                for source in event.sources
                if source.startswith(FACEBOOK_SOURCE_PREFIX)
            }
        }
        facebook_events = old_facebook_events
        facebook_state = facebook_source if isinstance(facebook_source, dict) else {}
        try:
            posts = await fetch_facebook_posts()
            current_sources = set()
            next_facebook_events: List[SourceEvent] = []
            next_facebook_posts = []
            local_month = local_now.strftime("%Y-%m")
            for post in posts[:MAX_FACEBOOK_POSTS]:
                source = _facebook_source(post)
                current_sources.add(source)
                fingerprint = _facebook_fingerprint(post)
                prior = prior_facebook_posts.get(post.source_id)
                if prior is not None and prior.get("fingerprint") == fingerprint:
                    next_facebook_events.extend(
                        prior_facebook_by_source.get(source, ())
                    )
                elif post.text:
                    try:
                        extracted = await extract_agenda_text_events(
                            api_key, post.text
                        )
                        extracted = {**extracted, "month": local_month}
                        next_facebook_events.extend(
                            normalize_extraction_candidates(
                                extracted,
                                local_month,
                                source,
                                post.text,
                            )
                        )
                    except (GeminiError, MunicipalAgendaError) as exc:
                        LOGGER.warning(
                            "Facebook post analysis failed; retaining prior facts: %s",
                            exc,
                        )
                        next_facebook_events.extend(
                            prior_facebook_by_source.get(source, ())
                        )
                        if prior is not None:
                            next_facebook_posts.append({
                                "source_id": post.source_id,
                                "fingerprint": prior["fingerprint"],
                            })
                        continue
                next_facebook_posts.append({
                    "source_id": post.source_id,
                    "fingerprint": fingerprint,
                })
            # A card may fall out of Facebook's short timeline before its
            # explicitly dated event has happened. Keep only such active facts.
            for source, prior_events in prior_facebook_by_source.items():
                if source not in current_sources:
                    next_facebook_events.extend(
                        event for event in prior_events
                        if event.end_date >= local_now.date()
                    )
            facebook_events = tuple(next_facebook_events[:MAX_EVENTS])
            facebook_state = {
                "checked_at": now.isoformat(),
                "posts": next_facebook_posts[:MAX_FACEBOOK_POSTS],
            }
        except FacebookError as exc:
            LOGGER.warning("Facebook timeline unavailable; retaining prior facts: %s", exc)
            if diagnostics is not None:
                diagnostics.append(source_error(
                    "FACEBOOK",
                    "Ajuntament de Guardamar Facebook",
                    exc,
                    stage="SUPPLEMENTAL",
                ))

        programme_source = old_sources.get("turismo_programme", {})
        programme_events, programme_state = await _turismo_programme_events(
            api_key,
            local_now.date(),
            old_programme_events,
            programme_source if isinstance(programme_source, dict) else {},
        )
        programme_events = tuple(
            _programme_source_metadata(event) for event in programme_events
        )
        programme_text_source = old_sources.get(
            TURISMO_PROGRAMME_TEXT_SOURCE, {}
        )
        programme_text_events, programme_text_state = (
            await _turismo_text_programme_events(
                api_key,
                local_now.date(),
                old_programme_text_events,
                (
                    programme_text_source
                    if isinstance(programme_text_source, dict) else {}
                ),
            )
        )
        events = merge_text_and_poster_events(text_events, poster_events)
        events = merge_text_and_poster_events(events, programme_events)
        events = merge_text_and_poster_events(events, programme_text_events)
        events = merge_text_and_poster_events(events, todo_events)
        events = merge_text_and_poster_events(events, facebook_events)
        events = _normalize_exhibition_opening_times(events)
        if todo_window is not None:
            current_admissions = tuple(
                admission
                for program in todo_window.programs
                for admission in program.admissions
                if admission.start_time is not None
                and (
                    admission.event_date is not None
                    or bool(admission.event_dates)
                )
            )
            if current_admissions:
                events = _enrich_admissions(events, current_admissions)
            current_participation = tuple(
                detail
                for program in todo_window.programs
                for detail in program.participation
            )
            target_dates = tuple(dict.fromkeys(
                day
                for program in todo_window.programs
                for day in program.dates
            ))
            if current_participation:
                for target_date in target_dates:
                    events = _enrich_todo_participation(
                        events, current_participation, target_date
                    )
            current_summaries = tuple(
                summary
                for program in todo_window.programs
                for summary in program.summaries
            )
            if current_summaries:
                for target_date in target_dates:
                    events = _enrich_todo_summaries(
                        events, current_summaries, target_date
                    )
        if todo_enrichment_programs:
            events = _enrich_todo_cinema_synopses(
                events,
                todo_enrichment_programs,
            )
        cultura_state: Dict[str, Any] = {"checked_at": now.isoformat()}
        try:
            cultura_posts = await fetch_facebook_posts(CULTURA_GUARDAMAR_PAGE_URL)
            events = _enrich_cultura_teasers(events, cultura_posts, old_events)
        except FacebookError as exc:
            LOGGER.info("Cultura Guardamar timeline unavailable; retaining prior teasers: %s", exc)
            events = _enrich_cultura_teasers(events, (), old_events)
            failure = source_error(
                "CULTURA", "Cultura Guardamar", exc, stage="ENRICHMENT"
            )
            cultura_state["diagnostic"] = {
                "code": failure.code,
                "source": failure.source,
                "description": failure.description,
            }
            if diagnostics is not None:
                diagnostics.append(failure)
        events = tuple(
            event for event in events
            if not _is_contentless_generic_event(event)
        )
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
            todo_state = (
                todo_window.source_state
                if todo_state_complete
                else _merge_todo_incremental_state(
                    todo_source if isinstance(todo_source, dict) else {},
                    todo_window.source_state,
                    todo_completed_candidate_ids,
                    todo_failed_candidate_ids,
                )
            )
            source_state["todo_cultura"] = {
                **todo_state,
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
        if programme_state:
            source_state["turismo_programme"] = programme_state
        if programme_text_state:
            source_state[TURISMO_PROGRAMME_TEXT_SOURCE] = {
                **programme_text_state,
                "checked_at": now.isoformat(),
            }
        if facebook_state:
            source_state["facebook"] = facebook_state
        source_state["cultura_guardamar"] = cultura_state
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
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Tuple[SourceEvent, ...]:
    """Read current events from the last atomic catalog without network I/O."""

    snapshot = await asyncio.to_thread(_load_snapshot, state_path)
    if snapshot is None:
        raise MunicipalAgendaError(
            "Municipal agenda catalog does not exist",
            code="NO-SNAPSHOT",
            description="локальный каталог мероприятий ещё не создан",
        )
    if diagnostics is not None:
        source_state = snapshot.get("sources", {}).get(
            "cultura_guardamar", {}
        )
        raw = (
            source_state.get("diagnostic")
            if isinstance(source_state, dict)
            else None
        )
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("code"), str)
            and raw["code"].startswith("CULTURA-")
            and raw.get("source") == "Cultura Guardamar"
            and isinstance(raw.get("description"), str)
        ):
            diagnostics.append(SourceDiagnostic(
                raw["code"], raw["source"], raw["description"][:240]
            ))
    events = snapshot["_events"]
    poster_url = str(snapshot.get("poster_url", ""))
    events = _apply_reviewed_corrections(poster_url, events)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    events = _apply_reviewed_daily_schedules(events, local_day)
    active = [
        event
        for event in events
        if event.start_date <= local_day <= event.end_date
        and not _is_editorially_hidden_daily_event(event)
    ]
    active = list(_prefer_openings_for_day(tuple(active)))
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
    source_events = await _cached_current_events(now, state_path, diagnostics)
    if not source_events:
        return ()
    session_plan = _session_source_plan(source_events)
    planned = list(zip(source_events, session_plan))
    translated_events = []
    if translation_cache_path is not None:
        translated_events = [
            (
                source,
                cached_title(
                    translation_cache_path,
                    "municipal_agenda",
                    display_source_title,
                ),
                session_group_key,
            )
            for source, (
                display_source_title,
                session_group_key,
            ) in planned
        ]
    else:
        display_source_titles = [
            metadata[0] for _, metadata in planned
        ]
        unique_titles = list(dict.fromkeys(display_source_titles))
        translated_by_title = {}
        try:
            titles = await translate_event_titles(api_key, unique_titles)
            translated_by_title.update(zip(unique_titles, titles))
        except GeminiError as batch_error:
            for display_source_title in unique_titles[
                :MAX_INDIVIDUAL_TRANSLATION_RECOVERY
            ]:
                try:
                    title = (await translate_event_titles(
                        api_key, [display_source_title]
                    ))[0]
                except GeminiError:
                    continue
                translated_by_title[display_source_title] = title
            failed_translations = sum(
                display_source_title not in translated_by_title
                for display_source_title in display_source_titles
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
            if not translated_by_title:
                raise MunicipalAgendaError(
                    "Event translation failed",
                    code=batch_error.diagnostic_code,
                    status=batch_error.server_status,
                    description=batch_error.safe_description,
                ) from batch_error
        translated_events = [
            (
                source,
                translated_by_title[display_source_title],
                session_group_key,
            )
            for source, (
                display_source_title,
                session_group_key,
            ) in planned
            if display_source_title in translated_by_title
        ]
    result = []
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for source, title, session_group_key in translated_events:
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
        place = source.place
        meeting_point = source.meeting_point
        if place and not event_place_is_map_safe(place) and place.casefold().startswith(
            ("место старта", "место сбора")
        ):
            meeting_point = meeting_point or place
            place = None
        participation_note = source.participation_note
        event_details = tuple(_detail_label(item) for item in source.details)
        legacy_difficulty = "маршрут низкой–средней сложности"
        if participation_note:
            note_parts = [
                part.strip()
                for part in participation_note.split(";")
                if part.strip()
            ]
            if legacy_difficulty in note_parts:
                difficulty = ROUTE_DIFFICULTY_PREFIX + "низкая–средняя"
                can_preserve = (
                    difficulty in event_details or len(event_details) < 3
                )
                if can_preserve:
                    if difficulty not in event_details:
                        event_details = (*event_details, difficulty)
                    note_parts = [
                        part for part in note_parts
                        if part != legacy_difficulty
                    ]
                    participation_note = "; ".join(note_parts) or None
        audience_label = source.audience_label
        schedule_note = source.schedule_note
        teaser_source = (
            "municipal_cinema_teaser"
            if "todo_cultura_synopsis" in source.sources
            else (
                "municipal_activity_teaser"
                if "todo_cultura_summary" in source.sources
                else "municipal_agenda_teaser"
            )
        )
        teaser = (
            cached_translation(
                translation_cache_path, teaser_source, source.teaser_es
            ) if translation_cache_path is not None and source.teaser_es else None
        )
        activities = re.fullmatch(
            r"(для [^;]{5,50}); доступны (.{5,120})",
            participation_note or "", re.IGNORECASE,
        )
        if activities is not None:
            audience_label = audience_label or activities.group(1)
            teaser = teaser or "Доступны " + activities.group(2).rstrip(".") + "."
            participation_note = None
        if participation_note and re.match(
            r"^в будни перерыв \d{1,2}:\d{2}–\d{1,2}:\d{2}$",
            participation_note, re.IGNORECASE,
        ):
            schedule_note = schedule_note or participation_note
            participation_note = None
        ticket_price_cents, ticket_price_is_from = _display_ticket_price(source)
        cinema_title = title
        translated_film = title.partition(":")[2].strip()
        if (
            "turismo_cinema" in source.sources
            and source.title_es.casefold().startswith("cine de los lunes:")
            and not (
                title.casefold().startswith("кино по понедельникам:")
                and translated_film.strip("«»").strip()
                and (
                    ":" not in translated_film
                    or (
                        translated_film.startswith("«")
                        and translated_film.endswith("»")
                    )
                )
            )
        ):
            # An unrelated cached translation must not replace the verified
            # film title in the official Monday cinema row.
            cinema_title = source.title_es
        if (
            "turismo_cinema" in source.sources
            and source.start_date.weekday() == 0
            and source.place is not None
            and "biblioteca" in source.place.casefold()
        ):
            # A merged Todo Cultura title can replace the Turismo title while
            # retaining Turismo's verified Monday-cinema source marker.
            source_film = re.search(
                r"\bpel[ií]cula\s+[‘\"«]([^’\"»]{1,90})[’\"»]",
                source.title_es,
                re.IGNORECASE,
            )
            if source_film is not None:
                film = reviewed_translation(source_film.group(1))
                if film is None:
                    translated_film = re.search(
                        r"(?:Показ|Кинопоказ) фильма «([^«»]{1,90})»",
                        title,
                    )
                    film = (
                        translated_film.group(1)
                        if translated_film is not None
                        else spanish_fallback(source_film.group(1))
                    )
                cinema_title = f"Кино по понедельникам: «{film}»"
        result.append(
            Event(
                title=(
                    _cinema_title(cinema_title)
                    if "turismo_cinema" in source.sources else title
                ),
                starts_at=starts_at,
                ends_at=ends_at,
                place=place,
                active_until=(
                    source.end_date
                    if source.start_date != source.end_date else None
                ),
                active_from=(
                    source.start_date
                    if source.start_date != source.end_date else None
                ),
                category=source.category,
                ticket_price_cents=ticket_price_cents,
                ticket_price_is_from=ticket_price_is_from,
                ticket_url=source.ticket_url,
                participation_note=participation_note,
                registration_contact=source.registration_contact,
                registration_url=source.registration_url,
                capacity_limited=source.capacity_limited,
                duration_minutes=source.duration_minutes,
                audience_label=audience_label,
                details=event_details,
                place_query=source.place_query,
                meeting_point=meeting_point,
                schedule_note=schedule_note,
                access_note=source.access_note,
                teaser=teaser,
                programme_title=source.programme_title,
                admission_evidence=source.admission_evidence,
                programme_order=source.programme_order,
                session_group_key=(
                    None if source.programme_title else session_group_key
                ),
                is_final_day=(
                    source.start_date != source.end_date
                    and local_day == source.end_date
                ),
                image_url=source.image_url,
            )
        )
    return tuple(result)


async def municipal_translation_items(
    now: datetime,
    state_path: Path,
) -> Tuple[Tuple[str, str], ...]:
    """Return source identities and exact titles from the local catalog."""

    events = await _cached_current_events(now, state_path)
    session_plan = _session_source_plan(events)
    items = list(dict.fromkeys(
        ("municipal_agenda", display_source_title)
        for display_source_title, _ in session_plan
    ))
    items.extend((
        (
            "municipal_cinema_teaser"
            if "todo_cultura_synopsis" in event.sources
            else (
                "municipal_activity_teaser"
                if "todo_cultura_summary" in event.sources
                else "municipal_agenda_teaser"
            )
        ),
        event.teaser_es,
    ) for event in events if event.teaser_es)
    return tuple(items)
