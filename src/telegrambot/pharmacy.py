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
CATALOG_WINDOW_DAYS = 45
CATALOG_VERSION = 1
MUNICIPALITY = "guardamar del segura"
_EXCEL_EPOCH = date(1899, 12, 30)
_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_HOURS_PATTERN = re.compile(
    r"^de\s+(\d{1,2}:\d{2})\s+a\s+(\d{1,2}:\d{2})$", re.IGNORECASE
)


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


def _display_hours(raw: str) -> Optional[str]:
    match = _HOURS_PATTERN.match(" ".join(raw.split()))
    if match is None:
        return None
    start, end = match.group(1), match.group(2)
    if start == end:
        return f"круглосуточно (с {start})"
    return f"{start}–{end}"


def normalize_rota(payload: bytes, window_start: date) -> Tuple[dict, ...]:
    """Extract the bounded Guardamar window from one official workbook."""

    window_end = window_start + timedelta(days=CATALOG_WINDOW_DAYS)
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            sheet = ElementTree.fromstring(
                archive.read("xl/worksheets/sheet.xml")
            )
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
        serial, _, _, _, _, name, address, municipality, hours = cells[:9]
        if municipality.strip().casefold() != MUNICIPALITY:
            continue
        if not serial.isdigit():
            continue
        duty_date = _EXCEL_EPOCH + timedelta(days=int(serial))
        if not window_start <= duty_date <= window_end:
            continue
        display_hours = _display_hours(hours)
        if not name.strip() or not address.strip() or display_hours is None:
            continue
        records.append({
            "date": duty_date.isoformat(),
            "name": _title_case(name),
            "address": _title_case(address).rstrip(" ,"),
            "hours": display_hours,
            "all_day": display_hours.startswith("круглосуточно"),
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
            ),
        ) from exc
    records = normalize_rota(payload, local_day)
    if not records:
        raise PharmacyError(
            "Pharmacy rota contained no Guardamar rows in the window",
            code="NO-ROWS",
            description="в официальном файле нет дежурств Гуардамара",
        )
    await asyncio.to_thread(_write_catalog, state_path, records, now)
    return len(records)


async def duty_pharmacies_on(
    now: datetime,
    state_path: Path,
) -> Tuple[PharmacyDuty, ...]:
    """Return today's duty rows from the local catalog, 24-hour duty first."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date().isoformat()
    records = await asyncio.to_thread(_load_catalog, state_path)
    todays: List[PharmacyDuty] = []
    seen = set()
    for record in sorted(
        (record for record in records if record["date"] == local_day),
        key=lambda record: (not record.get("all_day", False), record["name"]),
    ):
        key = (record["name"], record["hours"])
        if key in seen:
            continue
        seen.add(key)
        todays.append(PharmacyDuty(
            name=record["name"],
            address=record["address"],
            hours=record["hours"],
        ))
    return tuple(todays[:2])
