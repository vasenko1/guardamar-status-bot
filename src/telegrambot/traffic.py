"""Lightweight TomTom road- and lane-closure alerts for Guardamar."""

import asyncio
import fcntl
import html
import json
import logging
import os
import re
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Optional
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer

TRAFFIC_URL = "https://api.tomtom.com/maps/orbis/traffic/incidents/details"
REVERSE_URL = "https://api.tomtom.com/maps/orbis/places/reverseGeocode"
API_HOST = "api.tomtom.com"
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
GUARDAMAR_MUNICIPALITY = "Guardamar del Segura"
BBOX = "-0.7000,38.0250,-0.6200,38.1350"
CATEGORIES = frozenset({"roadClosed", "laneClosed"})
VALIDITIES = frozenset({"present", "future"})
PUBLISHABLE_PROBABILITIES = frozenset({"certain", "probable"})
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 512 * 1024
MAX_INCIDENTS = 512
MAX_STATE_EVENTS = 512
MAX_TEXT_LENGTH = 240
STATE_VERSION = 1
STATE_RETENTION = timedelta(days=14)
MISSING_CONFIRMATIONS = 2
DAILY_REPEAT_HOUR = 8

_STATE_REQUIRED_FIELDS = frozenset({
    "provider_id", "category", "validity", "probability",
    "starts_at", "ends_at", "from_place", "to_place",
    "descriptions_es", "coordinates", "location",
    "last_seen_at", "missing_successes",
})
_STATE_OPTIONAL_FIELDS = frozenset({
    "last_present_alert_date", "last_future_alert_date",
    "last_message_id", "last_alert_category", "pending_delivery",
    "end_notified_at", "ended_at",
})

