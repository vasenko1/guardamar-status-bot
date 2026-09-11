"""Morning-only Meteosalud and CAMS enrichment for the digest.

The module deliberately returns small display-domain records.  It neither owns
operational state nor exposes hourly CAMS fields to the formatter.
"""

import asyncio
import html
import json
import logging
import math
import os
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .diagnostics import SourceDiagnostic, source_error
from .models import AirQualitySummary, HeatHealthRisk, PollenSummary

LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
GUARDAMAR_LATITUDE = 38.0909
GUARDAMAR_LONGITUDE = -0.6556
METEOSALUD_URL = (
    "https://www.sanidad.gob.es/excesoTemperaturas/meteosalud.do?"
    "idComarca=770303&metodo=cargarComarca"
)
CAMS_DATA_URL = (
    "https://raw.githubusercontent.com/vasenko1/guardamar-cams-data/"
    "main/data/latest.json"
)
CAM_VARIABLES = (
    "particulate_matter_2.5um", "particulate_matter_10um", "ozone",
    "nitrogen_dioxide", "sulphur_dioxide", "dust", "pm10_wildfires",
    "alder_pollen", "birch_pollen", "grass_pollen", "mugwort_pollen",
    "olive_pollen", "ragweed_pollen",
)
POLLEN_LABELS = {
    "alder_pollen": "ольхи", "birch_pollen": "берёзы",
    "grass_pollen": "злаковых трав", "mugwort_pollen": "полыни",
    "olive_pollen": "оливы",
}
POLLEN_HIGH = {
    "alder_pollen": 50.0, "birch_pollen": 50.0, "grass_pollen": 50.0,
    "mugwort_pollen": 50.0, "olive_pollen": 200.0,
}
ICA_BANDS = {
    "sulphur_dioxide": (100, 200, 350, 500, 750),
    "particulate_matter_2.5um": (10, 20, 25, 50, 75),
    "particulate_matter_10um": (20, 40, 50, 100, 150),
    "ozone": (50, 100, 130, 240, 380),
    "nitrogen_dioxide": (40, 90, 120, 230, 340),
}
POLLUTANT_LABELS = {
    "particulate_matter_2.5um": "PM2.5",
    "particulate_matter_10um": "PM10", "ozone": "озон (O₃)",
    "nitrogen_dioxide": "NO₂", "sulphur_dioxide": "SO₂",
}


class EnvironmentError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.safe_description = description
        self.server_status = status


def _allowed_meteosalud(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "www.sanidad.gob.es"


def _allowed_cams_data(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "raw.githubusercontent.com"
        and parsed.path
        == "/vasenko1/guardamar-cams-data/main/data/latest.json"
    )


def parse_meteosalud_level(payload: bytes, now: datetime) -> Optional[HeatHealthRisk]:
    """Read only the page's dated current level; stale pages are rejected."""
    text = html.unescape(payload.decode("utf-8", "replace"))
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    date_match = re.search(r"\b(\d{2})/(\d{2})/(\d{2,4})\b", text)
    if not date_match:
        raise EnvironmentError("Meteosalud page has no date")
    day, month, year = map(int, date_match.groups())
    if year < 100:
        year += 2000
    if datetime(year, month, day, tzinfo=GUARDAMAR_TIMEZONE).date() != now.astimezone(GUARDAMAR_TIMEZONE).date():
        return None
    levels = ((0, "ausencia de riesgo"), (1, "bajo riesgo"),
              (2, "riesgo medio"), (3, "riesgo alto"))
    current = text.casefold().split("previsión", 1)[0]
    for level, label in levels:
        if label in current:
            return HeatHealthRisk(level)
    raise EnvironmentError("Meteosalud page has no known level")


async def fetch_meteosalud(now: datetime) -> Optional[HeatHealthRisk]:
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded, METEOSALUD_URL, is_allowed_url=_allowed_meteosalud,
            limit_bytes=256_000, timeout_seconds=12,
            headers={"Accept": "text/html", "User-Agent": "GuardamarMorningDigest/0.12"},
            accepted_types=frozenset({"text/html"}),
        )
        return parse_meteosalud_level(payload, now)
    except (BoundedFetchError, EnvironmentError) as exc:
        raise EnvironmentError(
            "Meteosalud unavailable",
            code=exc.code if isinstance(exc, BoundedFetchError) else "PARSE",
            status=exc.status if isinstance(exc, BoundedFetchError) else None,
            description=(
                "страница Meteosalud временно недоступна"
                if isinstance(exc, BoundedFetchError)
                else "страница Meteosalud не прошла проверку формата"
            ),
        ) from exc


def _ica_category(pollutant: str, value: float) -> int:
    """Return 0=good through 5=extremely unfavourable, per MITECO bands."""
    for category, upper in enumerate(ICA_BANDS[pollutant]):
        if value <= upper:
            return category
    return 5


