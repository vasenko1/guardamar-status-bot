"""Fetch today's official Agenda Guardamar events."""

import asyncio
import html
import http.client
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .gemini import GeminiError, translate_event_titles
from .holidays import is_market_day
from .models import Event

AGENDA_URL = (
    "https://www.agendaguardamar.com/"
    "PROGRAMACION-ESPECTACULOS.html"
)
AGENDA_HOSTS = {"agendaguardamar.com", "www.agendaguardamar.com"}
REQUEST_TIMEOUT_SECONDS = 10
PAGE_LIMIT_BYTES = 300_000
MAX_EVENT_LINKS = 12
MAX_EVENT_CONCURRENCY = 3
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_IGNORED_PLACES = {"ayuntamientoguardamardelsegura"}
_CALENDAR_LINK_PATTERN = re.compile(
    rb'href="([^"]*google\.com/calendar/render[^"]*)"',
    re.IGNORECASE,
)


class AgendaError(RuntimeError):
    """An operator-safe Agenda Guardamar source failure."""

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


def _is_agenda_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in AGENDA_HOSTS


class _AgendaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if not _is_agenda_url(new_url):
            raise AgendaError(
                "Agenda Guardamar redirected outside its official hosts",
                code="REDIRECT",
                description=(
                    "сервер перенаправил запрос за пределы Agenda Guardamar"
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


class _EventLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href and "/espectaculo/" in href and href.endswith(".html"):
            self.links.append(href)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capturing = False
        self._chunks: List[str] = []
        self.documents: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        if tag.casefold() != "script":
            return
        content_type = (dict(attrs).get("type") or "").casefold()
        if content_type == "application/ld+json":
            self._capturing = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._capturing:
            self.documents.append("".join(self._chunks))
            self._capturing = False
            self._chunks = []


def _repair_known_property_quote(document: str) -> str:
    """Remove only Agenda's observed quote after a closed object line."""

    lines = document.splitlines(keepends=True)
    for index in range(len(lines) - 1):
        if (
            lines[index].rstrip("\r\n").rstrip().endswith('},"')
            and lines[index + 1].lstrip().startswith(
                ('"startDate"', '"endDate"')
            )
        ):
            newline = (
                "\r\n"
                if lines[index].endswith("\r\n")
                else "\n" if lines[index].endswith("\n") else ""
            )
            content = lines[index][
                : len(lines[index]) - len(newline)
            ]
            lines[index] = content[:-1] + newline
    return "".join(lines)


def _remove_trailing_json_commas(document: str) -> str:
    """Remove commas before containers only when outside JSON strings."""

    result: List[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(document):
        character = document[index]
        if in_string:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            result.append(character)
            index += 1
            continue
        if character == ",":
            lookahead = index + 1
            while (
                lookahead < len(document)
                and document[lookahead].isspace()
            ):
                lookahead += 1
            if (
                lookahead < len(document)
                and document[lookahead] in "}]"
            ):
                index += 1
                continue
        result.append(character)
        index += 1
    return "".join(result)


def _decode_json_ld(document: str) -> Optional[Any]:
    try:
        return json.loads(document)
    except json.JSONDecodeError:
        repaired = _repair_known_property_quote(document)
        repaired = _remove_trailing_json_commas(repaired)
        if repaired == document:
            return None
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


def _read_page(url: str) -> bytes:
    if not _is_agenda_url(url):
        raise AgendaError(
            "Agenda Guardamar URL is not allowed",
            code="URL-POLICY",
            description="адрес не принадлежит Agenda Guardamar",
        )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "Accept-Language": "es",
            "User-Agent": "GuardamarMorningDigest/0.12",
        },
    )
    opener = urllib.request.build_opener(_AgendaRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            if not _is_agenda_url(response.geturl()):
                raise AgendaError(
                    "Agenda Guardamar returned an unexpected redirect",
                    code="REDIRECT",
                    description=(
                        "получен недопустимый адрес ответа Agenda Guardamar"
                    ),
                )
            if response.headers.get_content_type() != "text/html":
                raise AgendaError(
                    "Agenda Guardamar returned an unexpected content type",
                    code="CONTENT-TYPE",
                    description="сервер вернул содержимое не в формате HTML",
                )
            payload = response.read(PAGE_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise AgendaError(
            f"Agenda Guardamar HTTP status {exc.code}",
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
        raise AgendaError(
            "Agenda Guardamar request timed out"
            if timed_out
            else "Agenda Guardamar network request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
            description=(
                "сервер не ответил до истечения тайм-аута"
                if timed_out
                else "не удалось установить сетевое соединение"
            ),
        ) from exc
    if len(payload) > PAGE_LIMIT_BYTES:
        raise AgendaError(
            "Agenda Guardamar response was too large",
            code="TOO-LARGE",
            description="ответ превысил допустимый размер",
        )
    return payload


def extract_event_links(payload: bytes) -> Tuple[str, ...]:
    """Return a small unique set of official event detail URLs."""

    parser = _EventLinkParser()
    parser.feed(payload.decode("iso-8859-1", "replace"))
    result: List[str] = []
    seen = set()
    for href in parser.links:
        url = urllib.parse.urljoin(AGENDA_URL, href)
        if _is_agenda_url(url) and url not in seen:
            seen.add(url)
            result.append(url)
            if len(result) == MAX_EVENT_LINKS:
                break
    return tuple(result)


def _json_objects(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _json_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _json_objects(nested)


def _event_from_mapping(
    candidate: Dict[str, Any],
    local_day: date,
) -> Optional[Event]:
    event_type = candidate.get("@type")
    event_types = (
        event_type
        if isinstance(event_type, list)
        else [event_type]
    )
    if not any(
        isinstance(value, str)
        and value.casefold().endswith("event")
        for value in event_types
    ):
        return None
    title = candidate.get("name")
    start_value = candidate.get("startDate")
    if not isinstance(title, str) or not isinstance(start_value, str):
        return None
    title = " ".join(html.unescape(title).split())
    if not 1 <= len(title) <= 120:
        return None
    try:
        starts_at = datetime.fromisoformat(start_value)
    except ValueError:
        return None
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=GUARDAMAR_TIMEZONE)
    else:
        starts_at = starts_at.astimezone(GUARDAMAR_TIMEZONE)
    if starts_at.date() != local_day:
        return None

    ends_at = None
    end_value = candidate.get("endDate")
    if isinstance(end_value, str):
        try:
            ends_at = datetime.fromisoformat(end_value)
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=GUARDAMAR_TIMEZONE)
            else:
                ends_at = ends_at.astimezone(GUARDAMAR_TIMEZONE)
            if ends_at < starts_at:
                ends_at = None
        except ValueError:
            ends_at = None

    place = None
    location = candidate.get("location")
    raw_place = (
        location.get("name")
        if isinstance(location, dict)
        else location
    )
    if isinstance(raw_place, str):
        normalized_place = " ".join(html.unescape(raw_place).split())
        if (
            1 <= len(normalized_place) <= 120
            and normalized_place.casefold() not in _IGNORED_PLACES
        ):
            place = normalized_place
    return Event(
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        place=place,
    )


def _calendar_place(payload: bytes) -> Optional[str]:
    """Recover the official venue when the page's JSON-LD omits it."""

    match = _CALENDAR_LINK_PATTERN.search(payload)
    if match is None:
        return None
    raw_url = html.unescape(
        match.group(1).decode("utf-8", "replace")
    )
    values = urllib.parse.parse_qs(
        urllib.parse.urlparse(raw_url).query
    ).get("location")
    if not values:
        return None
    parts = [
        " ".join(part.split())
        for part in values[0].split(",")
        if " ".join(part.split())
    ]
    parts = [
        part
        for part in parts
        if not re.fullmatch(r"\d{5}", part)
        and part.casefold() != "guardamar del segura"
    ]
    if not parts:
        return None
    if (
        len(parts) > 1
        and parts[1].casefold() in parts[0].casefold()
    ):
        place = parts[1]
    else:
        place = parts[0]
    if not 1 <= len(place) <= 120:
        return None
    if place.isupper():
        place = place.title().replace(" De ", " de ")
    return place


def normalize_event_page(
    payload: bytes,
    local_day: date,
) -> Optional[Event]:
    """Return one event only from a valid JSON-LD object for local_day."""

    parser = _JsonLdParser()
    parser.feed(payload.decode("iso-8859-1", "replace"))
    for document in parser.documents:
        decoded = _decode_json_ld(document)
        if decoded is None:
            continue
        for candidate in _json_objects(decoded):
            event = _event_from_mapping(candidate, local_day)
            if event is not None:
                if event.place is None:
                    place = _calendar_place(payload)
                    if place is not None:
                        event = replace(event, place=place)
                return event
    return None


async def fetch_today_events(
    now: datetime,
    gemini_api_key: str = "",
) -> Tuple[Event, ...]:
    """Fetch today's official events with three bounded detail workers."""

    index = await asyncio.to_thread(_read_page, AGENDA_URL)
    links = extract_event_links(index)
    if not links:
        return ()
    semaphore = asyncio.Semaphore(MAX_EVENT_CONCURRENCY)

    async def read_detail(link: str) -> Optional[bytes]:
        async with semaphore:
            try:
                return await asyncio.to_thread(_read_page, link)
            except AgendaError:
                return None

    payloads = await asyncio.gather(
        *(read_detail(link) for link in links)
    )
    successful_payloads = [
        payload for payload in payloads if payload is not None
    ]
    if not successful_payloads:
        raise AgendaError(
            "Agenda Guardamar event details were unavailable",
            code="DETAILS-UNAVAILABLE",
            description="не удалось получить страницы мероприятий",
        )

    events: List[Event] = []
    seen = set()
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for payload in successful_payloads:
        event = normalize_event_page(payload, local_day)
        if event is None:
            continue
        key = (event.title.casefold(), event.starts_at)
        if key not in seen:
            seen.add(key)
            events.append(event)
    events.sort(key=lambda item: (item.starts_at, item.title.casefold()))
    if gemini_api_key and events:
        try:
            titles = await translate_event_titles(
                gemini_api_key,
                [event.title for event in events],
            )
        except GeminiError as exc:
            raise AgendaError(
                "Agenda Guardamar event translation failed",
                code=exc.diagnostic_code,
                status=exc.server_status,
                description=exc.safe_description,
            ) from exc
        events = [
            replace(event, title=title)
            for event, title in zip(events, titles)
        ]
    return tuple(events)


def recurring_events(now: datetime) -> Tuple[Event, ...]:
    """Return official recurring events determined only by the local date."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if local_day.weekday() == 6:
        return (
            Event(
                title="Рынок Campo de Guardamar",
                starts_at=datetime(
                    local_day.year,
                    local_day.month,
                    local_day.day,
                    7,
                    tzinfo=GUARDAMAR_TIMEZONE,
                ),
                ends_at=datetime(
                    local_day.year,
                    local_day.month,
                    local_day.day,
                    16,
                    tzinfo=GUARDAMAR_TIMEZONE,
                ),
                place="Camino del Raso, 15",
            ),
        )
    if not is_market_day(local_day):
        return ()
    opening_hour = 7 if 6 <= local_day.month <= 9 else 8
    return (
        Event(
            title="Рынок",
            starts_at=datetime(
                local_day.year,
                local_day.month,
                local_day.day,
                opening_hour,
                tzinfo=GUARDAMAR_TIMEZONE,
            ),
            ends_at=datetime(
                local_day.year,
                local_day.month,
                local_day.day,
                13,
                30,
                tzinfo=GUARDAMAR_TIMEZONE,
            ),
            place="парковка La Redonda",
        ),
    )


def requires_market_exception_check(now: datetime) -> bool:
    """Return whether today's municipal market needs a Mayor-channel check."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    return is_market_day(local_day)
