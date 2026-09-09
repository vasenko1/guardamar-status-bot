"""Small cached adapter for Guardamar Municipal Library's official agenda."""

import asyncio
import html
import json
import os
import re
import tempfile
import urllib.parse
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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
_DATE = re.compile(
    r"(?:(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|"
    r"domingo),?\s*)?(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})|"
    r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s*-\s*(\d{1,2})\s+de\s+"
    r"([a-záéíóú]+)\s+de\s+(\d{4}))",
    re.IGNORECASE,
)
_TIME = re.compile(r"\b([0-2]?\d:[0-5]\d)\s*-\s*([0-2]?\d:[0-5]\d)\b")


class _AgendaListParser(HTMLParser):
    """Read only the repeating official activity cards from the agenda page."""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[Dict[str, str]] = []
        self._current: Optional[Dict[str, object]] = None
        self._title_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div" and self._current is None and {"row", "actividades"} <= classes:
            self._current = {
                "depth": 1,
                "text": [],
                "title": [],
                "place": [],
                "place_depth": None,
                "link": None,
            }
            return
        if self._current is None:
            return
        if tag == "div":
            self._current["depth"] = int(self._current["depth"]) + 1
            if "list-opc" in classes:
                self._current["place_depth"] = self._current["depth"]
        elif tag == "a" and self._current["link"] is None:
            href = attributes.get("href")
            if href:
                self._current["link"] = href
        elif tag == "h3":
            self._title_depth += 1

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        self._current["text"].append(data)  # type: ignore[union-attr]
        if self._title_depth:
            self._current["title"].append(data)  # type: ignore[union-attr]
        if self._current["place_depth"] is not None:
            self._current["place"].append(data)  # type: ignore[union-attr]

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "h3" and self._title_depth:
            self._title_depth -= 1
        if tag != "div":
            return
        depth = int(self._current["depth"])
        if self._current["place_depth"] == depth:
            self._current["place_depth"] = None
        depth -= 1
        self._current["depth"] = depth
        if depth:
            return
        title = " ".join(" ".join(self._current["title"]).split())
        link = self._current["link"]
        if title and isinstance(link, str):
            self.records.append({
                "text": " ".join(" ".join(self._current["text"]).split()),
                "title": title,
                "place": " ".join(" ".join(self._current["place"]).split()),
                "link": link,
            })
        self._current = None


class _DetailTextParser(HTMLParser):
    """Collect the detail column without retaining a page or its media."""

    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != "div":
            return
        classes = set((dict(attrs).get("class") or "").split())
        if self._depth:
            self._depth += 1
        elif {"column", "detalle"} <= classes:
            self._depth = 1

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._depth:
            self._depth -= 1


class LibraryAgendaError(RuntimeError):
    """Operator-safe failure from the official library agenda."""


@dataclass(frozen=True)
class _LibraryRecord:
    event: Event
    detail_url: str
    detail_loaded: bool


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


def _activity_records(page: str) -> Tuple[Dict[str, str], ...]:
    parser = _AgendaListParser()
    parser.feed(page)
    return tuple(parser.records)


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
    for record in _activity_records(page):
        date_text = record["text"]
        start_day = _date(date_text)
        if start_day is None:
            continue
        end_day = _range_end(date_text)
        if (end_day or start_day) < local_day or start_day > horizon:
            continue
        title = record["title"]
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
        place_text = record["place"] or None
        if place_text is not None:
            place_text = re.sub(r"^location_on\s*", "", place_text)
        events.append((Event(
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            place=place_text,
            active_until=end_day,
            category="exhibition" if end_day else "event",
        ), urllib.parse.urljoin(LIBRARY_AGENDA_URL, html.unescape(record["link"]))))
        if len(events) == MAX_EVENTS:
            break
    return tuple(events)


def extract_teaser(payload: bytes) -> Optional[str]:
    """Return one complete factual sentence, never a generated summary."""

    parser = _DetailTextParser()
    parser.feed(payload.decode("utf-8", "replace"))
    text = " ".join(" ".join(parser.parts).split())
    if not text:
        return None
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


