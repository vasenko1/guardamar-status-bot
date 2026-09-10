"""Morning-only Meteosalud and CAMS enrichment for the digest.

The module deliberately returns small display-domain records.  It neither owns
operational state nor exposes hourly CAMS fields to the formatter.
"""

import asyncio
import html
import io
import json
import logging
import math
import re
import urllib.parse
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .models import AirQualitySummary, HeatHealthRisk, PollenSummary

LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
GUARDAMAR_LATITUDE = 38.0909
GUARDAMAR_LONGITUDE = -0.6556
METEOSALUD_URL = (
    "https://www.sanidad.gob.es/excesoTemperaturas/meteosalud.do?"
    "idComarca=770303&metodo=cargarComarca"
)
ADS_HOST = "ads.atmosphere.copernicus.eu"
ADS_PROCESS_URL = (
    f"https://{ADS_HOST}/api/retrieve/v1/processes/"
    "cams-europe-air-quality-forecasts/execution"
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
    pass


def _allowed_meteosalud(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "www.sanidad.gob.es"


def _allowed_ads(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and (
        parsed.hostname == ADS_HOST or (parsed.hostname or "").endswith(".ecmwf.int")
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
        raise EnvironmentError("Meteosalud unavailable") from exc


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


def _cams_request() -> dict:
    return {"inputs": {"variable": list(CAM_VARIABLES), "model": ["ensemble"], "level": ["0"], "type": ["analysis", "forecast"], "time": ["00:00"], "leadtime_hour": [str(value) for value in range(97)], "data_format": "netcdf_zip", "area": [38.15, -0.72, 38.05, -0.60]}}


async def fetch_cams(token: str, now: datetime) -> Tuple[Optional[AirQualitySummary], Optional[PollenSummary]]:
    """Make one bounded ADS retrieve request; absence of a token is optional."""
    if not token:
        return None, None
    try:
        body = json.dumps(_cams_request()).encode("utf-8")
        payload, _, _ = await asyncio.to_thread(fetch_bounded, ADS_PROCESS_URL, is_allowed_url=_allowed_ads, limit_bytes=128_000, timeout_seconds=20, headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "GuardamarMorningDigest/0.12"}, accepted_types=frozenset({"application/json"}), method="POST", data=body)
        job = json.loads(payload.decode("utf-8"))
        monitor = next((link.get("href") for link in job.get("links", []) if link.get("rel") == "monitor"), None)
        if not isinstance(monitor, str):
            raise EnvironmentError("ADS response has no monitor URL")
        for _ in range(10):
            await asyncio.sleep(3)
            payload, _, _ = await asyncio.to_thread(fetch_bounded, monitor, is_allowed_url=_allowed_ads, limit_bytes=128_000, timeout_seconds=15, headers={"PRIVATE-TOKEN": token, "Accept": "application/json", "User-Agent": "GuardamarMorningDigest/0.12"}, accepted_types=frozenset({"application/json"}))
            job = json.loads(payload.decode("utf-8"))
            asset = job.get("asset", {}).get("value", {}).get("href")
            if isinstance(asset, str):
                archive, _, _ = await asyncio.to_thread(fetch_bounded, asset, is_allowed_url=_allowed_ads, limit_bytes=8_000_000, timeout_seconds=30, headers={"Accept": "application/zip", "User-Agent": "GuardamarMorningDigest/0.12"}, accepted_types=frozenset({"application/zip", "application/octet-stream"}))
                return summarize_cams(_read_netcdf_zip(archive), now)
            if job.get("status") in {"failed", "dismissed"}:
                raise EnvironmentError("ADS job failed")
        raise EnvironmentError("ADS job did not finish in the morning budget")
    except (BoundedFetchError, EnvironmentError, UnicodeDecodeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise EnvironmentError("CAMS unavailable") from exc


def _read_netcdf_zip(payload: bytes) -> Iterable[Tuple[datetime, Dict[str, float]]]:
    """Read the tiny subset returned by ADS; netCDF4 is loaded only for CAMS."""
    try:
        from netCDF4 import Dataset  # type: ignore[import-not-found]
    except ImportError as exc:
        raise EnvironmentError("netCDF4 is required for CAMS NetCDF") from exc
    rows = defaultdict(dict)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            variable = next((item for item in CAM_VARIABLES if item in name), None)
            if variable is None:
                continue
            with archive.open(name) as source, Dataset("inmemory.nc", memory=source.read()) as document:
                data_name = next((key for key in document.variables if key not in {
                    "time", "latitude", "longitude", "lat", "lon", "level",
                    "forecast_reference_time",
                }), None)
                if data_name is None:
                    continue
                values = document.variables[data_name]
                time_key = "time" if "time" in document.variables else next(key for key in document.variables if "time" in key.casefold())
                raw_times = document.variables[time_key][:]
                units = getattr(document.variables[time_key], "units", "")
                match = re.search(r"hours since (.+)", str(units))
                if not match:
                    raise EnvironmentError("CAMS NetCDF has unsupported time units")
                origin = datetime.fromisoformat(match.group(1).replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                lat_key = "latitude" if "latitude" in document.variables else "lat"
                lon_key = "longitude" if "longitude" in document.variables else "lon"
                latitudes, longitudes = document.variables[lat_key][:], document.variables[lon_key][:]
                nearest = min(((float(latitudes[i]) - GUARDAMAR_LATITUDE) ** 2 + (float(longitudes[j]) - GUARDAMAR_LONGITUDE) ** 2, i, j) for i in range(len(latitudes)) for j in range(len(longitudes)))
                _, lat_index, lon_index = nearest
                for index, raw_time in enumerate(raw_times):
                    rows[origin + timedelta(hours=float(raw_time))][variable] = float(values[index, lat_index, lon_index])
    return tuple(rows.items())
