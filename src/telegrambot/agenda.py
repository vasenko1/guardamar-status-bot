"""Fetch today's official Agenda Guardamar events."""

import asyncio
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

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
MAX_DAILY_EVENTS = 2
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

_NAME_PATTERN = re.compile(
    r'"name"\s*:\s*"((?:\\.|[^"\\])*)"',
)
_START_PATTERN = re.compile(
    r'"startDate"\s*:\s*"([^"]+)"',
)
_END_PATTERN = re.compile(
    r'"endDate"\s*:\s*"([^"]+)"',
)
_LOCATION_PATTERN = re.compile(
    r'"location"\s*:\s*\{.*?"name"\s*:\s*"((?:\\.|[^"\\])*)"',
    re.DOTALL,
)


class AgendaError(RuntimeError):
    """Raised when official Agenda Guardamar data cannot be used safely."""


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


def _read_page(url: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in AGENDA_HOSTS:
        raise AgendaError("Agenda Guardamar URL is not allowed")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": "GuardamarMorningDigest/0.4",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in AGENDA_HOSTS:
                raise AgendaError(
                    "Agenda Guardamar returned an unexpected redirect"
                )
            payload = response.read(PAGE_LIMIT_BYTES + 1)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise AgendaError("Agenda Guardamar request failed") from exc
    if len(payload) > PAGE_LIMIT_BYTES:
        raise AgendaError("Agenda Guardamar response was too large")
    return payload


def extract_event_links(payload: bytes) -> Tuple[str, ...]:
    """Return a small unique set of official event detail URLs."""

    parser = _EventLinkParser()
    parser.feed(payload.decode("iso-8859-1", "replace"))
    result: List[str] = []
    seen = set()
    for href in parser.links:
        url = urllib.parse.urljoin(AGENDA_URL, href)
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme == "https"
            and parsed.hostname in AGENDA_HOSTS
            and url not in seen
        ):
            seen.add(url)
            result.append(url)
            if len(result) == MAX_EVENT_LINKS:
                break
    return tuple(result)


def normalize_event_page(
    payload: bytes,
    local_day: date,
) -> Optional[Event]:
    """Return one event only when its official start is on local_day."""

    page = payload.decode("iso-8859-1", "replace")
    name_match = _NAME_PATTERN.search(page)
    start_match = _START_PATTERN.search(page)
    if name_match is None or start_match is None:
        return None
    try:
        title = json.loads(f'"{name_match.group(1)}"')
        starts_at = datetime.fromisoformat(start_match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(title, str):
        return None
    title = " ".join(html.unescape(title).split())
    if not title or len(title) > 120:
        return None
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=GUARDAMAR_TIMEZONE)
    else:
        starts_at = starts_at.astimezone(GUARDAMAR_TIMEZONE)
    if starts_at.date() != local_day:
        return None
    ends_at = None
    end_match = _END_PATTERN.search(page)
    if end_match is not None:
        try:
            ends_at = datetime.fromisoformat(end_match.group(1))
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=GUARDAMAR_TIMEZONE)
            else:
                ends_at = ends_at.astimezone(GUARDAMAR_TIMEZONE)
            if ends_at < starts_at:
                ends_at = None
        except ValueError:
            ends_at = None
    place = None
    location_match = _LOCATION_PATTERN.search(page)
    if location_match is not None:
        try:
            decoded_place = json.loads(f'"{location_match.group(1)}"')
        except json.JSONDecodeError:
            decoded_place = None
        if isinstance(decoded_place, str):
            decoded_place = " ".join(html.unescape(decoded_place).split())
            if 1 <= len(decoded_place) <= 120:
                place = decoded_place
    return Event(
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        place=place,
    )


async def fetch_today_events(now: datetime) -> Tuple[Event, ...]:
    """Fetch at most two official events scheduled for today."""

    index = await asyncio.to_thread(_read_page, AGENDA_URL)
    links = extract_event_links(index)
    events: List[Event] = []
    seen = set()
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for link in links:
        try:
            payload = await asyncio.to_thread(_read_page, link)
        except AgendaError:
            continue
        event = normalize_event_page(payload, local_day)
        if event is None:
            continue
        key = (event.title.casefold(), event.starts_at)
        if key not in seen:
            seen.add(key)
            events.append(event)
    events.sort(key=lambda item: (item.starts_at, item.title.casefold()))
    return tuple(events[:MAX_DAILY_EVENTS])


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
