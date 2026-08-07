"""Fetch and normalize the minimal SafeBeach data used by the digest."""

import asyncio
import json
import math
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from .models import BeachStatus

SAFEBEACH_URL = "https://info.safebeach.es/guardamar-del-segura"
REQUEST_TIMEOUT_SECONDS = 10
HTML_LIMIT_BYTES = 512 * 1024
BEACH_PRIORITY = {
    "platja centre / babilònia": "Centre",
    "platja la roqueta": "Roqueta",
    "platja dels vivers": "Vivers",
    "platja del montcaio": "Montcaio",
    "platja del camp": "Camp",
    "platja de les ortigues": "Ortigues",
}
BEACH_ORDER = {
    name: index for index, name in enumerate(BEACH_PRIORITY.values())
}
KNOWN_BEACHES = tuple(BEACH_PRIORITY.values())
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

_MARKERS_ASSIGNMENT = re.compile(rb"\bwindow\.SB_MARKERS\s*=\s*")
_PAGE_DATE_PATTERN = re.compile(
    rb"""<div\s+class=["']sub["'][^>]*>[^<]*?"""
    rb"(\d{2}/\d{2}/\d{4})\s*</div>",
    re.IGNORECASE,
)
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

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID",
        status: Optional[int] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.server_status = status
        self.safe_description = description


def _is_safebeach_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "info.safebeach.es"
    )


