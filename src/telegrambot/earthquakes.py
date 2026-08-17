"""Bounded local-earthquake monitoring from the official IGN GeoRSS feed."""

import asyncio
import fcntl
import html
import json
import math
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterator, Optional, Sequence
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer
from .sun import GUARDAMAR_LATITUDE, GUARDAMAR_LONGITUDE

IGN_RSS_URL = "https://www.ign.es/ign/RssTools/sismologia.xml"
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
REQUEST_TIMEOUT_SECONDS = 10
XML_LIMIT_BYTES = 256 * 1024
MAX_FEED_ITEMS = 128
MAX_STATE_EVENTS = 256
MAX_ALERTS_PER_RUN = 3
STATE_RETENTION = timedelta(days=14)
MAX_NEW_EVENT_AGE = timedelta(hours=3)
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_DISTANCE_KM = 10.0
MIN_MAGNITUDE = 2.7
STATE_VERSION = 1

_GEO_NAMESPACE = "http://www.w3.org/2003/01/geo/wgs84_pos#"
_DESCRIPTION = re.compile(
    r"Se ha producido un terremoto de magnitud "
    r"(?P<magnitude>\d+(?:[.,]\d+)?) en (?P<location>.+?) "
    r"en la fecha (?P<date>\d{2}/\d{2}/\d{4}) "
    r"(?P<time>\d{1,2}:\d{2}:\d{2}) en la siguiente localización: "
    r"(?P<latitude>-?\d+(?:\.\d+)?),(?P<longitude>-?\d+(?:\.\d+)?)"
)


