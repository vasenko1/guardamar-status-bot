"""Fetch and normalize the AEMET data used by the first MVP slice."""

import asyncio
import io
import json
import logging
import math
import tarfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from .models import MorningDigest, Warning, Weather

AEMET_API_ROOT = "https://opendata.aemet.es/opendata/api"
GUARDAMAR_MUNICIPALITY_CODE = "03076"
VALENCIAN_COMMUNITY_WARNING_AREA = "77"
GUARDAMAR_WARNING_ZONE = "Litoral sur de Alicante"
ROJALES_STATION_CODE = "7261X"
CENTRO_LA_ROQUETA_BEACH_CODE = "0307605"

REQUEST_TIMEOUT_SECONDS = 15
JSON_LIMIT_BYTES = 1_000_000
WARNING_LIMIT_BYTES = 4_000_000
WARNING_UNCOMPRESSED_LIMIT_BYTES = 8_000_000
OBSERVATION_MAX_AGE_SECONDS = 3 * 60 * 60
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

LOGGER = logging.getLogger(__name__)


class AemetError(RuntimeError):
    """Raised when AEMET data cannot be safely retrieved or interpreted."""


def _decode_json(payload: bytes) -> Any:
    for encoding in ("utf-8-sig", "iso-8859-15"):
        try:
            return json.loads(payload.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise AemetError("AEMET returned invalid JSON")


def _read_url(url: str, api_key: str, limit: int) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not (
        parsed.hostname == "aemet.es"
        or (parsed.hostname or "").endswith(".aemet.es")
    ):
        raise AemetError("AEMET returned an unexpected download URL")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, application/xml, application/zip",
            "User-Agent": "GuardamarMorningDigest/0.1",
            "api_key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            payload = response.read(limit + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise AemetError("AEMET request failed") from exc

    if len(payload) > limit:
        raise AemetError("AEMET response exceeded the configured size limit")
    return payload


async def _fetch_product(path: str, api_key: str, limit: int) -> bytes:
    metadata_bytes = await asyncio.to_thread(
        _read_url, f"{AEMET_API_ROOT}/{path}", api_key, JSON_LIMIT_BYTES
    )
    metadata = _decode_json(metadata_bytes)
    if not isinstance(metadata, dict) or metadata.get("estado") != 200:
        raise AemetError("AEMET did not provide a product download")

    download_url = metadata.get("datos")
    if not isinstance(download_url, str) or not download_url:
        raise AemetError("AEMET response did not contain a download URL")
    return await asyncio.to_thread(_read_url, download_url, api_key, limit)


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_daily_forecast(
    payload: bytes,
    local_day: date,
    local_hour: int = 0,
) -> Tuple[
    int,
    int,
    Optional[str],
    Optional[int],
    Optional[str],
    Optional[int],
    Optional[str],
]:
    """Return today's temperature, wind, sky, and remaining rain forecast."""

    documents = _decode_json(payload)
    if not isinstance(documents, list) or not documents:
        raise AemetError("AEMET daily forecast was empty")

    prediction = documents[0]
    if not isinstance(prediction, dict):
        raise AemetError("AEMET daily forecast had an invalid structure")
    prediction_data = prediction.get("prediccion")
    if not isinstance(prediction_data, dict):
        raise AemetError("AEMET daily forecast had an invalid structure")
    days = prediction_data.get("dia", [])
    if not isinstance(days, list):
        raise AemetError("AEMET daily forecast had an invalid day list")
    expected_date = local_day.isoformat()
    selected = next(
        (
            item
            for item in days
            if isinstance(item, dict)
            and str(item.get("fecha", "")).startswith(expected_date)
        ),
        None,
    )
    if selected is None:
        raise AemetError("AEMET daily forecast did not include today")

    temperatures = selected.get("temperatura", {})
    if not isinstance(temperatures, dict):
        raise AemetError("AEMET daily forecast had invalid temperatures")
    minimum = _as_int(temperatures.get("minima"))
    maximum = _as_int(temperatures.get("maxima"))
    if minimum is None or maximum is None:
        raise AemetError("AEMET daily forecast had no valid temperature range")

    condition_priority = {
        "clear": 0,
        "partly_cloudy": 1,
        "cloudy": 2,
        "fog": 3,
        "rain": 4,
        "snow": 5,
        "storm": 6,
    }
    sky_condition = None
    sky_items = selected.get("estadoCielo", [])
    if not isinstance(sky_items, list):
        sky_items = []
    for item in sky_items:
        if not isinstance(item, dict):
            continue
        description = item.get("descripcion")
        if not isinstance(description, str):
            continue
        normalized = unicodedata.normalize(
            "NFKD", description.strip().casefold()
        )
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        candidate = None
        if "torment" in normalized:
            candidate = "storm"
        elif "nieve" in normalized:
            candidate = "snow"
        elif "lluv" in normalized or "chubasc" in normalized:
            candidate = "rain"
        elif "niebla" in normalized or "bruma" in normalized:
            candidate = "fog"
        elif (
            "intervalos" in normalized
            or "poco nuboso" in normalized
            or "nubes altas" in normalized
        ):
            candidate = "partly_cloudy"
        elif "nuboso" in normalized or "cubierto" in normalized:
            candidate = "cloudy"
        elif "despejado" in normalized:
            candidate = "clear"
        if candidate is not None and (
            sky_condition is None
            or condition_priority[candidate]
            > condition_priority[sky_condition]
        ):
            sky_condition = candidate

    wind_options: List[Tuple[int, str]] = []
    winds = selected.get("viento", [])
    if not isinstance(winds, list):
        winds = []
    for item in winds:
        if not isinstance(item, dict):
            continue
        speed = _as_int(item.get("velocidad"))
        direction = item.get("direccion")
        if speed is not None and isinstance(direction, str) and direction:
            wind_options.append((speed, direction))

    rain_probability, rain_period = _remaining_rain_forecast(
        selected.get("probPrecipitacion"),
        local_hour,
    )
    if wind_options:
        wind_speed, wind_direction = max(wind_options, key=lambda item: item[0])
        return (
            minimum,
            maximum,
            wind_direction,
            wind_speed,
            sky_condition,
            rain_probability,
            rain_period,
        )
    return (
        minimum,
        maximum,
        None,
        None,
        sky_condition,
        rain_probability,
        rain_period,
    )


def _remaining_rain_forecast(
    items: Any,
    local_hour: int,
) -> Tuple[Optional[int], Optional[str]]:
    if not isinstance(items, list):
        return None, None
    future = []
    encompassing = []
    for item in items:
        if not isinstance(item, dict):
            continue
        probability = _as_int(item.get("value"))
        period = item.get("periodo")
        if (
            probability is None
            or not 0 <= probability <= 100
            or not isinstance(period, str)
        ):
            continue
        parts = period.split("-")
        if len(parts) != 2:
            continue
        start = _as_int(parts[0])
        end = _as_int(parts[1])
        if (
            start is None
            or end is None
            or not 0 <= start <= 23
            or not 1 <= end <= 24
            or start >= end
        ):
            continue
        candidate = (probability, start, end)
        if start >= local_hour:
            future.append(candidate)
        elif end > local_hour:
            encompassing.append(candidate)
    candidates = future or encompassing
    if not candidates:
        return None, None
    probability, start, end = max(
        candidates,
        key=lambda item: (item[0], -(item[2] - item[1])),
    )
    return probability, f"{start:02d}:00–{end:02d}:00"


def normalize_beach_forecast(
    payload: bytes,
    local_day: date,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Return today's water temperature and sea state for the named beach."""

    documents = _decode_json(payload)
    if not isinstance(documents, list) or not documents:
        raise AemetError("AEMET beach forecast was empty")
    document = documents[0]
    if not isinstance(document, dict):
        raise AemetError("AEMET beach forecast had an invalid structure")
    prediction = document.get("prediccion")
    if not isinstance(prediction, dict):
        raise AemetError("AEMET beach forecast had an invalid structure")
    days = prediction.get("dia")
    if not isinstance(days, list):
        raise AemetError("AEMET beach forecast had an invalid day list")

    expected_date = int(local_day.strftime("%Y%m%d"))
    selected = next(
        (
            item
            for item in days
            if isinstance(item, dict)
            and _as_int(item.get("fecha")) == expected_date
        ),
        None,
    )
    if selected is None:
        raise AemetError("AEMET beach forecast did not include today")
    water = selected.get("tAgua", selected.get("tagua"))
    temperature = (
        _as_int(water.get("valor1"))
        if isinstance(water, dict)
        else None
    )
    if temperature is None or not 0 <= temperature <= 40:
        temperature = None

    waves = selected.get("oleaje")
    first_state = None
    later_state = None
    if isinstance(waves, dict):
        first_state = _normalize_sea_state(waves.get("descripcion1"))
        later_state = _normalize_sea_state(waves.get("descripcion2"))
    return temperature, first_state, later_state


def _normalize_sea_state(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKD", value.strip().casefold())
    text = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    if "muy fuerte" in text or "muy grues" in text:
        return "very_rough"
    if "fuerte" in text or "grues" in text:
        return "rough"
    if "moderad" in text:
        return "moderate"
    if "debil" in text or "liger" in text:
        return "slight"
    if "calma" in text:
        return "calm"
    return None


def _compass_direction(degrees: Any) -> Optional[str]:
    try:
        value = float(degrees) % 360
    except (TypeError, ValueError):
        return None
    labels = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )
    return labels[int((value + 11.25) // 22.5) % 16]


def normalize_observation(
    payload: bytes, now: datetime
) -> Optional[Tuple[float, Optional[str], Optional[int], datetime]]:
    """Return the newest fresh Rojales observation, if one is available."""

    records = _decode_json(payload)
    if not isinstance(records, list):
        raise AemetError("AEMET observation response was not a list")

    valid: List[Tuple[datetime, Dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        observed_at = _parse_datetime(record.get("fint"))
        try:
            temperature = float(record.get("ta"))
        except (TypeError, ValueError):
            continue
        if observed_at is not None and math.isfinite(temperature):
            valid.append((observed_at, {**record, "ta": temperature}))

    if not valid:
        return None

    observed_at, record = max(valid, key=lambda item: item[0])
    age = (now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc))
    if age.total_seconds() < -300 or age.total_seconds() > OBSERVATION_MAX_AGE_SECONDS:
        return None

    wind_speed = None
    try:
        # AEMET observations express wind speed in metres per second.
        speed_mps = float(record.get("vv"))
        if math.isfinite(speed_mps) and speed_mps >= 0:
            wind_speed = round(speed_mps * 3.6)
    except (TypeError, ValueError):
        pass

    return (
        float(record["ta"]),
        _compass_direction(record.get("dv")),
        wind_speed,
        observed_at,
    )


def _local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child_text(
    element: ElementTree.Element, name: str
) -> Optional[str]:
    for child in element:
        if _local_name(child) == name and child.text:
            return child.text.strip()
    return None


def _elements(element: ElementTree.Element, name: str) -> Iterable[ElementTree.Element]:
    return (item for item in element.iter() if _local_name(item) == name)


def _cap_documents(payload: bytes) -> Iterable[bytes]:
    if payload.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                xml_items = [
                    item
                    for item in archive.infolist()
                    if item.filename.lower().endswith(".xml")
                ]
                if (
                    sum(item.file_size for item in xml_items)
                    > WARNING_UNCOMPRESSED_LIMIT_BYTES
                ):
                    raise AemetError(
                        "AEMET warning archive exceeded the size limit"
                    )
                for item in xml_items:
                    yield archive.read(item)
        except (zipfile.BadZipFile, OSError) as exc:
            raise AemetError("AEMET warning archive was invalid") from exc
    elif len(payload) >= 262 and payload[257:262] == b"ustar":
        try:
            with tarfile.open(
                fileobj=io.BytesIO(payload),
                mode="r:*",
            ) as archive:
                xml_items = [
                    item
                    for item in archive.getmembers()
                    if item.isfile()
                    and item.name.lower().endswith(".xml")
                ]
                if (
                    sum(item.size for item in xml_items)
                    > WARNING_UNCOMPRESSED_LIMIT_BYTES
                ):
                    raise AemetError(
                        "AEMET warning archive exceeded the size limit"
                    )
                for item in xml_items:
                    extracted = archive.extractfile(item)
                    if extracted is not None:
                        yield extracted.read()
        except (tarfile.TarError, OSError) as exc:
            raise AemetError("AEMET warning archive was invalid") from exc
    else:
        yield payload


def normalize_warnings(payload: bytes, now: datetime) -> Tuple[Warning, ...]:
    """Return active CAP warnings for Guardamar's official warning zone."""

    warnings: List[Warning] = []
    seen = set()
    now_utc = now.astimezone(timezone.utc)

    for document in _cap_documents(payload):
        try:
            root = ElementTree.fromstring(document)
        except ElementTree.ParseError as exc:
            raise AemetError("AEMET returned invalid CAP XML") from exc

        if (_child_text(root, "status") or "").casefold() != "actual":
            continue

        for info in _elements(root, "info"):
            language = (_child_text(info, "language") or "").casefold()
            if language and not language.startswith("es"):
                continue

            areas = [
                text
                for area in _elements(info, "area")
                if (text := _child_text(area, "areaDesc"))
            ]
            if not any(
                GUARDAMAR_WARNING_ZONE.casefold() in area.casefold()
                for area in areas
            ):
                continue

            event = _child_text(info, "event")
            severity = _child_text(info, "severity")
            if (
                not event
                or not severity
                or severity.casefold() in {"minor", "unknown"}
            ):
                continue

            starts_at = _parse_datetime(
                _child_text(info, "onset")
                or _child_text(info, "effective")
            )
            ends_at = _parse_datetime(_child_text(info, "expires"))
            if (
                starts_at
                and starts_at.astimezone(GUARDAMAR_TIMEZONE).date()
                > now.astimezone(GUARDAMAR_TIMEZONE).date()
            ):
                continue
            if ends_at and ends_at.astimezone(timezone.utc) <= now_utc:
                continue

            level = {
                "moderate": "yellow",
                "severe": "orange",
                "extreme": "red",
            }.get(severity.casefold(), severity.casefold())
            key = (event.casefold(), level, ends_at)
            if key not in seen:
                seen.add(key)
                warnings.append(
                    Warning(event=event, level=level, ends_at=ends_at)
                )

    priority = {"red": 0, "orange": 1, "yellow": 2}
    warnings.sort(key=lambda item: (priority.get(item.level, 3), item.event))
    return tuple(warnings)


async def fetch_morning_digest(
    api_key: str,
    now: datetime,
    *,
    daily_attempts: int = 2,
    daily_retry_seconds: float = 2,
) -> MorningDigest:
    """Fetch AEMET products sequentially and return one normalized model."""

    if daily_attempts < 1:
        raise ValueError("daily_attempts must be at least one")
    daily_result = None
    daily_error = None
    for attempt in range(daily_attempts):
        try:
            daily_result = await _fetch_product(
                f"prediccion/especifica/municipio/diaria/"
                f"{GUARDAMAR_MUNICIPALITY_CODE}",
                api_key,
                JSON_LIMIT_BYTES,
            )
            break
        except AemetError as exc:
            daily_error = exc
            if attempt + 1 < daily_attempts:
                await asyncio.sleep(daily_retry_seconds)
    if daily_result is None:
        raise AemetError(
            "The daily Guardamar forecast is unavailable"
        ) from daily_error

    try:
        observation_result = await _fetch_product(
            f"observacion/convencional/datos/estacion/"
            f"{ROJALES_STATION_CODE}",
            api_key,
            JSON_LIMIT_BYTES,
        )
    except AemetError:
        observation_result = None
        LOGGER.warning("Current Rojales observation is unavailable")

    try:
        warning_result = await _fetch_product(
            f"avisos_cap/ultimoelaborado/area/"
            f"{VALENCIAN_COMMUNITY_WARNING_AREA}",
            api_key,
            WARNING_LIMIT_BYTES,
        )
    except AemetError:
        warning_result = None
        LOGGER.warning("AEMET warnings are unavailable")

    try:
        beach_result = await _fetch_product(
            f"prediccion/especifica/playa/"
            f"{CENTRO_LA_ROQUETA_BEACH_CODE}",
            api_key,
            JSON_LIMIT_BYTES,
        )
    except AemetError:
        beach_result = None
        LOGGER.warning("AEMET Centro / La Roqueta forecast is unavailable")

    local_now = now.astimezone(GUARDAMAR_TIMEZONE)
    (
        minimum,
        maximum,
        forecast_direction,
        forecast_speed,
        sky_condition,
        rain_probability,
        rain_period,
    ) = normalize_daily_forecast(
        daily_result,
        local_now.date(),
        local_now.hour,
    )
    wind_direction = forecast_direction
    wind_speed = forecast_speed
    forecast_comparison = forecast_speed

    current_temperature = None
    observed_at = None
    if observation_result is not None:
        observation = normalize_observation(observation_result, now)
        if observation is not None:
            (
                current_temperature,
                observed_direction,
                observed_speed,
                observed_at,
            ) = observation
            wind_direction = observed_direction or wind_direction
            wind_speed = (
                observed_speed if observed_speed is not None else wind_speed
            )
    warnings_available = warning_result is not None
    warnings: Tuple[Warning, ...] = ()
    if warning_result is not None:
        try:
            warnings = normalize_warnings(warning_result, now)
        except AemetError:
            warnings_available = False
            LOGGER.warning("AEMET warnings could not be interpreted")

    forecast_sea_temperature = None
    forecast_sea_state = None
    forecast_later_sea_state = None
    if beach_result is not None:
        try:
            (
                forecast_sea_temperature,
                forecast_sea_state,
                forecast_later_sea_state,
            ) = normalize_beach_forecast(
                beach_result, now.astimezone(GUARDAMAR_TIMEZONE).date()
            )
        except AemetError:
            LOGGER.warning(
                "AEMET Centro / La Roqueta forecast "
                "could not be interpreted"
            )
    return MorningDigest(
        weather=Weather(
            current_temperature_c=current_temperature,
            minimum_temperature_c=minimum,
            maximum_temperature_c=maximum,
            wind_direction=wind_direction,
            wind_speed_kmh=wind_speed,
            observed_at=observed_at,
            forecast_wind_speed_kmh=forecast_comparison,
            sky_condition=sky_condition,
            rain_probability_percent=rain_probability,
            rain_period=rain_period,
        ),
        warnings=warnings,
        warnings_available=warnings_available,
        forecast_sea_temperature_c=forecast_sea_temperature,
        forecast_sea_state=forecast_sea_state,
        forecast_later_sea_state=forecast_later_sea_state,
    )
