"""Bounded WordPress event supplement from Agrupacion Musical Guardamar."""

import asyncio
import json
import os
import re
import tempfile
import urllib.parse
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .event_translations import cached_title
from .gemini import GeminiError, extract_agenda_text_events
from .models import Event
from .municipal_agenda import (
    MunicipalAgendaError,
    SourceEvent,
    normalize_extraction_candidates,
)
from .todo_cultura import _all_mentioned_dates, _plain_lines

API_URL = "https://amguardamar.es/wp-json/wp/v2/posts"
API_HOST = "amguardamar.es"
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 300_000
POST_LIMIT = 12
EVENT_HORIZON_DAYS = 45
TEXT_LIMIT = 12_000
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

_PUBLIC_MARKERS = re.compile(
    r"\b(?:concierto|actuaci[oó]n|audici[oó]n|pasacalles?|"
    r"festival|recital|m[uú]sica\s+en\s+directo)\b",
    re.IGNORECASE,
)
_MUSIC_AND_PUBLIC_VENUE = re.compile(
    r"\b(?:banda|orquesta|ensemble|agrupaci[oó]n\s+musical|m[uú]sica)\b"
    r".*\b(?:plaza|parque|auditorio|casa\s+de\s+cultura|escuela\s+de\s+m[uú]sica)\b",
    re.IGNORECASE | re.DOTALL,
)
_NON_EVENT_TITLE = re.compile(
    r"\b(?:matr[ií]cula|becas?|convocatoria|curso|horarios?|asignaturas|"
    r"pruebas\s+de\s+acceso|plazas)\b",
    re.IGNORECASE,
)


class AmGuardamarError(RuntimeError):
    """Operator-safe failure from AM Guardamar's public WordPress API."""


def _allowed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == API_HOST


def _request_url() -> str:
    fields = (
        "id,date,modified,link,title,content,excerpt,categories,tags,"
        "featured_media,_links"
    )
    return API_URL + "?" + urllib.parse.urlencode({
        "per_page": POST_LIMIT,
        "orderby": "modified",
        "order": "desc",
        "_fields": fields,
    })