_SENTINELS = frozenset({
    "null", "none", "undefined", "unknown", "n/a", "na", "-", "—",
})
_RU_MONTHS = (
    "",
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


class TrafficError(RuntimeError):
    """TomTom response or local traffic state is not trustworthy."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


class TrafficDeliveryUncertain(TrafficError):
    """Telegram may have accepted a non-idempotent traffic message."""

    def __init__(self) -> None:
        super().__init__("traffic alert delivery is uncertain", code="DELIVERY-UNCERTAIN")


@dataclass(frozen=True)
class TrafficIncident:
    provider_id: str
    category: str
    validity: str
    probability: str
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]
    from_place: Optional[str]
    to_place: Optional[str]
    descriptions_es: tuple[str, ...]
    coordinates: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class TrafficLocation:
    municipality: str
    subdivision: Optional[str]
    street: Optional[str]
    longitude: float
    latitude: float


def _clean_text(value: Any, *, limit: int = MAX_TEXT_LENGTH) -> Optional[str]:
    """Return safe source text, never stringifying null-like values."""

    if value is None or not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if not cleaned or len(cleaned) > limit:
        return None
    if cleaned.casefold() in _SENTINELS:
        return None
    return cleaned


def _parse_time(value: Any) -> Optional[datetime]:
    text = _clean_text(value, limit=80)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrafficError("TomTom incident timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise TrafficError("TomTom incident timestamp has no timezone")
    return parsed.astimezone(GUARDAMAR_TIMEZONE)


def _coordinate(value: Any, *, latitude: bool) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TrafficError("TomTom geometry coordinate is invalid")
    result = float(value)
    minimum, maximum = (-90.0, 90.0) if latitude else (-180.0, 180.0)
    if not minimum <= result <= maximum:
        raise TrafficError("TomTom geometry coordinate is out of range")
    return result


def _geometry(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, dict):
        raise TrafficError("TomTom incident geometry is missing")
    kind = value.get("type")
    raw = value.get("coordinates")
    if kind == "Point":
        if not isinstance(raw, list) or len(raw) < 2:
            raise TrafficError("TomTom point geometry is invalid")
        return ((_coordinate(raw[0], latitude=False), _coordinate(raw[1], latitude=True)),)
    if kind != "LineString" or not isinstance(raw, list) or not raw:
        raise TrafficError("TomTom incident geometry is not supported")
    points = []
    for point in raw:
        if not isinstance(point, list) or len(point) < 2:
            raise TrafficError("TomTom line geometry is invalid")
        points.append(
            (_coordinate(point[0], latitude=False), _coordinate(point[1], latitude=True))
        )
    return tuple(points)


def parse_incidents(payload: bytes) -> tuple[TrafficIncident, ...]:
    """Parse only road/lane closures while failing closed on malformed matches."""

    if len(payload) > RESPONSE_LIMIT_BYTES:
        raise TrafficError("TomTom traffic response is too large")
    try:
        root = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrafficError("TomTom traffic response is invalid JSON") from exc
    incidents = root.get("incidents") if isinstance(root, dict) else None
    if not isinstance(incidents, list) or len(incidents) > MAX_INCIDENTS:
        raise TrafficError("TomTom traffic response has an invalid incidents list")

    parsed: dict[str, TrafficIncident] = {}
    for feature in incidents:
        if not isinstance(feature, dict):
            raise TrafficError("TomTom traffic feature is invalid")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise TrafficError("TomTom traffic feature has no properties")
        main_category = _clean_text(properties.get("iconCategory"), limit=40)
        descriptions = []
        event_categories = set()
        raw_events = properties.get("events")
        if raw_events is None:
            raw_events = []
        if not isinstance(raw_events, list):
            raise TrafficError("TomTom incident events are invalid")
        for event in raw_events:
            if not isinstance(event, dict):
                raise TrafficError("TomTom incident event is invalid")
            description = _clean_text(event.get("description"))
            if description and description not in descriptions:
                descriptions.append(description)
            event_category = _clean_text(event.get("iconCategory"), limit=40)
            if event_category:
                event_categories.add(event_category)

        closure_categories = set(event_categories)
        if main_category in CATEGORIES:
            closure_categories.add(main_category)
        if "roadClosed" in closure_categories:
            category = "roadClosed"
        elif "laneClosed" in closure_categories:
            category = "laneClosed"
        else:
            continue

        provider_id = _clean_text(properties.get("id"), limit=300)
        validity = _clean_text(properties.get("timeValidity"), limit=40)
        probability = _clean_text(properties.get("probabilityOfOccurrence"), limit=40)
        if provider_id is None or validity not in VALIDITIES or probability is None:
            raise TrafficError("TomTom closure has invalid required fields")

        incident = TrafficIncident(
            provider_id=provider_id,
            category=category,
            validity=validity,
            probability=probability,
            starts_at=_parse_time(properties.get("startTime")),
            ends_at=_parse_time(properties.get("endTime")),
            from_place=_clean_text(properties.get("from")),
            to_place=_clean_text(properties.get("to")),
            descriptions_es=tuple(descriptions),
            coordinates=_geometry(feature.get("geometry")),
        )
        previous = parsed.get(provider_id)
        if previous is not None and previous != incident:
            raise TrafficError("TomTom returned conflicting duplicate incident IDs")
        parsed[provider_id] = incident
    return tuple(parsed[key] for key in sorted(parsed))


def _is_tomtom_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == API_HOST


def _request_json(url: str, api_key: str, *, attributes: str) -> bytes:
    if not api_key or any(character in api_key for character in "\r\n"):
        raise TrafficError("TomTom API key is missing or invalid", code="CONFIG")
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_is_tomtom_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "Accept-Language": "es-ES",
                "Attributes": attributes,
                "TomTom-Api-Key": api_key,
                "TomTom-Api-Version": "2",
                "User-Agent": "GuardamarMorningDigest/0.15",
            },
            follow_redirects=False,
        )
    except BoundedFetchError as exc:
        raise TrafficError(
            f"TomTom request failed: {exc.code}", code=exc.code
        ) from exc
    return payload


def _read_incidents(api_key: str) -> tuple[TrafficIncident, ...]:
    query = urllib.parse.urlencode({
        "apiVersion": "2",
        "bbox": BBOX,
        "timeValidity": "present,future",
    })
    attributes = (
        "incidents(type,geometry(type,coordinates),properties("
        "id,iconCategory,events(description,code,iconCategory),"
        "startTime,endTime,from,to,timeValidity,probabilityOfOccurrence))"
    )
    return parse_incidents(_request_json(f"{TRAFFIC_URL}?{query}", api_key, attributes=attributes))


async def fetch_incidents(api_key: str) -> tuple[TrafficIncident, ...]:
    """Fetch one bounded traffic snapshot."""

    return await asyncio.to_thread(_read_incidents, api_key)


def _parse_reverse(payload: bytes, longitude: float, latitude: float) -> Optional[TrafficLocation]:
    try:
        root = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrafficError("TomTom reverse-geocode response is invalid JSON") from exc
    results = root.get("results") if isinstance(root, dict) else None
    if not isinstance(results, list):
        raise TrafficError("TomTom reverse-geocode response has no results list")
    for result in results:
        if not isinstance(result, dict):
            continue
        address = result.get("address")
        if not isinstance(address, dict):
            continue
        municipality = _clean_text(address.get("municipality"))
        if municipality is None:
            continue
        return TrafficLocation(
            municipality=municipality,
            subdivision=_clean_text(address.get("municipalitySubdivision")),
            street=_clean_text(address.get("street")),
            longitude=longitude,
            latitude=latitude,
        )
    return None


def _reverse_geocode(api_key: str, longitude: float, latitude: float) -> Optional[TrafficLocation]:
    query = urllib.parse.urlencode({
        "position": f"{longitude:.7f},{latitude:.7f}",
        "radiusInMeters": "75",
    })
    attributes = "results(type,title,position,address(*))"
    payload = _request_json(f"{REVERSE_URL}?{query}", api_key, attributes=attributes)
    return _parse_reverse(payload, longitude, latitude)


async def resolve_guardamar_location(
    incident: TrafficIncident,
    api_key: str,
) -> Optional[TrafficLocation]:
    """Resolve midpoint first and endpoints only for a possible boundary crossing."""

    points = incident.coordinates
    candidates = [points[len(points) // 2]]
    if len(points) > 1:
        for point in (points[0], points[-1]):
            if point not in candidates:
                candidates.append(point)
    for longitude, latitude in candidates:
        location = await asyncio.to_thread(
            _reverse_geocode, api_key, longitude, latitude
        )
        if (
            location is not None
            and location.municipality == GUARDAMAR_MUNICIPALITY
        ):
            return location
    return None


def _strip_urbanization(value: Optional[str]) -> Optional[str]:
    value = _clean_text(value)
    if value is None:
        return None
    stripped = re.sub(
        r"^(?:urbanizaci[oó]n|urbanitzaci[oó]|urb\.)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return stripped or None


def location_label(incident: TrafficIncident, location: TrafficLocation) -> str:
    """Build a stable label without ever rendering null-like source values."""

    subdivision = _strip_urbanization(location.subdivision)
    street = _clean_text(location.street)
    from_place = _clean_text(incident.from_place)
    to_place = _clean_text(incident.to_place)

    base = street
    if base and from_place and to_place and from_place != to_place:
        base = f"{base} — между {from_place} и {to_place}"
    elif base is None and from_place and to_place and from_place != to_place:
        base = f"{from_place} — {to_place}"
    elif base is None:
        base = from_place or to_place

    if subdivision and base:
        return f"{subdivision} — {base}"
    if subdivision:
        return subdivision
    return base or "Участок дороги в Гуардамаре"


def _map_url(location: TrafficLocation) -> str:
    query = f"{location.latitude:.7f},{location.longitude:.7f}"
    return "https://www.google.com/maps/search/?" + urllib.parse.urlencode({
        "api": "1", "query": query,
    })


def _map_line(incident: TrafficIncident, location: TrafficLocation) -> str:
    label = location_label(incident, location)
    return (
        f'📍 <a href="{html.escape(_map_url(location), quote=True)}">'
        f"<b>{html.escape(label)}</b></a>"
    )


def _time_label(value: datetime, *, include_date: bool) -> str:
    local = value.astimezone(GUARDAMAR_TIMEZONE)
    if include_date:
        return f"{local:%H:%M} {local.day} {_RU_MONTHS[local.month]}"
    return f"{local:%H:%M}"


def _place_phrase(location: TrafficLocation) -> str:
    subdivision = _strip_urbanization(location.subdivision)
    street = _clean_text(location.street)
    if subdivision and street:
        return f"в урбанизации {subdivision}, на {street}"
    if subdivision:
        return f"в урбанизации {subdivision}"
    if street:
        return f"в Гуардамаре, на {street}"
    return "в Гуардамаре"


def _sentence_start(value: str) -> str:
    """Upper-case only the first character without lower-casing proper names."""

    return value[:1].upper() + value[1:]


def fallback_body(
    incident: TrafficIncident,
    location: TrafficLocation,
    mode: str,
    now: datetime,
) -> str:
    """Deterministic publication fallback when editorial AI is unavailable."""

    place = _place_phrase(location)
    if mode == "future_tomorrow":
        start = incident.starts_at
        when = (
            f" с {_time_label(start, include_date=False)}"
            if start is not None else ""
        )
        if incident.category == "roadClosed":
            body = f"Завтра{when} {place} будет перекрыт проезд."
        else:
            body = f"Завтра{when} {place} будет перекрыта полоса движения."
    elif mode == "ongoing":
        body = (
            f"Проезд {place} остаётся перекрыт."
            if incident.category == "roadClosed"
            else f"{_sentence_start(place)} остаётся перекрыта полоса движения."
        )
    elif mode == "category_change":
        if incident.category == "roadClosed":
            body = f"{_sentence_start(place)} теперь полностью перекрыт проезд."
        else:
            body = (
                f"{_sentence_start(place)} полное перекрытие снято, "
                "но полоса движения остаётся закрыта."
            )
    else:
        if incident.category == "roadClosed":
            body = f"{_sentence_start(place)} перекрыт проезд."
        else:
            body = f"{_sentence_start(place)} перекрыта полоса движения."
        start = incident.starts_at
        if (
            mode == "new_present"
            and start is not None
            and start <= now.astimezone(GUARDAMAR_TIMEZONE)
        ):
            include_date = (
                start.astimezone(GUARDAMAR_TIMEZONE).date()
                != now.astimezone(GUARDAMAR_TIMEZONE).date()
            )
            body += (
                " Ограничение действует с "
                f"{_time_label(start, include_date=include_date)}."
            )

    end = incident.ends_at
    if end is not None and end > now.astimezone(GUARDAMAR_TIMEZONE):
        include_date = end.date() != now.astimezone(GUARDAMAR_TIMEZONE).date()
        body += (
            " Ожидается, что ограничение будет действовать до "
            f"{_time_label(end, include_date=include_date)}."
        )
    return body


def _title(category: str) -> str:
    if category not in CATEGORIES:
        raise TrafficError("traffic alert category is invalid")
    return "🚧 <b>Перекрытие участка дороги</b>"


def build_alert_message(
    incident: TrafficIncident,
    location: TrafficLocation,
    body_ru: str,
) -> str:
    body = " ".join(body_ru.split()).strip()
    if not body or len(body) > 900:
        raise TrafficError("traffic alert body is invalid")
    folded = body.casefold()
    if re.search(r"\b(?:null|none|undefined)\b", folded):
        raise TrafficError("traffic alert body contains a null-like token")
    return with_footer(
        f"{_title(incident.category)}\n\n"
        f"{html.escape(body)}\n\n"
        f"{_map_line(incident, location)}"
    )


def _record_incident(record: dict) -> TrafficIncident:
    if not isinstance(record, dict):
        raise TrafficError("traffic state event is invalid", code="STATE")
    provider_id = _clean_text(record.get("provider_id"), limit=300)
    category = _clean_text(record.get("category"), limit=40)
    validity = _clean_text(record.get("validity"), limit=40)
    probability = _clean_text(record.get("probability"), limit=40)
    if (
        provider_id is None
        or category not in CATEGORIES
        or validity not in VALIDITIES
        or probability is None
    ):
        raise TrafficError("traffic state event is invalid", code="STATE")

    coordinates = record.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise TrafficError("traffic state geometry is invalid", code="STATE")
    normalized_coordinates = []
    for point in coordinates:
        if not isinstance(point, list) or len(point) != 2:
            raise TrafficError("traffic state geometry is invalid", code="STATE")
        normalized_coordinates.append((
            _coordinate(point[0], latitude=False),
            _coordinate(point[1], latitude=True),
        ))

    raw_descriptions = record.get("descriptions_es")
    if not isinstance(raw_descriptions, list):
        raise TrafficError("traffic state descriptions are invalid", code="STATE")
    descriptions = []
    for item in raw_descriptions:
        if item is not None and not isinstance(item, str):
            raise TrafficError("traffic state descriptions are invalid", code="STATE")
        value = _clean_text(item)
        if value and value not in descriptions:
            descriptions.append(value)

    return TrafficIncident(
        provider_id=provider_id,
        category=category,
        validity=validity,
        probability=probability,
        starts_at=_parse_time(record.get("starts_at")),
        ends_at=_parse_time(record.get("ends_at")),
        from_place=_clean_text(record.get("from_place")),
        to_place=_clean_text(record.get("to_place")),
        descriptions_es=tuple(descriptions),
        coordinates=tuple(normalized_coordinates),
    )


def _record_location(record: dict) -> TrafficLocation:
    location = record.get("location")
    if not isinstance(location, dict):
        raise TrafficError("traffic state location is invalid", code="STATE")
    municipality = _clean_text(location.get("municipality"))
    if municipality is None:
        raise TrafficError("traffic state municipality is invalid", code="STATE")
    longitude = location.get("longitude")
    latitude = location.get("latitude")
    return TrafficLocation(
        municipality=municipality,
        subdivision=_clean_text(location.get("subdivision")),
        street=_clean_text(location.get("street")),
        longitude=_coordinate(longitude, latitude=False),
        latitude=_coordinate(latitude, latitude=True),
    )


def _location_data(location: TrafficLocation) -> dict:
    return {
        "municipality": location.municipality,
        "subdivision": location.subdivision,
        "street": location.street,
        "longitude": location.longitude,
        "latitude": location.latitude,
    }


def _serialize_incident(incident: TrafficIncident, location: TrafficLocation) -> dict:
    return {
        "provider_id": incident.provider_id,
        "category": incident.category,
        "validity": incident.validity,
        "probability": incident.probability,
        "starts_at": incident.starts_at.isoformat() if incident.starts_at else None,
        "ends_at": incident.ends_at.isoformat() if incident.ends_at else None,
        "from_place": incident.from_place,
        "to_place": incident.to_place,
        "descriptions_es": list(incident.descriptions_es),
        "coordinates": [[lon, lat] for lon, lat in incident.coordinates],
        "location": _location_data(location),
    }


def traffic_facts(
    incident: TrafficIncident,
    location: TrafficLocation,
    mode: str,
    now: datetime,
    *,
    previous_category: Optional[str] = None,
) -> dict:
    """Return only known facts; unknown values are omitted, never serialized as null."""

    facts: dict[str, Any] = {
        "mode": mode,
        "category": incident.category,
        "municipality": location.municipality,
        "location_label": location_label(incident, location),
        "today": now.astimezone(GUARDAMAR_TIMEZONE).date().isoformat(),
    }
    optional = {
        "urbanization": _strip_urbanization(location.subdivision),
        "street": _clean_text(location.street),
        "from": _clean_text(incident.from_place),
        "to": _clean_text(incident.to_place),
        "start_local": (
            incident.starts_at.astimezone(GUARDAMAR_TIMEZONE).isoformat()
            if incident.starts_at else None
        ),
        "end_local": (
            incident.ends_at.astimezone(GUARDAMAR_TIMEZONE).isoformat()
            if incident.ends_at
            and incident.ends_at > now.astimezone(GUARDAMAR_TIMEZONE)
            else None
        ),
        "previous_category": previous_category,
    }
    for key, value in optional.items():
        if value is not None:
            facts[key] = value
    if incident.descriptions_es:
        facts["details_es"] = list(incident.descriptions_es)
    return facts


class TrafficState:
    """Small atomic active/recent incident state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def empty() -> dict:
        return {"version": STATE_VERSION, "events": {}}

    def read(self) -> dict:
        if not self.path.exists():
            return self.empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrafficError("traffic state is unreadable", code="STATE") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "events"}
            or value.get("version") != STATE_VERSION
            or not isinstance(value.get("events"), dict)
            or len(value["events"]) > MAX_STATE_EVENTS
        ):
            raise TrafficError("traffic state is invalid", code="STATE")
        for provider_id, record in value["events"].items():
            _validate_state_record(provider_id, record)
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
            raise TrafficError("traffic state could not be saved", code="STATE") from exc

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        lock = self.path.with_name(f".{self.path.name}.lock")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with lock.open("a", encoding="utf-8") as handle:
                os.chmod(lock, 0o600)
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        except BlockingIOError as exc:
            raise TrafficError(
                "another traffic monitor is active", code="STATE"
            ) from exc
        except OSError as exc:
            raise TrafficError("traffic state could not be locked", code="STATE") from exc


