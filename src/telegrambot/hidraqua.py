"""One-shot, conservative Hidraqua interruption notices for Guardamar."""

import asyncio
import fcntl
import html
import json
import os
import urllib.parse
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Sequence
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer

LAYER_QUERY_URL = "https://services3.arcgis.com/5VitVYyVLQYnzXCo/arcgis/rest/services/Cierres_webPublicas_v/FeatureServer/0/query"
GUARDAMAR_CODE = "03076"
ACTIVE_STATUSES = ("4AP", "5EC")
TIMEOUT_SECONDS = 20
RESPONSE_LIMIT_BYTES = 512 * 1024
STATE_VERSION = 1
RETENTION = timedelta(days=180)
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
MADRID = ZoneInfo("Europe/Madrid")


class HidraquaError(RuntimeError):
    """The source response cannot safely drive a notice."""


@dataclass(frozen=True)
class HidraquaEvent:
    event_id: int
    status: str
    motive: str
    address: Optional[str]
    streets: Optional[str]
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]


def _is_hidraqua_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "services3.arcgis.com"


def _epoch(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise HidraquaError("invalid event date")
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(MADRID)
    except (OverflowError, OSError, ValueError) as exc:
        raise HidraquaError("invalid event date") from exc


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HidraquaError("invalid text field")
    value = " ".join(value.split())
    return value or None


def normalize_events(payload: Dict[str, Any]) -> tuple[HidraquaEvent, ...]:
    features = payload.get("features")
    if not isinstance(features, list):
        raise HidraquaError("response has no features list")
    events = {}
    for feature in features:
        attributes = feature.get("attributes") if isinstance(feature, dict) else None
        if not isinstance(attributes, dict):
            raise HidraquaError("response has invalid feature")
        event_id = attributes.get("CI_ID")
        status = attributes.get("CI_ESTADO")
        motive = attributes.get("CI_MOTIVO")
        municipality = attributes.get("COD_MUNI")
        if (
            not isinstance(event_id, int) or event_id <= 0
            or status not in ACTIVE_STATUSES or not isinstance(motive, str)
            or municipality != GUARDAMAR_CODE
        ):
            raise HidraquaError("response has invalid event fields")
        event = HidraquaEvent(
            event_id, status, motive, _text(attributes.get("CI_DIRECCION")),
            _text(attributes.get("CI_CALLES")),
            _epoch(attributes.get("CI_FH_INI_PREV")),
            _epoch(attributes.get("CI_FH_FIN_PREV")),
        )
        existing = events.get(event_id)
        if existing is not None and existing != event:
            raise HidraquaError("duplicate event ID has conflicting data")
        events[event_id] = event
    return tuple(events[key] for key in sorted(events))


def _read_active() -> Dict[str, Any]:
    where = "COD_MUNI='03076' AND CI_ESTADO IN ('4AP','5EC')"
    parameters = urllib.parse.urlencode({
        "where": where,
        "outFields": "CI_ID,CI_FH_INI_PREV,CI_FH_FIN_PREV,CI_DIRECCION,CI_CALLES,CI_ESTADO,CI_MOTIVO,COD_MUNI",
        "returnGeometry": "false", "f": "json",
    })
    try:
        data, _, _ = fetch_bounded(
            f"{LAYER_QUERY_URL}?{parameters}", is_allowed_url=_is_hidraqua_url,
            accepted_types=frozenset({"application/json", "text/plain"}),
            limit_bytes=RESPONSE_LIMIT_BYTES, timeout_seconds=TIMEOUT_SECONDS,
            headers={"Accept": "application/json", "User-Agent": "GuardamarMorningDigest/0.14"},
            follow_redirects=False,
        )
    except BoundedFetchError as exc:
        raise HidraquaError(f"request failed: {exc.code}") from exc
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HidraquaError("response is not JSON") from exc
    if not isinstance(payload, dict) or "error" in payload:
        raise HidraquaError("ArcGIS returned an error")
    return payload


async def fetch_active_events() -> tuple[HidraquaEvent, ...]:
    return normalize_events(await asyncio.to_thread(_read_active))


def _maps_link(label: str, query: str) -> str:
    """Return one escaped inline Maps search link for a source-backed place."""
    url = "https://www.google.com/maps/search/?" + urllib.parse.urlencode({
        "api": "1", "query": query,
    })
    return f'📍 <a href="{html.escape(url, quote=True)}"><b>{html.escape(label)}</b></a>'


def _address_parts(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not address:
        return None, None
    urbanization_match = re.search(r"\(([^()]+)\)\s*$", address)
    urbanization = urbanization_match.group(1).strip() if urbanization_match else None
    main = address[:urbanization_match.start()].strip(" ,") if urbanization_match else address
    main = main.split(",", 1)[0].strip()
    main = re.sub(r"\b(\d+)-\1\b", r"\1", main)
    match = re.fullmatch(r"(.+?)\s+(\d+[A-Za-z]?)", main)
    if match:
        main = f"{match.group(1)}, {match.group(2)}"
    return main or None, urbanization or None


def _street_list(value: Optional[str]) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip().title() for part in value.split(",") if part.strip())


def _russian_join(parts: Sequence[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} и {parts[1]}"
    return f"{', '.join(parts[:-1])} и {parts[-1]}"


def _location(event: HidraquaEvent) -> str:
    address, urbanization = _address_parts(event.address)
    if not address:
        return "в Гуардамаре"
    query_parts = [address]
    if urbanization:
        query_parts.append(urbanization)
    query_parts.extend(("03140 Guardamar del Segura", "Alicante"))
    linked = _maps_link(address, ", ".join(query_parts))
    if urbanization:
        if re.search(r",\s*\d+[A-Za-z]?$", address):
            return f"в <b>{html.escape(urbanization)}</b>, в районе {linked}"
        return f"в <b>{html.escape(urbanization)}</b> на {linked}"
    return f"в районе {linked}"


def _other_streets(event: HidraquaEvent) -> str:
    streets = _street_list(event.streets)
    if not streets:
        return ""
    _, urbanization = _address_parts(event.address)
    places = []
    for street in streets:
        query = [street]
        if urbanization:
            query.append(urbanization)
        query.extend(("Guardamar del Segura", "Alicante"))
        places.append(_maps_link(street, ", ".join(query)))
    noun = "улица" if len(places) == 1 else "улицы"
    verb = "затронута" if len(places) == 1 else "затронуты"
    return f" Также {verb} {noun} {_russian_join(places)}."


def _eta(event: HidraquaEvent, variant: int = 0) -> str:
    if not event.ends_at:
        return ""
    phrases = (
        "Восстановление ожидается примерно к",
        "Ожидаемое время восстановления — около",
        "Восстановление водоснабжения ожидается примерно к",
    )
    return f" {phrases[variant % len(phrases)]} <b>{event.ends_at:%H:%M}</b>."


def format_event(event: HidraquaEvent, *, grouped: bool = False, variant: int = 0) -> str:
    """Format one source record without footer; dynamic content is HTML-escaped."""
    location = _location(event)
    sentence_location = location[:1].upper() + location[1:]
    address, urbanization = _address_parts(event.address)
    grouped_location = sentence_location
    if urbanization and address and re.search(r",\s*\d+[A-Za-z]?$", address):
        grouped_location += ","
    if event.motive == "AVE":
        if grouped:
            text = f"🔹 {grouped_location} произошла авария на водопроводной сети."
        else:
            text = f"💧 Hidraqua сообщает об аварии на водопроводной сети {location}."
    elif event.motive == "***":
        text = (
            f"🔹 {sentence_location} проводятся работы по улучшению водопроводной сети."
            if grouped else
            f"💧 Hidraqua сообщает о работах по улучшению водопроводной сети {location}."
        )
    else:
        text = f"🔹 Hidraqua сообщает о работах на водопроводной сети {location}." if grouped else f"💧 Hidraqua сообщает о работах на водопроводной сети {location}."
    return text + _other_streets(event) + _eta(event, variant)


def format_messages(events: Sequence[HidraquaEvent], *, max_length: int = MAX_TELEGRAM_MESSAGE_LENGTH) -> tuple[tuple[tuple[int, ...], str], ...]:
    """Group new records and split only between complete event paragraphs."""
    if not events or max_length < 100:
        raise ValueError("events and a practical message limit are required")
    grouped = len(events) > 1
    header = "💧 <b>Hidraqua сообщает сразу о нескольких событиях на водопроводной сети Гуардамара.</b>"
    warning = "⚠️ Возможно временное отключение воды или перебои с водоснабжением в указанных районах."
    paragraphs = [format_event(item, grouped=grouped, variant=index) for index, item in enumerate(events)]
    result = []
    ids = []
    body = header if grouped else paragraphs[0]
    if not grouped:
        candidate = with_footer(body + "\n\n⚠️ Возможно отключение воды или перебои с водоснабжением.")
        if len(candidate) > max_length:
            raise HidraquaError("one event exceeds Telegram message limit")
        return (((events[0].event_id,), candidate),)
    for event, paragraph in zip(events, paragraphs):
        candidate_body = f"{body}\n\n{paragraph}" if ids else f"{header}\n\n{paragraph}"
        candidate = with_footer(f"{candidate_body}\n\n{warning}")
        if ids and len(candidate) > max_length:
            result.append((tuple(ids), with_footer(f"{body}\n\n{warning}")))
            ids = [event.event_id]
            body = f"{header}\n\n{paragraph}"
        else:
            ids.append(event.event_id)
            body = candidate_body
    final = with_footer(f"{body}\n\n{warning}")
    if len(final) > max_length:
        raise HidraquaError("one event exceeds Telegram message limit")
    result.append((tuple(ids), final))
    return tuple(result)


class HidraquaState:
    """Atomic bounded seen-ID store; first successful read is a quiet bootstrap."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HidraquaError("state is unreadable") from exc
        if value.get("version") != STATE_VERSION or not isinstance(value.get("events"), dict):
            raise HidraquaError("state is invalid")
        return value

    def write(self, value: dict) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        lock = self.path.with_name(f".{self.path.name}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with lock.open("a", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        except BlockingIOError as exc:
            raise HidraquaError("another Hidraqua run is active") from exc


def _prune(events: dict, now: datetime) -> dict:
    cutoff = now - RETENTION
    return {key: value for key, value in events.items() if isinstance(value, dict) and isinstance(value.get("first_seen_at"), str) and _parse_time(value["first_seen_at"]) >= cutoff}


def _parse_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HidraquaError("state timestamp is invalid") from exc
    if result.tzinfo is None:
        raise HidraquaError("state timestamp is invalid")
    return result


async def monitor_once(state: HidraquaState, now: datetime, send, *, publish_current_on_bootstrap: bool = False, message_limit: int = MAX_TELEGRAM_MESSAGE_LENGTH) -> int:
    events = await fetch_active_events()
    current = {str(event.event_id): event for event in events}
    value = state.read()
    if value is None:
        value = {"version": STATE_VERSION, "events": {}}
        if not publish_current_on_bootstrap:
            value["events"] = {key: {"first_seen_at": now.isoformat(), "published_at": None} for key in current}
            state.write(value)
            return 0
    seen = _prune(value["events"], now)
    new_events = [event for key, event in current.items() if key not in seen]
    sent = 0
    for identifiers, message in format_messages(new_events, max_length=message_limit) if new_events else ():
        await send(message)
        for identifier in identifiers:
            seen[str(identifier)] = {"first_seen_at": now.isoformat(), "published_at": now.isoformat()}
        state.write({"version": STATE_VERSION, "events": seen})
        sent += len(identifiers)
    if sent == 0:
        state.write({"version": STATE_VERSION, "events": seen})
    return sent