def _read_posts() -> List[Dict[str, Any]]:
    try:
        payload, _, _ = fetch_bounded(
            _request_url(),
            is_allowed_url=_allowed_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
        value = json.loads(payload.decode("utf-8"))
    except (BoundedFetchError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AmGuardamarError("AM Guardamar API is unavailable or invalid") from exc
    if not isinstance(value, list) or len(value) > POST_LIMIT:
        raise AmGuardamarError("AM Guardamar API returned an invalid post list")
    return [item for item in value if isinstance(item, dict)]


def _plain(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "\n".join(_plain_lines(value))


def _post_fields(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    identifier = raw.get("id")
    published = raw.get("date")
    modified = raw.get("modified")
    link = raw.get("link")
    title_value = raw.get("title")
    content_value = raw.get("content")
    excerpt_value = raw.get("excerpt")
    if not (
        isinstance(identifier, int)
        and identifier > 0
        and isinstance(published, str)
        and isinstance(modified, str)
        and isinstance(link, str)
        and isinstance(title_value, dict)
    ):
        return None
    title = _plain(title_value.get("rendered"))
    content = _plain(content_value.get("rendered")) if isinstance(content_value, dict) else ""
    excerpt = _plain(excerpt_value.get("rendered")) if isinstance(excerpt_value, dict) else ""
    categories = raw.get("categories")
    tags = raw.get("tags")
    featured_media = raw.get("featured_media")
    parsed = urllib.parse.urlparse(link)
    if (
        not title
        or parsed.scheme != "https"
        or parsed.hostname != API_HOST
        or len(title) > 240
        or not isinstance(categories, list)
        or not isinstance(tags, list)
        or not isinstance(featured_media, int)
    ):
        return None
    text = "\n".join(part for part in (title, content or excerpt) if part)
    if not text or len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT]
    return {
        "id": identifier,
        "date": published,
        "modified": modified,
        "link": link,
        "title": title,
        "text": text,
        "description": excerpt[:240] or None,
        "categories": [value for value in categories if isinstance(value, int)],
        "tags": [value for value in tags if isinstance(value, int)],
        "featured_media": featured_media,
    }


def _is_public_future_candidate(post: Dict[str, Any], now: datetime) -> Optional[str]:
    if _NON_EVENT_TITLE.search(post["title"]):
        return None
    text = post["text"]
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    dates = [
        candidate for candidate in _all_mentioned_dates(text, local_day)
        if local_day <= candidate <= local_day + timedelta(days=EVENT_HORIZON_DAYS)
    ]
    if not dates or "guardamar" not in text.casefold():
        return None
    if not (_PUBLIC_MARKERS.search(text) or _MUSIC_AND_PUBLIC_VENUE.search(text)):
        return None
    return min(dates).strftime("%Y-%m")


def _event_data(event: SourceEvent) -> Dict[str, Any]:
    data = asdict(event)
    data["start_date"] = event.start_date.isoformat()
    data["end_date"] = event.end_date.isoformat()
    data["sources"] = list(event.sources)
    return data


def _event_from_data(raw: Any) -> Optional[SourceEvent]:
    if not isinstance(raw, dict):
        return None
    try:
        title = raw["title_es"]
        start = date.fromisoformat(raw["start_date"])
        end = date.fromisoformat(raw["end_date"])
        if not isinstance(title, str) or not start <= end:
            return None
        values = dict(raw)
        values["start_date"] = start
        values["end_date"] = end
        values["sources"] = tuple(raw["sources"])
        return SourceEvent(**values)
    except (KeyError, TypeError, ValueError):
        return None


def _load_snapshot(path: Path) -> Dict[int, Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("posts"), list):
            raise ValueError
        result = {}
        for post in data["posts"]:
            if not isinstance(post, dict) or not isinstance(post.get("id"), int):
                raise ValueError
            if not isinstance(post.get("events"), list):
                raise ValueError
            result[post["id"]] = post
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        if path.exists():
            raise AmGuardamarError("AM Guardamar catalog is invalid") from exc
        return {}


def _write_snapshot(path: Path, now: datetime, posts: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(
                {"version": 1, "fetched_at": now.isoformat(), "posts": posts},
                output,
                ensure_ascii=False,
                separators=(",", ":"),
            )
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


async def refresh_am_guardamar_catalog(
    api_key: str, now: datetime, state_path: Path
) -> Tuple[SourceEvent, ...]:
    """Refresh the small post catalog; unchanged post IDs keep their facts."""

    previous = await asyncio.to_thread(_load_snapshot, state_path)
    records = []
    events = []
    for raw in await asyncio.to_thread(_read_posts):
        post = _post_fields(raw)
        if post is None:
            continue
        expected_month = _is_public_future_candidate(post, now)
        if expected_month is None:
            continue
        old = previous.get(post["id"])
        if old is not None and old.get("modified") == post["modified"]:
            extracted = tuple(
                event for event in (_event_from_data(item) for item in old["events"])
                if event is not None
            )
        else:
            result = await extract_agenda_text_events(api_key, post["text"])
            result = {**result, "month": expected_month}
            try:
                extracted = normalize_extraction_candidates(
                    result, expected_month, "am_guardamar", post["text"]
                )
            except MunicipalAgendaError:
                continue
        local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
        extracted = tuple(
            event for event in extracted
            if local_day <= event.end_date <= local_day + timedelta(days=EVENT_HORIZON_DAYS)
        )
        records.append(
            {
                "id": post["id"],
                "date": post["date"],
                "modified": post["modified"],
                "link": post["link"],
                "title": post["title"],
                "description": post["description"],
                "categories": post["categories"],
                "tags": post["tags"],
                "featured_media": post["featured_media"],
                "events": [_event_data(event) for event in extracted],
            }
        )
        events.extend(extracted)
    await asyncio.to_thread(_write_snapshot, state_path, now, records)
    return tuple(events)


async def _current_events(now: datetime, state_path: Path) -> Tuple[SourceEvent, ...]:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    posts = await asyncio.to_thread(_load_snapshot, state_path)
    events = []
    for post in posts.values():
        for raw in post["events"]:
            event = _event_from_data(raw)
            if event is not None and event.start_date <= local_day <= event.end_date:
                events.append(event)
    return tuple(events)


async def fetch_today_am_guardamar_events(
    now: datetime, state_path: Path, translation_cache_path: Path
) -> Tuple[Event, ...]:
    result = []
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    for event in await _current_events(now, state_path):
        starts_at = None
        ends_at = None
        if event.start_time:
            hour, minute = (int(value) for value in event.start_time.split(":"))
            starts_at = datetime.combine(
                local_day,
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=GUARDAMAR_TIMEZONE,
            )
            if event.end_time:
                hour, minute = (int(value) for value in event.end_time.split(":"))
                ends_at = datetime.combine(
                    local_day,
                    datetime.min.time().replace(hour=hour, minute=minute),
                    tzinfo=GUARDAMAR_TIMEZONE,
                )
        result.append(Event(
            title=cached_title(translation_cache_path, "am_guardamar", event.title_es),
            starts_at=starts_at, ends_at=ends_at, place=event.place,
            category=event.category, ticket_price_cents=event.ticket_price_cents,
            ticket_url=event.ticket_url, participation_note=event.participation_note,
            registration_contact=event.registration_contact,
            capacity_limited=event.capacity_limited,
        ))
    return tuple(result)


async def am_guardamar_translation_items(now: datetime, state_path: Path) -> Tuple[Tuple[str, str], ...]:
    return tuple(("am_guardamar", event.title_es) for event in await _current_events(now, state_path))