class EarthquakeError(RuntimeError):
    """Raised when the IGN source or local monitor state is not trustworthy."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


@dataclass(frozen=True)
class Earthquake:
    event_id: str
    occurred_at: datetime
    magnitude: float
    latitude: float
    longitude: float
    location: str


def _is_ign_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.ign.es"
        and parsed.path == "/ign/RssTools/sismologia.xml"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _normalized_text(value: Optional[str]) -> str:
    return " ".join((value or "").split())


def _event_id(value: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "www.ign.es":
        return None
    identifiers = urllib.parse.parse_qs(parsed.query).get("evid", ())
    if len(identifiers) != 1 or not re.fullmatch(r"es[0-9a-z]+", identifiers[0]):
        return None
    return identifiers[0]


def _parse_item(item: ET.Element) -> Optional[Earthquake]:
    guid = _normalized_text(item.findtext("guid"))
    event_id = _event_id(guid)
    match = _DESCRIPTION.fullmatch(_normalized_text(item.findtext("description")))
    latitude_text = _normalized_text(item.findtext(f"{{{_GEO_NAMESPACE}}}lat"))
    longitude_text = _normalized_text(item.findtext(f"{{{_GEO_NAMESPACE}}}long"))
    if event_id is None or match is None or not latitude_text or not longitude_text:
        return None
    try:
        magnitude = float(match.group("magnitude").replace(",", "."))
        latitude = float(latitude_text)
        longitude = float(longitude_text)
        described_latitude = float(match.group("latitude"))
        described_longitude = float(match.group("longitude"))
        occurred_at = datetime.strptime(
            f"{match.group('date')} {match.group('time')}",
            "%d/%m/%Y %H:%M:%S",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if not (
        0.0 <= magnitude <= 10.0
        and -90.0 <= latitude <= 90.0
        and -180.0 <= longitude <= 180.0
        and abs(latitude - described_latitude) <= 0.0001
        and abs(longitude - described_longitude) <= 0.0001
    ):
        return None
    location = _normalized_text(match.group("location"))
    if not location or len(location) > 120:
        return None
    return Earthquake(
        event_id=event_id,
        occurred_at=occurred_at,
        magnitude=magnitude,
        latitude=latitude,
        longitude=longitude,
        location=location,
    )


def parse_earthquakes(payload: bytes) -> tuple[Earthquake, ...]:
    """Parse a bounded IGN GeoRSS document and reject ambiguous duplicates."""

    if len(payload) > XML_LIMIT_BYTES or b"<!DOCTYPE" in payload.upper():
        raise EarthquakeError("IGN earthquake feed is unsafe")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise EarthquakeError("IGN earthquake feed is invalid XML") from exc
    if root.tag != "rss" or root.get("version") != "2.0":
        raise EarthquakeError("IGN earthquake feed has an invalid root")
    channel = root.find("channel")
    if channel is None:
        raise EarthquakeError("IGN earthquake feed has no channel")
    items = channel.findall("item")
    if len(items) > MAX_FEED_ITEMS:
        raise EarthquakeError("IGN earthquake feed has too many items")
    parsed: dict[str, Earthquake] = {}
    conflicts = set()
    for item in items:
        event = _parse_item(item)
        if event is None:
            continue
        previous = parsed.get(event.event_id)
        if previous is not None and previous != event:
            conflicts.add(event.event_id)
        else:
            parsed[event.event_id] = event
    for event_id in conflicts:
        parsed.pop(event_id, None)
    if items and not parsed:
        raise EarthquakeError("IGN earthquake feed has no valid items")
    return tuple(sorted(parsed.values(), key=lambda event: event.occurred_at))


def _read_feed() -> tuple[Earthquake, ...]:
    try:
        payload, _, _ = fetch_bounded(
            IGN_RSS_URL,
            is_allowed_url=_is_ign_url,
            accepted_types=frozenset({
                "application/xml",
                "application/rss+xml",
                "text/xml",
            }),
            limit_bytes=XML_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/xml,text/xml",
                "Accept-Language": "es",
                "User-Agent": "GuardamarMorningDigest/0.13",
            },
        )
    except BoundedFetchError as exc:
        raise EarthquakeError(
            "IGN earthquake feed is unavailable", code=exc.code
        ) from exc
    return parse_earthquakes(payload)


async def fetch_earthquakes() -> tuple[Earthquake, ...]:
    """Fetch the official feed once without an internal retry."""

    return await asyncio.to_thread(_read_feed)


def distance_and_bearing(event: Earthquake) -> tuple[float, float]:
    """Return great-circle distance and initial bearing from Guardamar."""

    radius_km = 6371.0088
    origin_lat = math.radians(GUARDAMAR_LATITUDE)
    target_lat = math.radians(event.latitude)
    delta_lat = target_lat - origin_lat
    delta_lon = math.radians(event.longitude - GUARDAMAR_LONGITUDE)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(origin_lat)
        * math.cos(target_lat)
        * math.sin(delta_lon / 2.0) ** 2
    )
    distance = radius_km * 2.0 * math.asin(min(1.0, math.sqrt(haversine)))
    y = math.sin(delta_lon) * math.cos(target_lat)
    x = (
        math.cos(origin_lat) * math.sin(target_lat)
        - math.sin(origin_lat)
        * math.cos(target_lat)
        * math.cos(delta_lon)
    )
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return distance, bearing


def qualifies(event: Earthquake) -> bool:
    distance, _ = distance_and_bearing(event)
    return event.magnitude >= MIN_MAGNITUDE and distance <= MAX_DISTANCE_KM


def _direction(bearing: float) -> str:
    directions = (
        "к северу",
        "к северо-востоку",
        "к востоку",
        "к юго-востоку",
        "к югу",
        "к юго-западу",
        "к западу",
        "к северо-западу",
    )
    return directions[int((bearing + 22.5) // 45.0) % len(directions)]


def _map_url(event: Earthquake) -> str:
    return (
        "https://maps.google.com/?q="
        f"{event.latitude:.4f},{event.longitude:.4f}"
    )


def build_earthquake_message(event: Earthquake) -> str:
    """Render one compact, forwarding-safe local earthquake notice."""

    distance, bearing = distance_and_bearing(event)
    local_time = event.occurred_at.astimezone(GUARDAMAR_TIMEZONE)
    magnitude = f"{event.magnitude:.1f}".replace(".", ",")
    if distance < 0.5:
        place = "в районе Гуардамара"
    else:
        rounded_distance = max(1, math.floor(distance + 0.5))
        place = (
            f"примерно в {rounded_distance} км {_direction(bearing)} "
            "от Гуардамара"
        )
    message = "\n".join((
        "📈 <b>Землетрясение рядом с Гуардамаром</b>",
        "",
        f"🕒 {local_time:%H:%M} - зарегистрировано землетрясение "
        f"магнитудой <b>{magnitude}</b>",
        "",
        f'📍 <a href="{html.escape(_map_url(event), quote=True)}">'
        f"Эпицентр: {html.escape(place)}</a>",
    ))
    return with_footer(message)


class EarthquakeState:
    """Store only bounded event identifiers needed for deduplication."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def empty() -> dict:
        return {"version": STATE_VERSION, "initialized": False, "events": []}

    def read(self) -> dict:
        if not self.path.exists():
            return self.empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EarthquakeError("earthquake state is unreadable", code="STATE") from exc
        if (
            not isinstance(value, dict)
            or value.get("version") != STATE_VERSION
            or not isinstance(value.get("initialized"), bool)
            or not isinstance(value.get("events"), list)
            or len(value["events"]) > MAX_STATE_EVENTS
        ):
            raise EarthquakeError("earthquake state is invalid", code="STATE")
        identifiers = set()
        for item in value["events"]:
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "occurred_at"}
                or not isinstance(item["id"], str)
                or re.fullmatch(r"es[0-9a-z]+", item["id"]) is None
                or not isinstance(item["occurred_at"], str)
                or item["id"] in identifiers
            ):
                raise EarthquakeError("earthquake state is invalid", code="STATE")
            try:
                occurred_at = datetime.fromisoformat(item["occurred_at"])
            except ValueError as exc:
                raise EarthquakeError(
                    "earthquake state is invalid", code="STATE"
                ) from exc
            if occurred_at.tzinfo is None:
                raise EarthquakeError("earthquake state is invalid", code="STATE")
            identifiers.add(item["id"])
        return value

    def write(self, value: dict) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise EarthquakeError(
                "earthquake state could not be saved", code="STATE"
            ) from exc

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a", encoding="utf-8") as lock:
                os.chmod(lock_path, 0o600)
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        except BlockingIOError as exc:
            raise EarthquakeError(
                "another earthquake monitor is active", code="STATE"
            ) from exc
        except OSError as exc:
            raise EarthquakeError(
                "earthquake state could not be locked", code="STATE"
            ) from exc


