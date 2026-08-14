"""On-call pharmacy rota from the official Alicante pharmacists' college.

The annual XLSX linked from cofalicante.com is the legally authoritative
rota. A pre-morning sync normalizes only the bounded Guardamar window into
one small atomic catalog; the 07:30 run reads that file and never fetches.
"""

import asyncio
import json
import os
import re
import tempfile
import urllib.parse
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .models import PharmacyDuty

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
ALLOWED_HOSTS = {"cofalicante.com", "www.cofalicante.com"}
ROTA_URL_TEMPLATE = (
    "https://www.cofalicante.com/ficheros/farmaciasguardia/"
    "guardias{year}.xlsx"
)
REQUEST_TIMEOUT_SECONDS = 30
WORKBOOK_LIMIT_BYTES = 4_000_000
# The 2026 provincial sheet expands to roughly 22 MB; this bound leaves room
# for legitimate growth while refusing a decompression bomb inside the cap.
SHEET_UNCOMPRESSED_LIMIT_BYTES = 48_000_000
# The college serves the workbook with a misspelled octet-stream type; the
# standard spellings are accepted too in case the server is ever corrected.
ACCEPTED_CONTENT_TYPES = frozenset({
    "application/octetstream",
    "application/octet-stream",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})
CATALOG_WINDOW_DAYS = 45
CATALOG_VERSION = 1
# Guardamar and San Fulgencio share the official pharmacy service zone.  The
# duty must therefore be selected by the published zone, not by the pharmacy's
# postal municipality; reinforcement rows in Guardamar can otherwise hide the
# pharmacy that covers the full night.
SERVICE_ZONE = "61"
_EXCEL_EPOCH = date(1899, 12, 30)
_SHEET_ENTRY = "xl/worksheets/sheet.xml"
_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_HOURS_PATTERN = re.compile(
    r"^de\s+(\d{1,2}:\d{2})\s+a\s+(\d{1,2}:\d{2})$", re.IGNORECASE
)
_NORMALIZED_HOURS_PATTERN = re.compile(
    r"^(\d{1,2}:\d{2})[–-](\d{1,2}:\d{2})$"
)
_LEGACY_ALL_DAY_PATTERN = re.compile(
    r"^круглосуточно\s*\(с\s*(\d{1,2}:\d{2})\)$", re.IGNORECASE
)
_COMMUNITY_PROPERTY_SUFFIX = re.compile(
    r"\s*,?\s+C\.?\s*B\.?\s*$", re.IGNORECASE
)
_STREET_NUMBER_MARKER = re.compile(r"\bN[º°]\s*", re.IGNORECASE)


class PharmacyError(RuntimeError):
    """An operator-safe pharmacy-rota failure."""

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


def _is_college_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


def _cell_value(cell) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(
            fragment.text or ""
            for fragment in cell.iter(f"{_SHEET_NS}t")
        ).strip()
    value = cell.find(f"{_SHEET_NS}v")
    return (value.text or "").strip() if value is not None else ""


def _title_case(value: str) -> str:
    lowered = " ".join(value.split()).title()
    for particle in (" De ", " Del ", " La ", " El ", " Y "):
        lowered = lowered.replace(particle, particle.casefold())
    return lowered


def _padded(value: str) -> str:
    """Render the published time as HH:MM so rows align in the digest."""

    hour, minute = value.split(":")
    hour_value, minute_value = int(hour), int(minute)
    if not 0 <= hour_value <= 23 or not 0 <= minute_value <= 59:
        raise ValueError("Invalid pharmacy duty clock")
    return f"{hour_value:02d}:{minute_value:02d}"


def _public_name(value: str) -> str:
    """Hide the registry-only Comunidad de Bienes suffix from readers."""

    return _COMMUNITY_PROPERTY_SUFFIX.sub("", value).rstrip(" ,")


def _public_address(value: str) -> str:
    """Use a plain street number that Google Maps resolves reliably."""

    return _STREET_NUMBER_MARKER.sub("", value)


def _normalized_hours(raw: str) -> Optional[Tuple[str, str]]:
    match = _HOURS_PATTERN.match(" ".join(raw.split()))
    if match is None:
        return None
    try:
        start, end = _padded(match.group(1)), _padded(match.group(2))
    except ValueError:
        return None
    return start, end


