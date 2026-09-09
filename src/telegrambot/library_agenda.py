"""Small cached adapter for Guardamar Municipal Library's official agenda."""

import asyncio
import html
import json
import os
import re
import tempfile
import urllib.parse
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .event_translations import cached_title, cached_translation
from .models import Event

LIBRARY_AGENDA_URL = (
    "https://www.bibliotecaspublicas.es/guardamardelsegura/"
    "actividades-programas/Agenda-de-actividades.html"
)
LIBRARY_HOST = "www.bibliotecaspublicas.es"
REQUEST_TIMEOUT_SECONDS = 15
PAGE_LIMIT_BYTES = 300_000
MAX_EVENTS = 20
HORIZON_DAYS = 7
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_RECORD = re.compile(
    r'<div class="registro\b.*?(?=<div class="registro\b|</ul>\s*'
    r'<div class="row numActividades")', re.IGNORECASE | re.DOTALL
)
_DATE = re.compile(
    r"(?:(?:Lunes,\s*)?(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})|"
    r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s*-\s*(\d{1,2})\s+de\s+"
    r"([a-záéíóú]+)\s+de\s+(\d{4}))",
    re.IGNORECASE,
)
_TIME = re.compile(r"\b([0-2]?\d:[0-5]\d)\s*-\s*([0-2]?\d:[0-5]\d)\b")
_LINK = re.compile(r'<a\s+href="([^"]+)"[^>]*>\s*<li class="titulo">\s*'
                   r"<h3>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
_PLACE = re.compile(
    r'list-opc.*?<li[^>]*>(?:\s*<[^>]+>)*\s*(.*?)</li>',
    re.IGNORECASE | re.DOTALL,
)
_DESCRIPTION = re.compile(
    r'<div class="column detalle">\s*(.*?)</div>', re.IGNORECASE | re.DOTALL
)


class LibraryAgendaError(RuntimeError):
    """Operator-safe failure from the official library agenda."""


def _is_library_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == LIBRARY_HOST


def _read_page(url: str) -> bytes:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_is_library_url,
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
        raise LibraryAgendaError(
            f"Library agenda request failed: {exc.code}"
        ) from exc
    return payload


def _text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def _date(value: str) -> Optional[date]:
    match = _DATE.search(value)
    if match is None:
        return None
    try:
        if match.group(1):
            return date(int(match.group(3)), _MONTHS[match.group(2).casefold()], int(match.group(1)))
        return date(int(match.group(8)), _MONTHS[match.group(5).casefold()], int(match.group(4)))
    except (KeyError, ValueError):
        return None


def _range_end(value: str) -> Optional[date]:
    match = _DATE.search(value)
    if match is None or not match.group(6):
        return None
    try:
        return date(int(match.group(8)), _MONTHS[match.group(7).casefold()], int(match.group(6)))
    except (KeyError, ValueError):
        return None


def extract_events(payload: bytes, now: datetime) -> Tuple[Tuple[Event, str], ...]:
    """Extract only the short dated records published on the official list."""

    page = payload.decode("utf-8", "replace")
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    horizon = local_day + timedelta(days=HORIZON_DAYS)
    events = []
    for record in _RECORD.findall(page):
        date_text = _text(record)
        start_day = _date(date_text)
        if start_day is None:
            continue
        end_day = _range_end(date_text)
        if (end_day or start_day) < local_day or start_day > horizon:
            continue
        link = _LINK.search(record)
        place = _PLACE.search(record)
        if link is None:
            continue
        title = _text(link.group(2))
        if not 1 <= len(title) <= 160:
            continue
        time_match = _TIME.search(date_text)
        if time_match:
            try:
                starts_at = datetime.combine(
                    start_day,
                    datetime.strptime(time_match.group(1), "%H:%M").time(),
                    GUARDAMAR_TIMEZONE,
                )
                ends_at = datetime.combine(
                    start_day,
                    datetime.strptime(time_match.group(2), "%H:%M").time(),
                    GUARDAMAR_TIMEZONE,
                )
            except ValueError:
                continue
        else:
            starts_at = None
            ends_at = None
        place_text = _text(place.group(1)) if place else None
        if place_text is not None:
            place_text = re.sub(r"^location_on\s*", "", place_text)
        events.append((Event(
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            place=place_text,
            active_until=end_day,
            category="exhibition" if end_day else "event",
        ), urllib.parse.urljoin(LIBRARY_AGENDA_URL, html.unescape(link.group(1)))))
        if len(events) == MAX_EVENTS:
            break
    return tuple(events)


def extract_teaser(payload: bytes) -> Optional[str]:
    """Return one complete factual sentence, never a generated summary."""

    match = _DESCRIPTION.search(payload.decode("utf-8", "replace"))
    if match is None:
        return None
    text = _text(match.group(1))
    factual = re.search(
        r"(?:Esta colección|Este ciclo|Esta exposición).*?[.!?]",
        text,
        re.IGNORECASE,
    )
    if factual is not None and 30 <= len(factual.group(0)) <= 200:
        return factual.group(0)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        if 30 <= len(sentence) <= 200 and sentence.endswith((".", "!", "?")):
            return sentence
    return None


def _write_snapshot(path: Path, now: datetime, events: Tuple[Event, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "fetched_at": now.isoformat(), "events": [
        {"title": event.title, "starts_at": event.starts_at.isoformat() if event.starts_at else None,
         "ends_at": event.ends_at.isoformat() if event.ends_at else None, "place": event.place,
         "active_until": event.active_until.isoformat() if event.active_until else None,
         "category": event.category, "teaser": event.teaser}
        for event in events
    ]}
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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


def _load_snapshot(path: Path) -> Tuple[Event, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError
        raw_events = data.get("events")
        if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
            raise ValueError
        events = []
        for raw in raw_events:
            if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
                raise ValueError
            starts_at = datetime.fromisoformat(raw["starts_at"]) if isinstance(raw.get("starts_at"), str) else None
            ends_at = datetime.fromisoformat(raw["ends_at"]) if isinstance(raw.get("ends_at"), str) else None
            active_until = date.fromisoformat(raw["active_until"]) if isinstance(raw.get("active_until"), str) else None
            if (starts_at and starts_at.tzinfo is None) or (ends_at and ends_at.tzinfo is None):
                raise ValueError
            events.append(Event(raw["title"], starts_at, ends_at, raw.get("place"), active_until,
                                raw.get("category", "event"), teaser=raw.get("teaser")))
        return tuple(events)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise LibraryAgendaError("Library agenda snapshot is invalid") from exc


async def refresh_library_catalog(now: datetime, state_path: Path) -> Tuple[Event, ...]:
    records = extract_events(await asyncio.to_thread(_read_page, LIBRARY_AGENDA_URL), now)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    events = []
    for event, link in records:
        teaser = None
        if (event.starts_at and event.starts_at.date() == local_day) or (
            event.starts_at is None and event.active_until and event.active_until >= local_day
        ):
            try:
                teaser = extract_teaser(await asyncio.to_thread(_read_page, link))
            except LibraryAgendaError:
                pass
        events.append(replace(event, teaser=teaser))
    await asyncio.to_thread(_write_snapshot, state_path, now, tuple(events))
    return tuple(events)


async def fetch_today_library_events(now: datetime, state_path: Path, translation_cache_path: Path) -> Tuple[Event, ...]:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    result = []
    for event in await asyncio.to_thread(_load_snapshot, state_path):
        active = ((event.starts_at is not None and event.starts_at.date() == local_day) or
                  (event.starts_at is None and event.active_until is not None and event.active_until >= local_day))
        if not active:
            continue
        teaser = (cached_translation(translation_cache_path, "library_agenda_teaser", event.teaser)
                  if event.teaser else None)
        result.append(replace(event,
            title=cached_title(translation_cache_path, "library_agenda", event.title), teaser=teaser))
    return tuple(result)


async def library_translation_items(now: datetime, state_path: Path) -> Tuple[Tuple[str, str], ...]:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    items = []
    for event in await asyncio.to_thread(_load_snapshot, state_path):
        active = ((event.starts_at is not None and event.starts_at.date() == local_day) or
                  (event.starts_at is None and event.active_until is not None and event.active_until >= local_day))
        if active:
            items.append(("library_agenda", event.title))
            if event.teaser:
                items.append(("library_agenda_teaser", event.teaser))
    return tuple(items)