def _write_snapshot(
    path: Path, now: datetime, records: Tuple[_LibraryRecord, ...]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "fetched_at": now.isoformat(), "events": [
        {
            "title": record.event.title,
            "starts_at": record.event.starts_at.isoformat() if record.event.starts_at else None,
            "ends_at": record.event.ends_at.isoformat() if record.event.ends_at else None,
            "place": record.event.place,
            "active_until": record.event.active_until.isoformat() if record.event.active_until else None,
            "category": record.event.category,
            "teaser": record.event.teaser,
            "detail_url": record.detail_url,
            "detail_loaded": record.detail_loaded,
        }
        for record in records
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


def _load_snapshot(path: Path) -> Tuple[_LibraryRecord, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") not in {1, 2}:
            raise ValueError
        raw_events = data.get("events")
        if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
            raise ValueError
        records = []
        for raw in raw_events:
            if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
                raise ValueError
            starts_at = datetime.fromisoformat(raw["starts_at"]) if isinstance(raw.get("starts_at"), str) else None
            ends_at = datetime.fromisoformat(raw["ends_at"]) if isinstance(raw.get("ends_at"), str) else None
            active_until = date.fromisoformat(raw["active_until"]) if isinstance(raw.get("active_until"), str) else None
            if (starts_at and starts_at.tzinfo is None) or (ends_at and ends_at.tzinfo is None):
                raise ValueError
            event = Event(
                raw["title"], starts_at, ends_at, raw.get("place"), active_until,
                raw.get("category", "event"), teaser=raw.get("teaser"),
            )
            if data["version"] == 1:
                records.append(_LibraryRecord(event, "", False))
                continue
            detail_url = raw.get("detail_url")
            detail_loaded = raw.get("detail_loaded")
            if (
                not isinstance(detail_url, str)
                or not _is_library_url(detail_url)
                or not isinstance(detail_loaded, bool)
            ):
                raise ValueError
            records.append(_LibraryRecord(event, detail_url, detail_loaded))
        return tuple(records)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise LibraryAgendaError("Library agenda snapshot is invalid") from exc


async def refresh_library_catalog(now: datetime, state_path: Path) -> Tuple[Event, ...]:
    records = extract_events(await asyncio.to_thread(_read_page, LIBRARY_AGENDA_URL), now)
    previous = await asyncio.to_thread(_load_snapshot, state_path) if state_path.exists() else ()
    previous_by_url = {
        record.detail_url: record for record in previous if record.detail_url
    }
    refreshed = []
    for event, link in records:
        old = previous_by_url.get(link)
        same_card = old is not None and replace(old.event, teaser=None) == event
        if same_card and old.detail_loaded:
            refreshed.append(old)
            continue
        teaser = None
        detail_loaded = False
        try:
            teaser = extract_teaser(await asyncio.to_thread(_read_page, link))
            detail_loaded = True
        except LibraryAgendaError:
            pass
        refreshed.append(_LibraryRecord(
            replace(event, teaser=teaser), link, detail_loaded
        ))
    await asyncio.to_thread(_write_snapshot, state_path, now, tuple(refreshed))
    return tuple(record.event for record in refreshed)


async def fetch_today_library_events(now: datetime, state_path: Path, translation_cache_path: Path) -> Tuple[Event, ...]:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    result = []
    for record in await asyncio.to_thread(_load_snapshot, state_path):
        event = record.event
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
    for record in await asyncio.to_thread(_load_snapshot, state_path):
        event = record.event
        active = ((event.starts_at is not None and event.starts_at.date() == local_day) or
                  (event.starts_at is None and event.active_until is not None and event.active_until >= local_day))
        if active:
            items.append(("library_agenda", event.title))
            if event.teaser:
                items.append(("library_agenda_teaser", event.teaser))
    return tuple(items)