def _period(hours: Sequence[int]) -> str:
    values = sorted(set(hours))
    if len(values) >= 12:
        return "в течение дня"
    middle = sum(values) / len(values)
    if middle < 11:
        return "утром"
    if middle < 15:
        return "днём"
    if middle < 19:
        return "во второй половине дня"
    return "вечером"


def summarize_cams(
    hours: Iterable[Tuple[datetime, Dict[str, float]]], now: datetime,
) -> Tuple[Optional[AirQualitySummary], Optional[PollenSummary]]:
    """Apply MITECO windows and compact pollen policy to one nearest grid cell."""
    local_today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    series = sorted((moment.astimezone(GUARDAMAR_TIMEZONE), values) for moment, values in hours)
    categories = defaultdict(list)
    for index, (moment, values) in enumerate(series):
        if moment.date() != local_today:
            continue
        for pollutant in ICA_BANDS:
            window = 1 if pollutant in {"nitrogen_dioxide", "sulphur_dioxide"} else (8 if pollutant == "ozone" else 24)
            samples = [entry[1].get(pollutant) for entry in series[max(0, index-window+1):index+1]]
            if len(samples) == window and all(value is not None for value in samples):
                categories[pollutant].append((moment.hour, _ica_category(pollutant, sum(samples) / window)))
    worst = max((category for values in categories.values() for _, category in values), default=0)
    if worst < 3:  # Regular is intentionally quiet; only Desfavorable+ is material.
        air = None
    else:
        pollutants = tuple(key for key, values in categories.items() if max(category for _, category in values) == worst)
        bad_hours = [hour for key in pollutants for hour, category in categories[key] if category == worst]
        dust_related = any(
            values.get("dust", 0.0) >= 0.35 * values.get("particulate_matter_10um", math.inf)
            for moment, values in series if moment.date() == local_today
        ) and "particulate_matter_10um" in pollutants
        wildfire = any(
            values.get("pm10_wildfires", 0.0) >= 0.25 * values.get("particulate_matter_10um", math.inf)
            for moment, values in series if moment.date() == local_today
        )
        air = AirQualitySummary(tuple(POLLUTANT_LABELS[key] for key in pollutants), _period(bad_hours), dust_related, wildfire)
    high = []
    pollen_hours = []
    ragweed_hours = []
    for variable, threshold in POLLEN_HIGH.items():
        matching = [moment.hour for moment, values in series if moment.date() == local_today and values.get(variable, 0.0) > threshold]
        if matching:
            high.append(POLLEN_LABELS[variable])
            pollen_hours.extend(matching)
    ragweed_hours = [moment.hour for moment, values in series if moment.date() == local_today and values.get("ragweed_pollen", 0.0) >= 3.0]
    pollen = PollenSummary(tuple(high), _period(pollen_hours) if pollen_hours else None, bool(ragweed_hours), _period(ragweed_hours) if ragweed_hours else None) if high or ragweed_hours else None
    return air, pollen


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise EnvironmentError(f"CAMS {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EnvironmentError(f"CAMS {label} is invalid") from exc
    if parsed.tzinfo is None:
        raise EnvironmentError(f"CAMS {label} has no timezone")
    return parsed.astimezone(timezone.utc)


def _required_utc_hours(now: datetime) -> Tuple[datetime, ...]:
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    local_start = datetime.combine(local_day, time.min, GUARDAMAR_TIMEZONE)
    local_end = datetime.combine(
        local_day + timedelta(days=1), time.min, GUARDAMAR_TIMEZONE
    )
    start = local_start.astimezone(timezone.utc) - timedelta(hours=23)
    end = local_end.astimezone(timezone.utc)
    return tuple(
        start + timedelta(hours=offset)
        for offset in range(int((end - start).total_seconds() // 3600))
    )


def parse_cams_payload(
    payload: bytes, now: datetime
) -> Tuple[Tuple[Tuple[datetime, Dict[str, float]], ...], datetime]:
    """Validate the public producer contract and today's rolling coverage."""

    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvironmentError("CAMS data is not valid JSON") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise EnvironmentError("CAMS data has an unsupported schema")
    if (
        document.get("provider")
        != "Copernicus Atmosphere Monitoring Service (CAMS)"
        or document.get("product") != "cams-europe-air-quality-forecasts"
        or document.get("model") != "ensemble"
    ):
        raise EnvironmentError("CAMS data has invalid provenance")
    forecast_base = _parse_timestamp(
        document.get("forecast_base_utc"), "forecast base"
    )
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if forecast_base.date() not in {
        local_day,
        local_day - timedelta(days=1),
    }:
        raise EnvironmentError("CAMS forecast is stale or premature")
    units = document.get("units")
    if not isinstance(units, dict):
        raise EnvironmentError("CAMS units are missing")
    expected_units = {
        **{
            name: "µg/m3"
            for name in (
                "particulate_matter_2.5um",
                "particulate_matter_10um",
                "ozone",
                "nitrogen_dioxide",
                "sulphur_dioxide",
                "dust",
                "pm10_wildfires",
            )
        },
        **{
            name: "grains/m3"
            for name in (
                "alder_pollen",
                "birch_pollen",
                "grass_pollen",
                "mugwort_pollen",
                "olive_pollen",
                "ragweed_pollen",
            )
        },
    }
    rows = document.get("hourly")
    if not isinstance(rows, list):
        raise EnvironmentError("CAMS hourly data is missing")
    parsed_rows: Dict[datetime, Dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") not in {
            "analysis",
            "forecast",
        }:
            raise EnvironmentError("CAMS hourly row is invalid")
        timestamp = _parse_timestamp(row.get("timestamp_utc"), "timestamp")
        raw_values = row.get("values")
        if not isinstance(raw_values, dict):
            raise EnvironmentError("CAMS hourly values are invalid")
        values: Dict[str, float] = {}
        for name, raw_value in raw_values.items():
            if name not in CAM_VARIABLES or units.get(name) != expected_units[name]:
                raise EnvironmentError("CAMS variable metadata is invalid")
            if (
                not isinstance(raw_value, (int, float))
                or isinstance(raw_value, bool)
                or not math.isfinite(raw_value)
                or raw_value < 0
            ):
                raise EnvironmentError("CAMS hourly value is invalid")
            values[name] = float(raw_value)
        existing = parsed_rows.get(timestamp)
        if existing is not None and existing != values:
            raise EnvironmentError("CAMS data has conflicting timestamps")
        parsed_rows[timestamp] = values
    core = set(ICA_BANDS)
    for timestamp in _required_utc_hours(now):
        if not core.issubset(parsed_rows.get(timestamp, {})):
            raise EnvironmentError("CAMS data does not cover today's windows")
    return tuple(sorted(parsed_rows.items())), forecast_base


def _load_cams_cache(
    cache_path: Path, now: datetime
) -> Optional[Tuple[Tuple[Tuple[datetime, Dict[str, float]], ...], datetime]]:
    try:
        return parse_cams_payload(cache_path.read_bytes(), now)
    except (OSError, EnvironmentError):
        return None


def _write_cams_cache(cache_path: Path, payload: bytes) -> None:
    temporary = cache_path.with_name(f".{cache_path.name}.tmp")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(payload)
        os.chmod(temporary, 0o600)
        os.replace(temporary, cache_path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise EnvironmentError("CAMS cache could not be saved") from exc


async def fetch_cams(
    data_url: str,
    cache_path: Path,
    now: datetime,
    *,
    allow_remote: bool = True,
    diagnostics: Optional[List[SourceDiagnostic]] = None,
) -> Tuple[Optional[AirQualitySummary], Optional[PollenSummary], datetime]:
    """Use the newest valid public JSON or a covering local last-good copy."""

    cached = await asyncio.to_thread(_load_cams_cache, cache_path, now)
    remote = None
    remote_payload = None
    remote_failure = None
    if allow_remote and data_url:
        try:
            remote_payload, _, _ = await asyncio.to_thread(
                fetch_bounded,
                data_url,
                is_allowed_url=_allowed_cams_data,
                limit_bytes=128_000,
                timeout_seconds=12,
                headers={
                    "Accept": "application/json,text/plain",
                    "User-Agent": "GuardamarMorningDigest/0.13",
                },
                accepted_types=frozenset(
                    {"application/json", "text/plain", "application/octet-stream"}
                ),
            )
            remote = parse_cams_payload(remote_payload, now)
        except (BoundedFetchError, EnvironmentError) as exc:
            remote_failure = EnvironmentError(
                "Remote CAMS JSON unavailable",
                code=exc.code if isinstance(exc, BoundedFetchError) else "PAYLOAD",
                status=exc.status if isinstance(exc, BoundedFetchError) else None,
                description=(
                    "публичный прогноз CAMS временно недоступен"
                    if isinstance(exc, BoundedFetchError)
                    else "публичный прогноз CAMS не прошёл проверку формата"
                ),
            )
            LOGGER.warning("Remote CAMS JSON unavailable; trying cache: %s", exc)
    selected = cached
    if remote is not None and (
        selected is None or remote[1] >= selected[1]
    ):
        selected = remote
        assert remote_payload is not None
        try:
            await asyncio.to_thread(_write_cams_cache, cache_path, remote_payload)
        except EnvironmentError as exc:
            LOGGER.warning("CAMS cache update failed: %s", exc)
            if diagnostics is not None:
                diagnostics.append(source_error(
                    "CAMS", "CAMS", exc, stage="CACHE"
                ))
    if selected is None:
        raise EnvironmentError(
            "CAMS unavailable",
            code="UNAVAILABLE",
            description="нет корректного свежего прогноза или локального снимка",
        )
    if remote_failure is not None and diagnostics is not None:
        failure = source_error(
            "CAMS", "CAMS", remote_failure, stage="REMOTE"
        )
        diagnostics.append(SourceDiagnostic(
            failure.code,
            failure.source,
            f"{failure.description}; использован локальный снимок",
        ))
    air, pollen = summarize_cams(selected[0], now)
    return air, pollen, selected[1]