def _safe_iso(value: Any) -> Optional[datetime]:
    text = _clean_text(value, limit=80)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TrafficError("traffic state timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise TrafficError("traffic state timestamp has no timezone")
    return parsed


def _prune(events: dict, now: datetime) -> dict:
    cutoff = now - STATE_RETENTION
    result = {}
    for key, record in events.items():
        if not isinstance(key, str) or not isinstance(record, dict):
            continue
        last_seen = _safe_iso(record.get("last_seen_at"))
        if last_seen is None or last_seen >= cutoff:
            result[key] = record
    return result


def _alert_date(record: dict, name: str) -> Optional[date]:
    value = _clean_text(record.get(name), limit=20)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TrafficError("traffic state alert date is invalid") from exc


def _last_message_id(record: dict) -> Optional[int]:
    value = record.get("last_message_id")
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise TrafficError("traffic state message ID is invalid")
    return value


def _validate_state_record(provider_id: Any, record: Any) -> None:
    if (
        not isinstance(provider_id, str)
        or not provider_id
        or len(provider_id) > 300
        or not isinstance(record, dict)
        or not _STATE_REQUIRED_FIELDS.issubset(record)
        or set(record) - (_STATE_REQUIRED_FIELDS | _STATE_OPTIONAL_FIELDS)
    ):
        raise TrafficError("traffic state event is invalid", code="STATE")

    incident = _record_incident(record)
    location = _record_location(record)
    if (
        incident.provider_id != provider_id
        or location.municipality != GUARDAMAR_MUNICIPALITY
    ):
        raise TrafficError("traffic state event is inconsistent", code="STATE")

    last_seen = _safe_iso(record.get("last_seen_at"))
    if last_seen is None:
        raise TrafficError("traffic state last-seen time is invalid", code="STATE")

    missing = record.get("missing_successes")
    if not isinstance(missing, int) or isinstance(missing, bool) or missing < 0:
        raise TrafficError("traffic state missing counter is invalid", code="STATE")

    for field in ("last_present_alert_date", "last_future_alert_date"):
        if field in record:
            _alert_date(record, field)

    if "last_message_id" in record:
        _last_message_id(record)

    alert_category = _clean_text(record.get("last_alert_category"), limit=40)
    if (
        "last_alert_category" in record
        and alert_category not in CATEGORIES
    ):
        raise TrafficError("traffic state alert category is invalid", code="STATE")

    for field in ("end_notified_at", "ended_at"):
        if field in record and _safe_iso(record.get(field)) is None:
            raise TrafficError("traffic state lifecycle time is invalid", code="STATE")

    pending = record.get("pending_delivery")
    if pending is not None:
        if (
            not isinstance(pending, dict)
            or set(pending) != {"at", "marker", "value"}
            or _safe_iso(pending.get("at")) is None
            or _clean_text(pending.get("marker"), limit=40) is None
            or _clean_text(pending.get("value"), limit=80) is None
        ):
            raise TrafficError("traffic pending delivery state is invalid", code="STATE")


async def _deliver(
    state: TrafficState,
    value: dict,
    record: dict,
    *,
    message: str,
    publish: Callable[[str, Optional[int]], Awaitable[int]],
    reply_to: Optional[int],
    marker: str,
    marker_value: str,
    remember: Optional[dict[str, Any]] = None,
) -> int:
    missing = object()
    previous_marker = record.get(marker, missing)
    previous_pending = record.get("pending_delivery", missing)
    previous_remember = {
        key: record.get(key, missing) for key in (remember or {})
    }
    record[marker] = marker_value
    for key, remembered_value in (remember or {}).items():
        record[key] = remembered_value
    record["pending_delivery"] = {
        "at": datetime.now(GUARDAMAR_TIMEZONE).isoformat(),
        "marker": marker,
        "value": marker_value,
    }
    state.write(value)
    try:
        message_id = await publish(message, reply_to)
    except TrafficDeliveryUncertain:
        logging.warning("Traffic delivery uncertain; automatic resend suppressed")
        raise
    except Exception:
        if previous_marker is missing:
            record.pop(marker, None)
        else:
            record[marker] = previous_marker
        if previous_pending is missing:
            record.pop("pending_delivery", None)
        else:
            record["pending_delivery"] = previous_pending
        for key, previous_value in previous_remember.items():
            if previous_value is missing:
                record.pop(key, None)
            else:
                record[key] = previous_value
        state.write(value)
        raise
    record["last_message_id"] = message_id
    record.pop("pending_delivery", None)
    state.write(value)
    return 1


async def monitor_traffic(
    state: TrafficState,
    now: datetime,
    tomtom_api_key: str,
    compose_body: Callable[[dict], Awaitable[Optional[str]]],
    publish: Callable[[str, Optional[int]], Awaitable[int]],
    *,
    fetcher: Callable[[str], Awaitable[tuple[TrafficIncident, ...]]] = fetch_incidents,
    locator: Callable[[TrafficIncident, str], Awaitable[Optional[TrafficLocation]]] = resolve_guardamar_location,
) -> int:
    """Run one hourly closure check and publish only resident-useful transitions."""

    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    local_day = local_now.date()
    incidents = await fetcher(tomtom_api_key)
    raw_ids = {incident.provider_id for incident in incidents}
    delivered = 0

    with state.exclusive_run():
        value = state.read()
        events = _prune(value["events"], local_now)
        value["events"] = events

        # Absence is meaningful only after a fully successful TomTom snapshot.
        for provider_id, record in list(events.items()):
            if provider_id in raw_ids:
                record["missing_successes"] = 0
                continue
            missing = record.get("missing_successes", 0)
            if not isinstance(missing, int) or isinstance(missing, bool) or missing < 0:
                raise TrafficError("traffic state missing counter is invalid")
            missing += 1
            record["missing_successes"] = missing
            if missing < MISSING_CONFIRMATIONS or record.get("ended_at"):
                continue

            previous_validity = _clean_text(record.get("validity"), limit=40)
            had_present_alert = _alert_date(record, "last_present_alert_date") is not None
            had_future_alert = _alert_date(record, "last_future_alert_date") is not None
            reply_to = _last_message_id(record)

            if (
                previous_validity == "present"
                and had_present_alert
                and reply_to is not None
            ):
                incident = _record_incident(record)
                location = _record_location(record)
                if incident.category == "roadClosed":
                    body = (
                        f"По актуальным данным, проезд по "
                        f"<b>{html.escape(location_label(incident, location))}</b> "
                        "снова открыт."
                    )
                    title = "✅ <b>Дорога снова открыта</b>"
                else:
                    body = (
                        f"По актуальным данным, ограничение полосы на "
                        f"<b>{html.escape(location_label(incident, location))}</b> "
                        "снято."
                    )
                    title = "✅ <b>Полоса движения снова открыта</b>"
                message = with_footer(
                    f"{title}\n\n{body}\n\n{_map_line(incident, location)}"
                )
                delivered += await _deliver(
                    state,
                    value,
                    record,
                    message=message,
                    publish=publish,
                    reply_to=reply_to,
                    marker="end_notified_at",
                    marker_value=local_now.isoformat(),
                )
            elif (
                previous_validity == "future"
                and had_future_alert
                and reply_to is not None
            ):
                incident = _record_incident(record)
                location = _record_location(record)
                message = with_footer(
                    "ℹ️ <b>Изменение планируемого ограничения</b>\n\n"
                    "Ранее запланированное ограничение больше не отображается "
                    "в актуальных данных TomTom. Перед поездкой лучше проверить маршрут.\n\n"
                    f"{_map_line(incident, location)}"
                )
                delivered += await _deliver(
                    state,
                    value,
                    record,
                    message=message,
                    publish=publish,
                    reply_to=reply_to,
                    marker="end_notified_at",
                    marker_value=local_now.isoformat(),
                )
            record["ended_at"] = local_now.isoformat()
            state.write(value)

        for incident in incidents:
            existing = events.get(incident.provider_id)
            reactivated = (
                existing is not None
                and _clean_text(existing.get("ended_at"), limit=80) is not None
            )
            if incident.probability not in PUBLISHABLE_PROBABILITIES:
                if existing is not None:
                    existing["last_seen_at"] = local_now.isoformat()
                    existing["missing_successes"] = 0
                    state.write(value)
                continue

            if existing is not None and not reactivated:
                location = _record_location(existing)
            else:
                try:
                    location = await locator(incident, tomtom_api_key)
                except TrafficError:
                    logging.warning(
                        "Traffic location lookup failed for new incident %s",
                        incident.provider_id,
                    )
                    continue
            if location is None or location.municipality != GUARDAMAR_MUNICIPALITY:
                continue

            lifecycle_existing = None if reactivated else existing
            old_incident = (
                _record_incident(lifecycle_existing)
                if lifecycle_existing is not None else None
            )
            old_category = old_incident.category if old_incident else None
            old_validity = old_incident.validity if old_incident else None
            last_message = (
                _last_message_id(lifecycle_existing)
                if lifecycle_existing is not None else None
            )
            previous_present_date = (
                _alert_date(lifecycle_existing, "last_present_alert_date")
                if lifecycle_existing is not None else None
            )
            previous_future_date = (
                _alert_date(lifecycle_existing, "last_future_alert_date")
                if lifecycle_existing is not None else None
            )
            last_alert_category = (
                _clean_text(lifecycle_existing.get("last_alert_category"), limit=40)
                if lifecycle_existing is not None else None
            )
            base = _serialize_incident(incident, location)
            if lifecycle_existing is not None:
                for key in (
                    "last_present_alert_date", "last_future_alert_date",
                    "last_message_id", "last_alert_category",
                    "pending_delivery",
                    "end_notified_at", "ended_at",
                ):
                    if key in existing:
                        base[key] = existing[key]
            base["last_seen_at"] = local_now.isoformat()
            base["missing_successes"] = 0
            base.pop("ended_at", None)
            base.pop("end_notified_at", None)
            events[incident.provider_id] = base
            record = base
            state.write(value)

            mode = None
            marker = None
            marker_value = local_day.isoformat()
            reply_to = None

            if incident.validity == "future":
                if (
                    incident.starts_at is not None
                    and incident.starts_at.astimezone(GUARDAMAR_TIMEZONE).date()
                    == local_day + timedelta(days=1)
                    and previous_future_date != local_day
                ):
                    mode = "future_tomorrow"
                    marker = "last_future_alert_date"
                else:
                    continue
            else:
                newly_present = (
                    lifecycle_existing is None
                    or old_validity != "present"
                    or previous_present_date is None
                )
                category_changed = (
                    lifecycle_existing is not None
                    and old_validity == "present"
                    and previous_present_date is not None
                    and (last_alert_category or old_category) != incident.category
                )
                if newly_present:
                    mode = "new_present"
                    marker = "last_present_alert_date"
                elif category_changed:
                    mode = "category_change"
                    marker = "last_present_alert_date"
                    reply_to = last_message
                elif (
                    previous_present_date != local_day
                    and local_now.hour >= DAILY_REPEAT_HOUR
                ):
                    mode = "ongoing"
                    marker = "last_present_alert_date"
                else:
                    continue

            if lifecycle_existing is not None:
                try:
                    refreshed_location = await locator(incident, tomtom_api_key)
                except TrafficError as exc:
                    logging.warning(
                        "Traffic location refresh failed for incident %s: %s",
                        incident.provider_id,
                        exc,
                    )
                else:
                    if (
                        refreshed_location is not None
                        and refreshed_location.municipality == GUARDAMAR_MUNICIPALITY
                    ):
                        location = refreshed_location
                        record["location"] = _location_data(location)
                        state.write(value)

            facts = traffic_facts(
                incident,
                location,
                mode,
                local_now,
                previous_category=old_category,
            )
            try:
                body = await compose_body(facts)
            except Exception as exc:
                logging.warning("Traffic editorial composition failed: %s", exc)
                body = None
            if not body:
                body = fallback_body(
                    incident,
                    location,
                    mode,
                    local_now
                )
            try:
                message = build_alert_message(incident, location, body)
            except TrafficError:
                body = fallback_body(
                    incident,
                    location,
                    mode,
                    local_now,
                )
                message = build_alert_message(incident, location, body)

            remember = (
                {"last_alert_category": incident.category}
                if incident.validity == "present" else None
            )
            delivered += await _deliver(
                state,
                value,
                record,
                message=message,
                publish=publish,
                reply_to=reply_to,
                marker=marker,
                marker_value=marker_value,
                remember=remember,
            )

        state.write(value)
    return delivered