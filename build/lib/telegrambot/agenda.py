"""Fetch today's official Agenda Guardamar events."""

import asyncio
import html
import json
import os
import re
import tempfile
import urllib.parse
from dataclasses import replace
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .gemini import GeminiError, translate_event_titles
from .event_translations import cached_title
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
MAX_CATALOG_EVENTS = 100
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


_TRANSPORT_DESCRIPTIONS = {
    "URL-POLICY": "адрес не принадлежит Agenda Guardamar",
    "REDIRECT": "получен недопустимый адрес ответа Agenda Guardamar",
    "CONTENT-TYPE": "сервер вернул содержимое не в формате HTML",
    "TIMEOUT": "сервер не ответил до истечения тайм-аута",
    "NETWORK": "не удалось установить сетевое соединение",
    "TOO-LARGE": "ответ превысил допустимый размер",
}


def _read_page(url: str) -> bytes:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_is_agenda_url,
            accepted_types=frozenset({"text/html"}),
            limit_bytes=PAGE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html",
                "Accept-Language": "es",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise AgendaError(
            f"Agenda Guardamar request failed: {exc.code}",
            code=exc.code,
            status=exc.status,
            description=(
                f"сервер вернул HTTP {exc.status}"
                if exc.status is not None
                else _TRANSPORT_DESCRIPTIONS.get(exc.code)
            ),
        ) from exc
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
    local_day: Optional[date],
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
    if local_day is not None and starts_at.date() != local_day:
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


def _ticket_url(value: str, starts_at: datetime) -> Optional[str]:
    """Accept only an occurrence-specific ticket URL on the official host."""

    url = urllib.parse.urljoin(AGENDA_URL, html.unescape(value))
    if not _is_agenda_url(url) or "/entradas/" not in url:
        return None
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    expected_date = starts_at.strftime("%d/%m/%Y")
    expected_time = starts_at.strftime("%H:%M")
    if query.get("webfecha") != [expected_date]:
        return None
    if query.get("webhora") != [expected_time]:
        return None
    return url


