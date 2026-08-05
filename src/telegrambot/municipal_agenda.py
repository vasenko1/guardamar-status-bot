"""Monthly official municipal agenda poster with a small local snapshot."""

import asyncio
import hashlib
import html
import http.client
import json
import logging
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .gemini import (
    GeminiError,
    extract_agenda_events,
    extract_agenda_text_events,
    translate_event_titles,
    verify_agenda_poster_events,
)
from .event_translations import cached_title
from .models import Event
from .diagnostics import SourceDiagnostic, source_error
from .todo_cultura import TodoCulturaError, fetch_latest_program

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


class _MunicipalRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if not _is_allowed_url(new_url, self.allowed_hosts):
            raise MunicipalAgendaError(
                "Municipal agenda redirected outside official hosts",
                code="REDIRECT",
                description=(
                    "сервер перенаправил запрос за пределы официального сайта"
                ),
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _read_url(
    url: str,
    allowed_hosts: set[str],
    limit: int,
) -> Tuple[bytes, str]:
    if not _is_allowed_url(url, allowed_hosts):
        raise MunicipalAgendaError(
            "Municipal agenda URL is not allowed",
            code="URL-POLICY",
            description="адрес не принадлежит официальной афише",
        )
    page_request = allowed_hosts == PAGE_HOSTS
    accepted_types = (
        {"text/html"}
        if page_request
        else {"image/jpeg", "image/png", "image/webp"}
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": (
                "text/html"
                if page_request
                else "image/jpeg,image/png,image/webp"
            ),
            "User-Agent": "GuardamarMorningDigest/0.12",
        },
    )
    opener = urllib.request.build_opener(
        _MunicipalRedirectHandler(allowed_hosts)
    )
    try:
        with opener.open(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            if not _is_allowed_url(response.geturl(), allowed_hosts):
                raise MunicipalAgendaError(
                    "Unexpected municipal agenda redirect",
                    code="REDIRECT",
                    description=(
                        "получен недопустимый адрес ответа официальной афиши"
                    ),
                )
            mime_type = response.headers.get_content_type()
            if mime_type not in accepted_types:
                raise MunicipalAgendaError(
                    "Municipal agenda returned an unexpected content type",
                    code="CONTENT-TYPE",
                    description=(
                        "официальная афиша вернула неожиданный формат"
                    ),
                )
            payload = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise MunicipalAgendaError(
            f"Municipal agenda returned HTTP {exc.code}",
            code=f"HTTP-{exc.code}",
            status=exc.code,
            description=f"сервер вернул HTTP {exc.code}",
        ) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, (TimeoutError, socket.timeout))
        )
        raise MunicipalAgendaError(
            "Municipal agenda request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
            description=(
                "сервер не ответил до истечения тайм-аута"
                if timed_out
                else "не удалось установить сетевое соединение"
            ),
        ) from exc
    if len(payload) > limit:
        raise MunicipalAgendaError(
            "Municipal agenda response was too large",
            code="TOO-LARGE",
            description="ответ превысил допустимый размер",
        )
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


def _same_occurrence(left: SourceEvent, right: SourceEvent) -> bool:
    if (
        left.start_date != right.start_date
        or left.end_date != right.end_date
        or left.start_time != right.start_time
    ):
        return False
    return _word_overlap(left.title_es, right.title_es) >= 0.5


