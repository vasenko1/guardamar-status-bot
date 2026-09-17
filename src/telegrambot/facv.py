"""Bounded official FACV calendar source for Guardamar chess events."""

import asyncio
import re
import unicodedata
import urllib.parse
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Optional

from ._transport import BoundedFetchError, fetch_bounded

FACV_URL = "https://www.facv.org/appwebfacv/public/staff/torneos/calendario_oficial.php"
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "guardamar-status-bot/1.0",
}
_MAX_BYTES = 1024 * 1024
_TIMEOUT_SECONDS = 15.0
_MAX_EVENTS = 64


class FacvSourceError(RuntimeError):
    """An FACV observation that is unsafe to use."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", " ".join(value.split())).casefold()
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.facv.org"
        and port in {None, 443}
        and parsed.path == "/appwebfacv/public/staff/torneos/calendario_oficial.php"
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.casefold()
        if lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"td", "th"} and self._cell is not None:
            value = " ".join("".join(self._cell).split())
            self._row.append(value)
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _parse_date(value: str) -> date:
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", value)
    if match is None:
        raise FacvSourceError("FACV event date is invalid", code="SCHEMA")
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError as exc:
        raise FacvSourceError("FACV event date is invalid", code="SCHEMA") from exc


def _header_map(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    wanted = {
        "nombre": "title",
        "inicio": "start",
        "final": "end",
        "lugar": "place",
        "organizador": "organizer",
    }
    for row_index, row in enumerate(rows):
        mapped: dict[str, int] = {}
        for index, cell in enumerate(row):
            key = wanted.get(_fold(cell))
            if key is not None:
                mapped[key] = index
        if set(mapped) == set(wanted.values()):
            return row_index, mapped
    raise FacvSourceError("FACV calendar table header is missing", code="SCHEMA")


def parse_facv_html(payload: bytes, local_day: date, observed_at: datetime) -> dict:
    """Normalize current/future Guardamar rows from one FACV calendar page."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FacvSourceError("FACV HTML is invalid", code="HTML") from exc
    parser = _TableParser()
    parser.feed(text)
    header_index, columns = _header_map(parser.rows)
    events = []
    seen = set()
    required_max = max(columns.values())
    for row in parser.rows[header_index + 1 :]:
        if len(row) <= required_max:
            continue
        place = " ".join(row[columns["place"]].split())
        if _fold(place) != "guardamar del segura":
            continue
        title = " ".join(row[columns["title"]].split())
        organizer = " ".join(row[columns["organizer"]].split())
        if not title or len(title) > 180 or len(organizer) > 180:
            raise FacvSourceError("FACV target row is invalid", code="SCHEMA")
        start = _parse_date(row[columns["start"]])
        end = _parse_date(row[columns["end"]])
        if end < start:
            raise FacvSourceError("FACV event interval is reversed", code="SCHEMA")
        if end < local_day:
            continue
        identity = (title.casefold(), start, end, place.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        events.append(
            {
                "sport": "chess",
                "title": title,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "place": place,
                "organizer": organizer,
                "source_url": FACV_URL,
            }
        )
        if len(events) > _MAX_EVENTS:
            raise FacvSourceError("FACV Guardamar event set is too large", code="SCHEMA")
    events.sort(key=lambda item: (item["start"], item["title"].casefold()))
    return {"observed_at": observed_at.isoformat(), "events": events}


def valid_facv_snapshot(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"observed_at", "events"}:
        return False
    try:
        observed = datetime.fromisoformat(value["observed_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    events = value.get("events")
    if not isinstance(events, list) or len(events) > _MAX_EVENTS:
        return False
    required = {"sport", "title", "start", "end", "place", "organizer", "source_url"}
    for event in events:
        if not isinstance(event, dict) or set(event) != required:
            return False
        if event.get("sport") != "chess" or event.get("source_url") != FACV_URL:
            return False
        if not all(isinstance(event.get(key), str) and event[key] for key in ("title", "place", "organizer")):
            return False
        try:
            start = date.fromisoformat(event["start"])
            end = date.fromisoformat(event["end"])
        except (TypeError, ValueError):
            return False
        if end < start or _fold(event["place"]) != "guardamar del segura":
            return False
    return True


async def fetch_facv_snapshot(now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FACV observation time must be timezone-aware")
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            FACV_URL,
            is_allowed_url=_allowed_url,
            accepted_types=_HTML_TYPES,
            limit_bytes=_MAX_BYTES,
            timeout_seconds=_TIMEOUT_SECONDS,
            headers=_HEADERS,
        )
    except BoundedFetchError as exc:
        raise FacvSourceError("FACV request failed", code=exc.code) from exc
    return parse_facv_html(payload, now.date(), now)