class _SafeBeachRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if not _is_safebeach_url(new_url):
            raise SafeBeachError(
                "SafeBeach redirected outside its public host",
                code="REDIRECT",
                description="сервер перенаправил запрос за пределы SafeBeach",
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _read_page() -> bytes:
    request = urllib.request.Request(
        SAFEBEACH_URL,
        headers={
            "Accept": "text/html",
            "Accept-Language": "es",
            "User-Agent": "GuardamarMorningDigest/0.11",
        },
    )
    try:
        opener = urllib.request.build_opener(
            _SafeBeachRedirectHandler()
        )
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if not _is_safebeach_url(response.geturl()):
                raise SafeBeachError(
                    "SafeBeach returned an unexpected URL",
                    code="REDIRECT",
                    description="получен недопустимый адрес ответа",
                )
            content_type = response.headers.get_content_type()
            if content_type != "text/html":
                raise SafeBeachError(
                    "SafeBeach returned an unexpected content type",
                    code="CONTENT-TYPE",
                    description=(
                        "сервер вернул содержимое не в формате HTML"
                    ),
                )
            payload = response.read(HTML_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SafeBeachError(
            f"SafeBeach HTTP status {exc.code}",
            code=f"HTTP-{exc.code}",
            status=exc.code,
            description=f"сервер вернул HTTP {exc.code}",
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise SafeBeachError(
            "SafeBeach request timed out",
            code="TIMEOUT",
            description="сервер не ответил до истечения тайм-аута",
        ) from exc
    except urllib.error.URLError as exc:
        raise SafeBeachError(
            "SafeBeach network request failed",
            code="NETWORK",
            description="не удалось установить сетевое соединение",
        ) from exc

    if len(payload) > HTML_LIMIT_BYTES:
        raise SafeBeachError(
            "SafeBeach response exceeded the configured size limit",
            code="TOO-LARGE",
            description="ответ превысил допустимый размер",
        )
    return payload


def _label_flag_color(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    colors = {
        "green"
        if word in {"green", "verde"}
        else "yellow"
        if word in {"yellow", "amarilla", "amarillo"}
        else "red"
        for word in re.findall(r"[a-záéíóúüñ]+", normalized)
        if word
        in {
            "green",
            "verde",
            "yellow",
            "amarilla",
            "amarillo",
            "red",
            "roja",
        }
    }
    return next(iter(colors)) if len(colors) == 1 else None


def _flag_color(
    item: Dict[str, Any],
) -> Tuple[Optional[str], bool]:
    label = item.get("textoBandera")
    label_color = _label_flag_color(label)
    color = item.get("colorBandera")
    hex_color = (
        _FLAG_HEX.get(color.strip().casefold())
        if isinstance(color, str)
        else None
    )
    if (
        label_color is not None
        and hex_color is not None
        and label_color != hex_color
    ):
        return None, False
    return label_color or hex_color, True


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


def _jellyfish_state(value: Any) -> Optional[bool]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in {"sí", "si", "yes"}:
        return True
    if normalized in {"no"}:
        return False
    return None


def _updated_time(value: Any) -> Optional[time]:
    if not isinstance(value, str):
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        return None


def _page_date(payload: bytes) -> date:
    match = _PAGE_DATE_PATTERN.search(payload)
    if match is None:
        raise SafeBeachError(
            "SafeBeach page had no current date",
            code="NO-DATE",
            description="страница не содержит календарную дату",
        )
    try:
        return datetime.strptime(
            match.group(1).decode("ascii"),
            "%d/%m/%Y",
        ).date()
    except (UnicodeDecodeError, ValueError) as exc:
        raise SafeBeachError(
            "SafeBeach page date was invalid",
            code="INVALID-DATE",
            description="страница содержит некорректную дату",
        ) from exc


def _markers(payload: bytes) -> Any:
    assignment = _MARKERS_ASSIGNMENT.search(payload)
    if assignment is None:
        raise SafeBeachError(
            "SafeBeach page did not contain beach data",
            code="NO-DATA",
            description="на странице отсутствует блок данных пляжей",
        )
    try:
        text = payload[assignment.end() :].decode("utf-8").lstrip()
        markers, _ = json.JSONDecoder().raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeBeachError(
            "SafeBeach returned invalid beach data",
            code="INVALID-JSON",
            description="данные пляжей не являются корректным JSON",
        ) from exc
    return markers


def normalize_beach_status(
    payload: bytes,
    expected_date: date,
) -> Optional[BeachStatus]:
    """Return Centre conditions and individual nearby beach flags."""

    source_date = _page_date(payload)
    if source_date != expected_date:
        raise SafeBeachError(
            "SafeBeach page date did not match today",
            code="STALE-DATE",
            description=(
                f"дата страницы {source_date:%d.%m.%Y} "
                f"не совпадает с текущей {expected_date:%d.%m.%Y}"
            ),
        )
    markers = _markers(payload)
    if not isinstance(markers, list):
        raise SafeBeachError(
            "SafeBeach beach data was not a list",
            code="INVALID-STRUCTURE",
            description="список пляжей имеет некорректную структуру",
        )

    records: Dict[str, Tuple[Any, ...]] = {}
    conflicted = set()
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
            short_name = BEACH_PRIORITY.get(beach_name)
            if short_name is None or short_name in conflicted:
                continue
            flag, flag_is_consistent = _flag_color(item)
            if not flag_is_consistent:
                conflicted.add(short_name)
                records.pop(short_name, None)
                continue
            record = (
                flag,
                _sea_temperature(item.get("waterTemp")),
                _wind_direction(item.get("windDeg")),
                _wind_speed_kmh(item.get("viento")),
                _sea_state(item.get("oleaje")),
                _jellyfish_state(item.get("medusas")),
                _updated_time(item.get("hora")),
            )
            previous = records.get(short_name)
            if previous is not None:
                previous_flag = previous[0]
                current_flag = record[0]
                previous_time = previous[6]
                current_time = record[6]
                if (
                    previous_time is not None
                    and current_time is not None
                    and previous_flag is not None
                    and current_flag is not None
                    and previous_flag != current_flag
                ):
                    conflicted.add(short_name)
                    records.pop(short_name, None)
                    continue
                if previous_time is not None and (
                    current_time is None or current_time <= previous_time
                ):
                    continue
            records[short_name] = record

    if not records:
        return None
    centre = records.get("Centre")
    if centre is None:
        flag = sea_temperature = wind_direction = wind_speed = sea_state = None
    else:
        (
            flag,
            sea_temperature,
            wind_direction,
            wind_speed,
            sea_state,
            _,
            _,
        ) = centre
    nearby_flags = [
        (name, record[0])
        for name, record in records.items()
        if record[0] is not None
    ]
    jellyfish_states = [
        (name, record[5])
        for name, record in records.items()
        if record[5] is not None
    ]
    jellyfish_beaches = [
        name for name, present in jellyfish_states if present
    ]
    updated_times = [
        (name, record[6])
        for name, record in records.items()
        if record[0] is not None and record[6] is not None
    ]
    nearby_flags.sort(key=lambda item: BEACH_ORDER[item[0]])
    jellyfish_beaches.sort(key=BEACH_ORDER.__getitem__)
    jellyfish_states.sort(key=lambda item: BEACH_ORDER[item[0]])
    updated_times.sort(key=lambda item: BEACH_ORDER[item[0]])
    return BeachStatus(
        flag_color=flag,
        sea_temperature_c=sea_temperature,
        source_date=source_date,
        wind_direction=wind_direction,
        wind_speed_kmh=wind_speed,
        sea_state=sea_state,
        nearby_flags=tuple(nearby_flags),
        jellyfish_beaches=tuple(jellyfish_beaches),
        jellyfish_states=tuple(jellyfish_states),
        updated_times=tuple(updated_times),
    )


def is_current_status(
    status: Optional[BeachStatus],
    now: datetime,
) -> bool:
    """Validate one or more current operational flags."""

    if status is None:
        return False
    expected = set(KNOWN_BEACHES)
    flag_names = [name for name, _ in status.nearby_flags]
    time_names = [name for name, _ in status.updated_times]
    jellyfish_names = list(status.jellyfish_beaches)
    jellyfish_state_names = [name for name, _ in status.jellyfish_states]
    flags = set(flag_names)
    times = dict(status.updated_times)
    if (
        not flags
        or len(flag_names) != len(flags)
        or len(time_names) != len(set(time_names))
        or len(jellyfish_names) != len(set(jellyfish_names))
        or len(jellyfish_state_names) != len(set(jellyfish_state_names))
        or not flags <= expected
        or set(times) != flags
        or not set(jellyfish_names) <= flags
        or not set(jellyfish_state_names) <= flags
        or (
            status.jellyfish_states
            and set(jellyfish_names) != {
                name
                for name, present in status.jellyfish_states
                if present
            }
        )
        or any(
            color not in {"green", "yellow", "red"}
            for _, color in status.nearby_flags
        )
    ):
        return False
    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    if status.source_date != local_now.date():
        return False
    latest_allowed = (
        local_now.hour * 60 + local_now.minute + 5
    )
    return all(
        updated.hour * 60 + updated.minute <= latest_allowed
        for updated in times.values()
    )


def is_complete_current_status(
    status: Optional[BeachStatus],
    now: datetime,
) -> bool:
    """Require every known Guardamar beach before the final attempt."""

    if not is_current_status(status, now):
        return False
    flags = {name for name, _ in status.nearby_flags}
    return flags == set(KNOWN_BEACHES)


def _current_status(
    status: Optional[BeachStatus],
    now: datetime,
) -> Optional[BeachStatus]:
    """Keep every timestamped current flag in product priority order."""

    if status is None:
        return None
    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    if status.source_date != local_now.date():
        return None
    latest_allowed = local_now.hour * 60 + local_now.minute + 5
    times = dict(status.updated_times)
    flags = [
        (name, color)
        for name, color in status.nearby_flags
        if (
            name in BEACH_ORDER
            and name in times
            and times[name].hour * 60 + times[name].minute <= latest_allowed
        )
    ]
    flags.sort(key=lambda item: BEACH_ORDER[item[0]])
    selected_flags = tuple(flags)
    if not selected_flags:
        return None
    selected_names = {name for name, _ in selected_flags}
    selected_times = tuple(
        (name, times[name]) for name, _ in selected_flags
    )
    centre_selected = "Centre" in selected_names
    return BeachStatus(
        flag_color=status.flag_color if centre_selected else None,
        sea_temperature_c=(
            status.sea_temperature_c if centre_selected else None
        ),
        source_date=status.source_date,
        wind_direction=status.wind_direction if centre_selected else None,
        wind_speed_kmh=status.wind_speed_kmh if centre_selected else None,
        sea_state=status.sea_state if centre_selected else None,
        nearby_flags=selected_flags,
        jellyfish_beaches=tuple(
            name
            for name in status.jellyfish_beaches
            if name in selected_names
        ),
        jellyfish_states=tuple(
            (name, present)
            for name, present in status.jellyfish_states
            if name in selected_names
        ),
        updated_times=selected_times,
    )


async def fetch_beach_status(
    now: Optional[datetime] = None,
) -> Optional[BeachStatus]:
    """Fetch the official public Guardamar SafeBeach status."""

    local_now = (
        now.astimezone(GUARDAMAR_TIMEZONE)
        if now is not None
        else datetime.now(GUARDAMAR_TIMEZONE)
    )
    payload = await asyncio.to_thread(_read_page)
    status = normalize_beach_status(payload, local_now.date())
    return _current_status(status, local_now)