_MONTHS_GENITIVE = (
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _day_label(value: date) -> str:
    return f"{value.day} {_MONTHS_GENITIVE[value.month]}"


def _duty_hours_text(duty_date: date, start: str, end: str) -> str:
    """Describe every accepted shift without implying pharmacy closure."""

    if start == end:
        next_day = duty_date + timedelta(days=1)
        return (
            f"Круглосуточное дежурство с {start} {_day_label(duty_date)} "
            f"до {end} {_day_label(next_day)}"
        )
    if end <= start:
        next_day = duty_date + timedelta(days=1)
        return (
            f"Дежурит с {start} {_day_label(duty_date)} "
            f"до {end} {_day_label(next_day)}"
        )
    return f"Дежурит с {start} до {end}"


def _record_hours(record: dict, duty_date: date) -> str:
    """Render new structured records and catalogs made by older releases."""

    start = record.get("start_time")
    end = record.get("end_time")
    if isinstance(start, str) and isinstance(end, str):
        try:
            return _duty_hours_text(
                duty_date, _padded(start), _padded(end)
            )
        except ValueError:
            pass

    legacy = record.get("hours", "")
    match = _NORMALIZED_HOURS_PATTERN.match(legacy)
    if match is not None:
        try:
            return _duty_hours_text(
                duty_date, _padded(match.group(1)), _padded(match.group(2))
            )
        except ValueError:
            return legacy
    match = _LEGACY_ALL_DAY_PATTERN.match(legacy)
    if match is not None:
        try:
            start = _padded(match.group(1))
            return _duty_hours_text(duty_date, start, start)
        except ValueError:
            return legacy
    return legacy


def normalize_rota(payload: bytes, window_start: date) -> Tuple[dict, ...]:
    """Extract the bounded Guardamar window from one official workbook."""

    window_end = window_start + timedelta(days=CATALOG_WINDOW_DAYS)
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            # The download cap bounds only the compressed archive, so the
            # declared uncompressed size is checked before any extraction.
            if (
                archive.getinfo(_SHEET_ENTRY).file_size
                > SHEET_UNCOMPRESSED_LIMIT_BYTES
            ):
                raise PharmacyError(
                    "Pharmacy rota sheet exceeds the uncompressed limit",
                    code="TOO-LARGE",
                    description="официальный файл дежурств слишком большой",
                )
            sheet = ElementTree.fromstring(archive.read(_SHEET_ENTRY))
    except PharmacyError:
        raise
    except (
        zipfile.BadZipFile,
        KeyError,
        ElementTree.ParseError,
        ValueError,
    ) as exc:
        raise PharmacyError(
            "Pharmacy rota workbook is unreadable",
            code="INVALID-WORKBOOK",
            description="официальный файл дежурств не читается",
        ) from exc

    records = []
    for row in sheet.iter(f"{_SHEET_NS}row"):
        cells = [_cell_value(cell) for cell in row.iter(f"{_SHEET_NS}c")]
        if len(cells) < 9:
            continue
        serial, zone, _, _, _, name, address, municipality, hours = cells[:9]
        if zone.strip() != SERVICE_ZONE:
            continue
        if not serial.isdigit():
            continue
        duty_date = _EXCEL_EPOCH + timedelta(days=int(serial))
        if not window_start <= duty_date <= window_end:
            continue
        normalized_hours = _normalized_hours(hours)
        if (
            not name.strip()
            or not address.strip()
            or not municipality.strip()
            or normalized_hours is None
        ):
            continue
        start_time, end_time = normalized_hours
        records.append({
            "date": duty_date.isoformat(),
            "name": _public_name(_title_case(name)),
            "address": _public_address(_title_case(address)).rstrip(" ,"),
            "municipality": _title_case(municipality),
            "start_time": start_time,
            "end_time": end_time,
            "hours": f"{start_time}–{end_time}",
            "all_day": start_time == end_time,
        })
    return tuple(records)


def _write_catalog(path: Path, records: Tuple[dict, ...], now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CATALOG_VERSION,
        "fetched_at": now.isoformat(),
        "records": list(records),
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
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


def _load_catalog(path: Path) -> Tuple[dict, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if (
        not isinstance(data, dict)
        or data.get("version") != CATALOG_VERSION
        or not isinstance(data.get("records"), list)
    ):
        return ()
    return tuple(
        record
        for record in data["records"]
        if isinstance(record, dict)
        and isinstance(record.get("date"), str)
        and isinstance(record.get("name"), str)
        and isinstance(record.get("address"), str)
        and isinstance(record.get("hours"), str)
    )


async def refresh_pharmacy_catalog(
    now: datetime,
    state_path: Path,
) -> int:
    """Fetch this year's official rota once and save the bounded window."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    url = ROTA_URL_TEMPLATE.format(year=local_day.year)
    try:
        payload, _, _ = await asyncio.to_thread(
            lambda: fetch_bounded(
                url,
                is_allowed_url=_is_college_url,
                accepted_types=ACCEPTED_CONTENT_TYPES,
                limit_bytes=WORKBOOK_LIMIT_BYTES,
                timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "Accept": (
                        "application/vnd.openxmlformats-officedocument"
                        ".spreadsheetml.sheet, application/octet-stream"
                    ),
                    "User-Agent": "GuardamarMorningDigest/0.12",
                },
            )
        )
    except BoundedFetchError as exc:
        raise PharmacyError(
            f"Pharmacy rota request failed: {exc.code}",
            code=exc.code,
            status=exc.status,
            description=(
                f"сервер вернул HTTP {exc.status}"
                if exc.status is not None
                else "официальный файл дежурств недоступен"
                if exc.code != "CONTENT-TYPE"
                else "сервер вернул неожиданный формат файла дежурств"
            ),
        ) from exc
    records = normalize_rota(payload, local_day)
    if not records:
        raise PharmacyError(
            "Pharmacy rota contained no service-zone rows in the window",
            code="NO-ROWS",
            description="в официальном файле нет дежурств зоны Гуардамара",
        )
    await asyncio.to_thread(_write_catalog, state_path, records, now)
    return len(records)


async def duty_pharmacies_on(
    now: datetime,
    state_path: Path,
) -> Tuple[PharmacyDuty, ...]:
    """Return today's duty rows from the local catalog, 24-hour duty first."""

    duty_date = now.astimezone(GUARDAMAR_TIMEZONE).date()
    local_day = duty_date.isoformat()
    records = await asyncio.to_thread(_load_catalog, state_path)
    todays: List[PharmacyDuty] = []
    seen = set()
    for record in sorted(
        (record for record in records if record["date"] == local_day),
        key=lambda record: (not record.get("all_day", False), record["name"]),
    ):
        municipality = record.get("municipality", "Guardamar del Segura")
        hours = _record_hours(record, duty_date)
        key = (record["name"], municipality, hours)
        if key in seen:
            continue
        seen.add(key)
        todays.append(PharmacyDuty(
            # Clean again so catalogs created by an older deployed version
            # become user-friendly immediately, before the next weekly sync.
            name=_public_name(record["name"]),
            address=_public_address(record["address"]),
            hours=hours,
            municipality=municipality,
        ))
    return tuple(todays[:2])