def prune_state(value: dict, now: datetime) -> bool:
    """Remove expired identifiers and enforce the hard state-size bound."""

    cutoff = now.astimezone(timezone.utc) - STATE_RETENTION
    retained = []
    for item in value["events"]:
        occurred_at = datetime.fromisoformat(item["occurred_at"])
        if occurred_at.astimezone(timezone.utc) >= cutoff:
            retained.append(item)
    retained.sort(key=lambda item: item["occurred_at"], reverse=True)
    retained = retained[:MAX_STATE_EVENTS]
    changed = retained != value["events"]
    value["events"] = retained
    return changed


def _remember(value: dict, event: Earthquake) -> None:
    value["events"].append({
        "id": event.event_id,
        "occurred_at": event.occurred_at.isoformat(),
    })
    value["events"].sort(key=lambda item: item["occurred_at"], reverse=True)
    del value["events"][MAX_STATE_EVENTS:]


async def monitor_earthquakes(
    now: datetime,
    state: EarthquakeState,
    fetcher: Callable[[], Awaitable[Sequence[Earthquake]]],
    sender: Callable[[str], Awaitable[int]],
) -> int:
    """Fetch once, seed silently, then deliver fresh qualifying events once."""

    with state.exclusive_run():
        value = state.read()
        if prune_state(value, now):
            state.write(value)
        events = tuple(await fetcher())
        known = {item["id"] for item in value["events"]}
        if not value["initialized"]:
            for event in events:
                if event.event_id not in known:
                    _remember(value, event)
            value["initialized"] = True
            state.write(value)
            return 0

        delivered = 0
        utc_now = now.astimezone(timezone.utc)
        for event in sorted(
            events, key=lambda item: item.occurred_at, reverse=True
        ):
            if event.event_id in known:
                continue
            age = utc_now - event.occurred_at.astimezone(timezone.utc)
            if (
                age < -MAX_FUTURE_SKEW
                or age > MAX_NEW_EVENT_AGE
                or not qualifies(event)
            ):
                _remember(value, event)
                known.add(event.event_id)
                state.write(value)
                continue
            if delivered >= MAX_ALERTS_PER_RUN:
                _remember(value, event)
                known.add(event.event_id)
                state.write(value)
                continue
            await sender(build_earthquake_message(event))
            _remember(value, event)
            known.add(event.event_id)
            state.write(value)
            delivered += 1
        return delivered