def _poster_conflicts_with_text(
    text_event: SourceEvent,
    poster_event: SourceEvent,
) -> bool:
    """Detect a less reliable poster rendering of a text occurrence."""

    dates_overlap = not (
        poster_event.end_date < text_event.start_date
        or poster_event.start_date > text_event.end_date
    )
    if not dates_overlap:
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
        duplicate_index = next(
            (
                index
                for index, text_event in enumerate(merged)
                if _same_occurrence(text_event, poster_event)
                or _poster_conflicts_with_text(text_event, poster_event)
            ),
            None,
        )
        if duplicate_index is None:
            merged.append(poster_event)
            continue
        current = merged[duplicate_index]
        merged[duplicate_index] = SourceEvent(
            **{
                **current.__dict__,
                "sources": tuple(dict.fromkeys(
                    current.sources + poster_event.sources
                )),
            }
        )
    return tuple(merged[:MAX_EVENTS])


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
        event = SourceEvent(
            title_es=_clean_text(raw.get("title_es"), 120) or "",
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            place=_clean_text(raw.get("place"), 120),
            category="event" if category == "workshop" else category,
            sources=(source,),
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
        "version": 2,
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
        if not isinstance(data, dict) or data.get("version") not in {1, 2}:
            raise ValueError
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if fetched_at.tzinfo is None:
            raise ValueError
        events = []
        for raw in data["events"]:
            normalized = normalize_extraction(
                {"events": [raw]},
                source=(
                    raw.get("sources", ["mupi"])[0]
                    if isinstance(raw, dict)
                    and isinstance(raw.get("sources", ["mupi"]), list)
                    and raw.get("sources", ["mupi"])
                    else "mupi"
                ),
            )[0]
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


def _apply_reviewed_corrections(
    poster_url: str,
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Repair facts manually verified against a specific official poster."""

    parsed = urllib.parse.urlparse(poster_url)
    poster_name = parsed.path.rsplit("/", 1)[-1].casefold()
    is_july_2026 = (
        parsed.scheme == "https"
        and parsed.hostname in POSTER_HOSTS
        and "/wp-content/uploads/2026/07/" in parsed.path.casefold()
        and poster_name.startswith("mupi-julio-2026")
        and poster_name.endswith((".jpg", ".jpeg", ".png", ".webp"))
    )
    is_august_2026 = (
        parsed.scheme == "https"
        and parsed.hostname in POSTER_HOSTS
        and "/wp-content/uploads/2026/07/" in parsed.path.casefold()
        and poster_name == "mupi-agosto-2026-scaled.jpg"
    )
    if not is_july_2026 and not is_august_2026:
        return events
    if is_august_2026:
        reviewed = (
            SourceEvent(
                title_es=(
                    "Torneo de tenis 24.º Open Real Villa de Guardamar, "
                    "Memorial Pepe y Juan Tendero 2026"
                ),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
                start_time=None,
                end_time=None,
                place="Polideportivo Municipal Guardamar",
                category="event",
                sources=("mupi_reviewed",),
            ),
            SourceEvent(
                title_es=(
                    "Exposición de pintura y escultura: "
                    "Mediterráneo, el lenguaje del agua"
                ),
                start_date=date(2026, 6, 19),
                end_date=date(2026, 8, 14),
                start_time=None,
                end_time=None,
                place="Sala de exposiciones Casa de Cultura",
                category="exhibition",
                sources=("mupi_reviewed",),
            ),
            *tuple(
                SourceEvent(
                    title_es="Rutas nocturnas: senderismo y dinámica grupal",
                    start_date=date(2026, 8, day),
                    end_date=date(2026, 8, day),
                    start_time="22:15",
                    end_time="00:15",
                    place=None,
                    category="event",
                    sources=("mupi_reviewed",),
                )
                for day in (7, 14, 21, 28)
            ),
            SourceEvent(
                title_es="Taller de cultura K-Pop y TikTok",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
                start_time="19:00",
                end_time="21:00",
                place="Centro Social Juvenil",
                category="event",
                sources=("mupi_reviewed",),
            ),
            *tuple(
                SourceEvent(
                    title_es=title,
                    start_date=date(2026, 8, day),
                    end_date=date(2026, 8, day),
                    start_time="19:00",
                    end_time="21:00",
                    place="Centro Social Juvenil",
                    category="event",
                    sources=("mupi_reviewed", "todo_cultura_reviewed"),
                )
                for day, title in (
                    (8, "Taller de baterías"),
                    (15, "Taller de guitarras eléctricas"),
                    (22, "Taller de música electrónica"),
                    (29, "Taller de canto"),
                )
            ),
        )
        filtered = []
        for event in events:
            title = event.title_es.casefold()
            if (
                "rutas nocturnas" in title
                or "senderismo" in title and "dinámica" in title
                or "mediterráneo" in title and "lenguaje del agua" in title
                or "tendero" in title
                or "open real villa" in title
                or "open" in title and "villa de guardamar" in title
                or "k-pop" in title
                or "tik tok" in title
                or "tiktok" in title
                or "taller de bater" in title
                or "taller de guitarra" in title
                or "taller de música electrónica" in title
                or "taller de musica electronica" in title
                or "taller de canto" in title
            ):
                continue
            filtered.append(event)
        return tuple(filtered) + reviewed
    corrected = []
    entropia_added = False
    for event in events:
        title = event.title_es.casefold()
        if "conchi montes" not in title and "entrop" not in title:
            corrected.append(event)
            continue
        if not entropia_added:
            corrected.append(
                SourceEvent(
                    title_es=(
                        "Exposición de pintura «Entropía» "
                        "de Conchi Montes"
                    ),
                    start_date=date(2026, 7, 3),
                    end_date=date(2026, 7, 29),
                    start_time="08:00",
                    end_time="14:00",
                    place="Biblioteca Pública Municipal",
                    category="exhibition",
                    sources=event.sources,
                )
            )
            entropia_added = True
    return tuple(corrected)


def _merge_reviewed_text_agenda(
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Keep verified current-month facts when the poster advances early."""

    additions = []
    if not any(
        "conchi montes" in event.title_es.casefold()
        or "entrop" in event.title_es.casefold()
        for event in events
    ):
        additions.append(SourceEvent(
            title_es="Exposición de pintura «Entropía» de Conchi Montes",
            start_date=date(2026, 7, 3),
            end_date=date(2026, 7, 29),
            start_time="08:00",
            end_time="14:00",
            place="Biblioteca Pública Municipal",
            category="exhibition",
        ))
    return events + tuple(additions)


def _apply_reviewed_daily_schedules(
    events: Tuple[SourceEvent, ...],
    local_day: date,
) -> Tuple[SourceEvent, ...]:
    """Apply event-specific hours published in the official text agenda."""

    scheduled = []
    for event in events:
        normalized = event.title_es.casefold()
        is_mediterraneo = (
            "mediterráneo" in normalized
            and "lenguaje del agua" in normalized
            and event.start_date == date(2026, 6, 19)
            and event.end_date == date(2026, 8, 14)
        )
        is_vira_degliarenko = (
            "vira deg" in normalized
            and event.start_date == date(2026, 7, 31)
            and event.end_date == date(2026, 8, 21)
        )
        if is_vira_degliarenko:
            if local_day.weekday() >= 5:
                continue
            scheduled.append(SourceEvent(
                title_es="Exposición de pintura «Luz a pesar del dolor» de Vira Degliarenko",
                start_date=event.start_date,
                end_date=event.end_date,
                start_time="08:00",
                end_time="14:00",
                place="Biblioteca Municipal Guardamar del Segura",
                category="exhibition",
                sources=event.sources,
            ))
            continue
        if not is_mediterraneo:
            scheduled.append(event)
            continue
        scheduled.append(
            SourceEvent(
                title_es=(
                    "Exposición de pintura y escultura: "
                    "Mediterráneo, el lenguaje del agua"
                ),
                start_date=event.start_date,
                end_date=event.end_date,
                start_time=None,
                end_time=None,
                place="Sala de exposiciones Casa de Cultura",
                category="exhibition",
                sources=event.sources,
            )
        )
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
            )
            if not text_events:
                raise MunicipalAgendaError(
                    "Official text agenda extraction was empty",
                    code="EMPTY-TEXT",
                    description="официальная текстовая программа не дала событий",
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
        todo_events = old_todo_events
        todo_program = None
        try:
            todo_program = await fetch_latest_program(local_now.date())
            if (
                isinstance(todo_source, dict)
                and todo_source.get("sha256") == todo_program.sha256
                and todo_source.get("date") == local_now.date().isoformat()
            ):
                todo_events = old_todo_events
            else:
                todo_result = await extract_agenda_text_events(
                    api_key,
                    todo_program.text,
                )
                todo_month = local_now.strftime("%Y-%m")
                todo_result = {**todo_result, "month": todo_month}
                todo_events = normalize_extraction_candidates(
                    todo_result,
                    todo_month,
                    "todo_cultura",
                )
        except (TodoCulturaError, GeminiError, MunicipalAgendaError) as exc:
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
                old_events,
                local_now.date(),
            )
        source_state = {
            "turismo_html": {
                "url": AGENDA_PAGE_URL,
                "sha256": page_hash,
                "month": text_month or None,
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
        if todo_program is not None:
            source_state["todo_cultura"] = {
                "url": todo_program.source_url,
                "sha256": todo_program.sha256,
                "modified": todo_program.modified,
                "date": local_now.date().isoformat(),
                "checked_at": now.isoformat(),
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
    events = _merge_reviewed_text_agenda(events)
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
