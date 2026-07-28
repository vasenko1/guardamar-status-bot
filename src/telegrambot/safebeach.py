"""Fetch and normalize the minimal SafeBeach data used by the digest."""

import asyncio
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from .models import BeachStatus

SAFEBEACH_URL = "https://info.safebeach.es/guardamar-del-segura"
REQUEST_TIMEOUT_SECONDS = 10
HTML_LIMIT_BYTES = 500_000
TARGET_BEACH_NAME = "platja centre / babilònia"
NEARBY_BEACHES = {
    "platja centre / babilònia": "Centre",
    "platja la roqueta": "Roqueta",
    "platja dels vivers": "Vivers",
}

_MARKERS_PATTERN = re.compile(
    rb"window\.SB_MARKERS\s*=\s*(\[.*?\]);", re.DOTALL
)
_FLAG_PRIORITY = {"green": 1, "yellow": 2, "red": 3}
_FLAG_HEX = {
    "#00ff00": "green",
    "#008000": "green",
    "#f7d40e": "yellow",
    "#ffff00": "yellow",
    "#fd0002": "red",
    "#ff0000": "red",
}


class SafeBeachError(RuntimeError):
    """Raised when SafeBeach data cannot be safely retrieved or parsed."""


def _read_page() -> bytes:
    request = urllib.request.Request(
        SAFEBEACH_URL,
        headers={
            "Accept": "text/html",
            "User-Agent": "GuardamarMorningDigest/0.1",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            final_url = urllib.parse.urlparse(response.geturl())
            if (
                final_url.scheme != "https"
                or final_url.hostname != "info.safebeach.es"
            ):
                raise SafeBeachError(
                    "SafeBeach returned an unexpected redirect"
                )
            payload = response.read(HTML_LIMIT_BYTES + 1)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise SafeBeachError("SafeBeach request failed") from exc

    if len(payload) > HTML_LIMIT_BYTES:
        raise SafeBeachError(
            "SafeBeach response exceeded the configured size limit"
        )
    return payload


def _flag_color(item: Dict[str, Any]) -> Optional[str]:
    label = item.get("textoBandera")
    if isinstance(label, str):
        normalized = label.casefold()
        for color in _FLAG_PRIORITY:
            if color in normalized:
                return color
        spanish = {"verde": "green", "amarilla": "yellow", "roja": "red"}
        for word, color in spanish.items():
            if word in normalized:
                return color

    color = item.get("colorBandera")
    if isinstance(color, str):
        return _FLAG_HEX.get(color.casefold())
    return None


def _sea_temperature(value: Any) -> Optional[int]:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*º?\s*C?\s*", value)
    if not match:
        return None
    temperature = float(match.group(1).replace(",", "."))
    if not math.isfinite(temperature) or not 0 <= temperature <= 40:
        return None
    return round(temperature)


def _wind_speed_kmh(value: Any) -> Optional[int]:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*(\d+(?:[.,]\d+)?)\s*m/s\s*",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    speed_mps = float(match.group(1).replace(",", "."))
    if not math.isfinite(speed_mps) or not 0 <= speed_mps <= 50:
        return None
    return round(speed_mps * 3.6)


def _wind_direction(value: Any) -> Optional[str]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    degrees = float(value)
    if not math.isfinite(degrees) or not 0 <= degrees <= 360:
        return None
    directions = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    return directions[round(degrees / 22.5) % 16]


def _sea_state(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    states = {
        "calma": "calm",
        "calmado": "calm",
        "tranquilo": "calm",
        "débil": "slight",
        "debil": "slight",
        "moderado": "moderate",
        "fuerte": "rough",
        "muy fuerte": "very_rough",
    }
    return states.get(normalized)


def normalize_beach_status(payload: bytes) -> Optional[BeachStatus]:
    """Return Centre conditions and individual nearby beach flags."""

    match = _MARKERS_PATTERN.search(payload)
    if match is None:
        raise SafeBeachError("SafeBeach page did not contain beach data")
    try:
        markers = json.loads(match.group(1).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeBeachError("SafeBeach returned invalid beach data") from exc
    if not isinstance(markers, list):
        raise SafeBeachError("SafeBeach beach data was not a list")

    centre = None
    nearby_flags = []
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        items = marker.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("hasActividad") is not True
                or item.get("serviceEnded") is not False
            ):
                continue
            beach_name = str(item.get("beachName", "")).strip().casefold()
            short_name = NEARBY_BEACHES.get(beach_name)
            if short_name is None:
                continue
            flag = _flag_color(item)
            if flag is not None:
                nearby_flags.append((short_name, flag))
            if beach_name == TARGET_BEACH_NAME:
                centre = (
                    flag,
                    _sea_temperature(item.get("waterTemp")),
                    _wind_direction(item.get("windDeg")),
                    _wind_speed_kmh(item.get("viento")),
                    _sea_state(item.get("oleaje")),
                )

    if centre is None and not nearby_flags:
        return None
    if centre is None:
        flag = sea_temperature = wind_direction = wind_speed = sea_state = None
    else:
        flag, sea_temperature, wind_direction, wind_speed, sea_state = centre
    order = {"Centre": 0, "Roqueta": 1, "Vivers": 2}
    nearby_flags.sort(key=lambda item: order[item[0]])
    return BeachStatus(
        flag_color=flag,
        sea_temperature_c=sea_temperature,
        wind_direction=wind_direction,
        wind_speed_kmh=wind_speed,
        sea_state=sea_state,
        nearby_flags=tuple(nearby_flags),
    )


async def fetch_beach_status() -> Optional[BeachStatus]:
    """Fetch the official public Guardamar SafeBeach status."""

    payload = await asyncio.to_thread(_read_page)
    return normalize_beach_status(payload)
