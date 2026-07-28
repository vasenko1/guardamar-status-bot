"""Monthly official municipal agenda poster with a small local snapshot."""

import asyncio
import hashlib
import json
import os
import re
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

from .gemini import GeminiError, extract_agenda_events, translate_event_titles
from .models import Event

AGENDA_PAGE_URL = "https://guardamarturismo.com/agenda-cultural/"
PAGE_HOSTS = {"guardamarturismo.com", "www.guardamarturismo.com"}
POSTER_HOSTS = {"guardamardelsegura.es", "www.guardamardelsegura.es"}
PAGE_LIMIT_BYTES = 500_000
POSTER_LIMIT_BYTES = 4_000_000
REQUEST_TIMEOUT_SECONDS = 15
MAX_EVENTS = 80
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
JULY_2026_POSTER = (
    "https://www.guardamardelsegura.es/wp-content/uploads/"
    "2026/07/MUPI-JULIO-2026-scaled.jpg"
)


class MunicipalAgendaError(RuntimeError):
    """Raised when neither the current poster nor a snapshot is safe to use."""


@dataclass(frozen=True)
class SourceEvent:
    title_es: str
    start_date: date
    end_date: date
    start_time: Optional[str]
    end_time: Optional[str]
    place: Optional[str]
    category: str


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


def _read_url(url: str, allowed_hosts: set[str], limit: int) -> Tuple[bytes, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise MunicipalAgendaError("municipal agenda URL is not allowed")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GuardamarMorningDigest/0.8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in allowed_hosts:
                raise MunicipalAgendaError("unexpected municipal agenda redirect")
            payload = response.read(limit + 1)
            mime_type = response.headers.get_content_type()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise MunicipalAgendaError("municipal agenda request failed") from exc
    if len(payload) > limit:
        raise MunicipalAgendaError("municipal agenda response was too large")
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
    raise MunicipalAgendaError("official monthly poster was not found")


def _clean_text(value: Any, maximum: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MunicipalAgendaError("invalid poster event text")
    result = " ".join(value.split())
    if not result or len(result) > maximum:
        raise MunicipalAgendaError("invalid poster event text")
    return result


def normalize_extraction(result: Dict[str, Any]) -> Tuple[SourceEvent, ...]:
    """Validate OCR output and discard routine non-event entries."""

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
        )
        key = (event.title_es.casefold(), event.start_date, event.start_time)
        if key not in seen:
            seen.add(key)
            events.append(event)
    return tuple(events)


def _snapshot_data(
    poster_url: str,
    poster_hash: str,
    fetched_at: datetime,
    events: Tuple[SourceEvent, ...],
) -> Dict[str, Any]:
    return {
        "version": 1,
        "poster_url": poster_url,
        "poster_sha256": poster_hash,
        "fetched_at": fetched_at.isoformat(),
        "events": [
            {
                "title_es": event.title_es,
                "start_date": event.start_date.isoformat(),
                "end_date": event.end_date.isoformat(),
                "start_time": event.start_time,
                "end_time": event.end_time,
                "place": event.place,
                "category": event.category,
            }
            for event in events
        ],
    }


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
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError
        events = normalize_extraction({"events": data["events"]})
        return {**data, "_events": events}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, MunicipalAgendaError) as exc:
        raise MunicipalAgendaError("municipal agenda snapshot is invalid") from exc


def _apply_reviewed_corrections(
    poster_url: str,
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Repair facts manually verified in the official text agenda."""

    if poster_url != JULY_2026_POSTER:
        return events
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
                )
            )
            entropia_added = True
    return tuple(corrected)


def _merge_reviewed_text_agenda(
    events: Tuple[SourceEvent, ...],
) -> Tuple[SourceEvent, ...]:
    """Keep verified current-month facts when the poster advances early."""

    if any(
        "conchi montes" in event.title_es.casefold()
        or "entrop" in event.title_es.casefold()
        for event in events
    ):
        return events
    return events + (
        SourceEvent(
            title_es="Exposición de pintura «Entropía» de Conchi Montes",
            start_date=date(2026, 7, 3),
            end_date=date(2026, 7, 29),
            start_time="08:00",
            end_time="14:00",
            place="Biblioteca Pública Municipal",
            category="exhibition",
        ),
    )


async def _current_events(
    api_key: str,
    now: datetime,
    state_path: Path,
) -> Tuple[SourceEvent, ...]:
    snapshot = await asyncio.to_thread(_load_snapshot, state_path)
    poster_url = (
        str(snapshot.get("poster_url", ""))
        if snapshot is not None
        else ""
    )
    try:
        page, _ = await asyncio.to_thread(
            _read_url, AGENDA_PAGE_URL, PAGE_HOSTS, PAGE_LIMIT_BYTES
        )
        poster_url = extract_poster_url(page)
        if snapshot is not None and snapshot.get("poster_url") == poster_url:
            events = snapshot["_events"]
        else:
            poster, mime_type = await asyncio.to_thread(
                _read_url, poster_url, POSTER_HOSTS, POSTER_LIMIT_BYTES
            )
            poster_hash = hashlib.sha256(poster).hexdigest()
            if snapshot is not None and snapshot.get("poster_sha256") == poster_hash:
                events = snapshot["_events"]
            else:
                extracted = await extract_agenda_events(api_key, poster, mime_type)
                events = normalize_extraction(extracted)
            await asyncio.to_thread(
                _write_snapshot,
                state_path,
                _snapshot_data(poster_url, poster_hash, now, events),
            )
    except (MunicipalAgendaError, GeminiError):
        if snapshot is None:
            raise
        events = snapshot["_events"]
    events = _apply_reviewed_corrections(poster_url, events)
    events = _merge_reviewed_text_agenda(events)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    active = [event for event in events if event.start_date <= local_day <= event.end_date]
    active.sort(
        key=lambda event: (
            event.start_date != event.end_date,
            event.start_time or "99:99",
            event.title_es.casefold(),
        )
    )
    return tuple(active[:2])


async def fetch_today_municipal_events(
    now: datetime,
    api_key: str,
    state_path: Path,
) -> Tuple[Event, ...]:
    """Return up to two translated events, using the snapshot during outages."""

    if not api_key:
        raise MunicipalAgendaError("Gemini key is required for municipal agenda")
    source_events = await _current_events(api_key, now, state_path)
    if not source_events:
        return ()
    try:
        titles = await translate_event_titles(
            api_key, [event.title_es for event in source_events]
        )
    except GeminiError as exc:
        raise MunicipalAgendaError("event translation failed") from exc
    result = []
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for source, title in zip(source_events, titles):
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
            )
        )
    return tuple(result)