def _page_facts(
    payload: bytes,
) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Read bounded duration, regular price and meeting point from official text."""

    markup = payload.decode("cp1252", "replace")
    text = " ".join(
        html.unescape(re.sub(r"<[^>]+>", " ", markup)).split()
    )
    duration = None
    duration_match = re.search(
        r"Duraci[oó]n\s+(\d{1,2})\s+horas?\s+aprox",
        text,
        re.IGNORECASE,
    )
    if duration_match is not None:
        candidate = int(duration_match.group(1))
        if 1 <= candidate <= 12:
            duration = candidate
    price = None
    price_match = re.search(
        r"(?:Regular|Precio|Preu)\s*:\s*"
        r"(\d{1,4})(?:[,.](\d{1,2}))?\s*[€\x80]",
        text,
        re.IGNORECASE,
    )
    if price_match is not None:
        euros = int(price_match.group(1))
        cents = int((price_match.group(2) or "0").ljust(2, "0"))
        candidate = euros * 100 + cents
        if 0 <= candidate <= 100_000:
            price = candidate
    elif re.search(
        r"\b(?:entrada|actividad|acceso)\s+(?:es\s+)?"
        r"(?:libre|gratuit[oa])\b",
        text,
        re.IGNORECASE,
    ):
        price = 0
    place = None
    place_match = re.search(
        r"Punto de encuentro\s*:\s*(.{1,120}?)"
        r"(?=\s+(?:Itinerario|Distancia|Duraci[oó]n|ENTRADA|Regular|Precio|Preu)\b|$)",
        text,
        re.IGNORECASE,
    )
    if place_match is not None:
        place = " ".join(html.unescape(place_match.group(1)).split())
    return duration, price, place


def _page_sessions(payload: bytes) -> Tuple[Tuple[datetime, str], ...]:
    """Return the bounded dated sessions advertised by the official page."""

    text = payload.decode("cp1252", "replace")
    result = []
    seen = set()
    ticket_path = None
    for match in re.finditer(
        r"href\s*=\s*['\"]?([^'\"\s>]+/entradas/[^'\"\s>]+)",
        text,
        re.IGNORECASE,
    ):
        raw_url = html.unescape(match.group(1))
        parsed_url = urllib.parse.urlparse(
            urllib.parse.urljoin(AGENDA_URL, raw_url)
        )
        if ticket_path is None:
            ticket_path = parsed_url.path
        elif parsed_url.path != ticket_path:
            continue
        query = urllib.parse.parse_qs(
            parsed_url.query
        )
        raw_date = (query.get("webfecha") or [None])[0]
        raw_time = (query.get("webhora") or [None])[0]
        if not isinstance(raw_date, str) or not isinstance(raw_time, str):
            continue
        try:
            starts_at = datetime.strptime(
                f"{raw_date} {raw_time}", "%d/%m/%Y %H:%M"
            ).replace(tzinfo=GUARDAMAR_TIMEZONE)
        except ValueError:
            continue
        url = _ticket_url(raw_url, starts_at)
        key = starts_at
        if url is not None and key not in seen:
            seen.add(key)
            result.append((starts_at, url))
            if len(result) == MAX_CATALOG_EVENTS:
                break
    result.sort(key=lambda item: item[0])
    return tuple(result)


def normalize_event_pages(
    payload: bytes,
    local_day: Optional[date],
) -> Tuple[Event, ...]:
    """Return all validated occurrences from one official event page."""

    parser = _JsonLdParser()
    parser.feed(payload.decode("cp1252", "replace"))
    base_event = None
    for document in parser.documents:
        decoded = _decode_json_ld(document)
        if decoded is None:
            continue
        for candidate in _json_objects(decoded):
            event = _event_from_mapping(candidate, None)
            if event is not None:
                base_event = event
                break
        if base_event is not None:
            break
    if base_event is None:
        return ()

    duration_hours, price_cents, meeting_point = _page_facts(payload)
    place = (
        f"место встречи — {meeting_point}"
        if meeting_point is not None
        else base_event.place or _calendar_place(payload)
    )
    if (
        place is not None
        and place.casefold() == "castell"
        and any(
            marker in base_event.title.casefold()
            for marker in ("sand memories", "memoria de arena")
        )
    ):
        place = "место встречи — Castillo de Guardamar"
    sessions = _page_sessions(payload)
    if not sessions:
        sessions = ((base_event.starts_at, ""),)
    result = []
    for starts_at, ticket_url in sessions:
        if local_day is not None and starts_at.date() != local_day:
            continue
        ends_at = base_event.ends_at
        if duration_hours is not None:
            ends_at = starts_at + timedelta(hours=duration_hours)
        elif len(sessions) > 1 or starts_at != base_event.starts_at:
            ends_at = None
        result.append(replace(
            base_event,
            starts_at=starts_at,
            ends_at=ends_at,
            place=place,
            ticket_price_cents=price_cents,
            ticket_url=ticket_url or None,
        ))
    return tuple(result)


def _write_agenda_snapshot(path: Path, now: datetime, events: Tuple[Event, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 2,
        "fetched_at": now.isoformat(),
        "events": [
            {
                "title": event.title,
                "starts_at": event.starts_at.isoformat()
                if event.starts_at else None,
                "ends_at": event.ends_at.isoformat()
                if event.ends_at else None,
                "place": event.place,
                "ticket_price_cents": event.ticket_price_cents,
                "ticket_url": event.ticket_url,
            }
            for event in events
        ],
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
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


def _load_agenda_snapshot(path: Path) -> Tuple[Event, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") not in {1, 2}:
            raise ValueError
        raw_events = data.get("events")
        if (
            not isinstance(raw_events, list)
            or len(raw_events) > MAX_CATALOG_EVENTS
        ):
            raise ValueError
        events = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                raise ValueError
            title = raw.get("title")
            starts_raw = raw.get("starts_at")
            if not isinstance(title, str) or not isinstance(starts_raw, str):
                raise ValueError
            starts_at = datetime.fromisoformat(starts_raw)
            ends_raw = raw.get("ends_at")
            ends_at = (
                datetime.fromisoformat(ends_raw)
                if isinstance(ends_raw, str)
                else None
            )
            if starts_at.tzinfo is None or (
                ends_at is not None and ends_at.tzinfo is None
            ):
                raise ValueError
            place = raw.get("place")
            if place is not None and not isinstance(place, str):
                raise ValueError
            ticket_price_cents = raw.get("ticket_price_cents")
            if ticket_price_cents is not None and (
                not isinstance(ticket_price_cents, int)
                or not 0 <= ticket_price_cents <= 100_000
            ):
                raise ValueError
            ticket_url = raw.get("ticket_url")
            if ticket_url is not None:
                if not isinstance(ticket_url, str):
                    raise ValueError
                normalized_ticket_url = _ticket_url(ticket_url, starts_at)
                if normalized_ticket_url is None:
                    raise ValueError
                ticket_url = normalized_ticket_url
            events.append(Event(
                title=title,
                starts_at=starts_at.astimezone(GUARDAMAR_TIMEZONE),
                ends_at=ends_at.astimezone(GUARDAMAR_TIMEZONE)
                if ends_at else None,
                place=place,
                ticket_price_cents=ticket_price_cents,
                ticket_url=ticket_url,
            ))
        return tuple(events)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AgendaError(
            "Agenda Guardamar snapshot is invalid",
            code="SNAPSHOT",
            description="локальный каталог Agenda Guardamar повреждён",
        ) from exc
async def _collect_agenda_catalog(now: datetime) -> Tuple[Event, ...]:
    """Collect a bounded window of structured Agenda Guardamar events."""
    index = await asyncio.to_thread(_read_page, AGENDA_URL)
    links = extract_event_links(index)
    if not links:
        raise AgendaError(
            "Agenda Guardamar index contained no event links",
            code="INDEX-EMPTY",
            description="страница программы не содержит ссылок на мероприятия",
        )
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
    horizon = local_day + timedelta(days=45)
    for payload in successful_payloads:
        for event in normalize_event_pages(payload, None):
            if event.starts_at is None or not (
                local_day <= event.starts_at.date() <= horizon
            ):
                continue
            key = (event.title.casefold(), event.starts_at)
            if key not in seen:
                seen.add(key)
                events.append(event)
    if not events:
        raise AgendaError(
            "Agenda Guardamar event details contained no usable events",
            code="DETAILS-INVALID",
            description="страницы мероприятий не содержат пригодных данных",
        )
    events.sort(key=lambda item: (item.starts_at, item.title.casefold()))
    return tuple(events)


async def refresh_agenda_catalog(
    now: datetime,
    state_path: Path,
) -> Tuple[Event, ...]:
    """Refresh and atomically store the structured ticketed-event catalog."""

    events = await _collect_agenda_catalog(now)
    await asyncio.to_thread(_write_agenda_snapshot, state_path, now, events)
    return events


async def fetch_today_events(
    now: datetime,
    gemini_api_key: str = "",
    state_path: Optional[Path] = None,
    translation_cache_path: Optional[Path] = None,
) -> Tuple[Event, ...]:
    """Read today's cached events, or use the legacy direct collection path."""

    if state_path is None:
        events = list(await _collect_agenda_catalog(now))
    else:
        catalog = await asyncio.to_thread(_load_agenda_snapshot, state_path)
        local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
        events = [
            event for event in catalog
            if event.starts_at is not None
            and event.starts_at.date() == local_day
        ]
    if translation_cache_path is not None:
        events = [
            replace(
                event,
                title=cached_title(
                    translation_cache_path,
                    "agenda_guardamar",
                    event.title,
                ),
            )
            for event in events
        ]
    elif gemini_api_key and events:
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


async def agenda_translation_items(
    now: datetime,
    state_path: Path,
) -> Tuple[Tuple[str, str], ...]:
    """Return only today's source titles from the local catalog."""

    events = await asyncio.to_thread(_load_agenda_snapshot, state_path)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    return tuple(
        ("agenda_guardamar", event.title)
        for event in events
        if event.starts_at is not None
        and event.starts_at.date() == local_day
    )


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
