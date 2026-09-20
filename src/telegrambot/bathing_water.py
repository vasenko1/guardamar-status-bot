"""Official Guardamar bathing-water programme discovery.

This adapter reads only the small municipal index page. It deliberately does
not interpret PDF laboratory tables; it keeps the annually published control
window and the newest linked weekly report so the guide can stay current
without hard-coded season dates.
"""

import asyncio
import re
import urllib.parse
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Optional, Tuple

from ._transport import BoundedFetchError, fetch_bounded

BATHING_WATER_PAGE_URL = (
    "https://www.guardamardelsegura.es/"
    "programa-de-control-de-las-zonas-de-bano/"
)
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "guardamar-status-bot/1.0",
}
_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_SEASON_RE = re.compile(
    r"análisis de las aguas e inspección semanal del "
    r"(\d{1,2}) de ([a-záéíóúñ]+) al "
    r"(\d{1,2}) de ([a-záéíóúñ]+)\.\s*(\d{4})",
    re.IGNORECASE,
)
_REPORT_RE = re.compile(
    r"fecha:\s*(\d{2})\.(\d{2})\.(\d{4})\s*[-–—]\s*"
    r"(\d{2})\.(\d{2})\.(\d{4})",
    re.IGNORECASE,
)


class BathingWaterSourceError(RuntimeError):
    """Raised when the municipal bathing-water index cannot be trusted."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


class _ProgrammeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.anchors = []
        self._href: Optional[str] = None
        self._anchor_parts = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        self._href = href if isinstance(href, str) else None
        self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            return
        self.parts.append(normalized)
        if self._href is not None:
            self._anchor_parts.append(normalized)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a":
            return
        if self._href is not None:
            self.anchors.append(
                (self._href, " ".join(self._anchor_parts).strip())
            )
        self._href = None
        self._anchor_parts = []

    def visible_text(self) -> str:
        return " ".join(self.parts)


def _allowed_page_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {
            "guardamardelsegura.es",
            "www.guardamardelsegura.es",
        }
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/")
        == "/programa-de-control-de-las-zonas-de-bano"
    )


def _allowed_report_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {
            "guardamardelsegura.es",
            "www.guardamardelsegura.es",
        }
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/wp-content/uploads/")
        and parsed.path.casefold().endswith(".pdf")
    )


def _month(value: str) -> int:
    month = _MONTHS.get(value.casefold())
    if month is None:
        raise BathingWaterSourceError(
            "unknown month in bathing-water programme",
            code="SCHEMA",
        )
    return month


def _parse_programme_page(
    payload: bytes,
    *,
    expected_year: int,
    observed_at: datetime,
) -> dict:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BathingWaterSourceError(
            "bathing-water page is not UTF-8",
            code="ENCODING",
        ) from exc

    parser = _ProgrammeParser()
    parser.feed(source)
    text = parser.visible_text()

    seasons = []
    for match in _SEASON_RE.finditer(text):
        year = int(match.group(5))
        try:
            start = date(
                year,
                _month(match.group(2)),
                int(match.group(1)),
            )
            end = date(
                year,
                _month(match.group(4)),
                int(match.group(3)),
            )
        except ValueError as exc:
            raise BathingWaterSourceError(
                "invalid bathing-water programme dates",
                code="SCHEMA",
            ) from exc
        if start > end:
            raise BathingWaterSourceError(
                "reversed bathing-water programme dates",
                code="SCHEMA",
            )
        seasons.append((year, start, end))

    matches = [item for item in seasons if item[0] == expected_year]
    if len(matches) != 1:
        raise BathingWaterSourceError(
            "current-year bathing-water programme is missing or ambiguous",
            code="YEAR",
        )
    _, season_start, season_end = matches[0]

    reports: list[Tuple[date, date, str]] = []
    for href, label in parser.anchors:
        match = _REPORT_RE.search(label)
        if match is None:
            continue
        try:
            start = date(
                int(match.group(3)),
                int(match.group(2)),
                int(match.group(1)),
            )
            end = date(
                int(match.group(6)),
                int(match.group(5)),
                int(match.group(4)),
            )
        except ValueError:
            continue
        if start.year != expected_year or end.year != expected_year or start > end:
            continue
        url = urllib.parse.urljoin(BATHING_WATER_PAGE_URL, href)
        if not _allowed_report_url(url):
            continue
        reports.append((start, end, url))

    latest = max(reports, key=lambda item: (item[1], item[0])) if reports else None
    return {
        "observed_at": observed_at.isoformat(),
        "season_year": expected_year,
        "season_start": season_start.isoformat(),
        "season_end": season_end.isoformat(),
        "latest_report_start": latest[0].isoformat() if latest else None,
        "latest_report_end": latest[1].isoformat() if latest else None,
        "latest_report_url": latest[2] if latest else None,
    }


def valid_bathing_water_snapshot(value) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        year = value["season_year"]
        start = date.fromisoformat(value["season_start"])
        end = date.fromisoformat(value["season_end"])
    except (KeyError, TypeError, ValueError):
        return False
    if (
        observed.tzinfo is None
        or observed.utcoffset() is None
        or not isinstance(year, int)
        or isinstance(year, bool)
        or not 2000 <= year <= 2100
        or start.year != year
        or end.year != year
        or start > end
    ):
        return False

    report_values = (
        value.get("latest_report_start"),
        value.get("latest_report_end"),
        value.get("latest_report_url"),
    )
    if report_values == (None, None, None):
        return True
    if any(item is None for item in report_values):
        return False
    try:
        report_start = date.fromisoformat(report_values[0])
        report_end = date.fromisoformat(report_values[1])
    except (TypeError, ValueError):
        return False
    return (
        report_start.year == year
        and report_end.year == year
        and report_start <= report_end
        and isinstance(report_values[2], str)
        and _allowed_report_url(report_values[2])
    )


async def fetch_bathing_water_snapshot(now: datetime) -> dict:
    """Fetch the current year's municipal programme and newest report link."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("bathing-water observation time must be timezone-aware")
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            BATHING_WATER_PAGE_URL,
            is_allowed_url=_allowed_page_url,
            limit_bytes=512 * 1024,
            timeout_seconds=15.0,
            headers=_REQUEST_HEADERS,
            accepted_types=_HTML_TYPES,
        )
    except BoundedFetchError as exc:
        raise BathingWaterSourceError(
            "bathing-water programme request failed",
            code=f"HTTP-{exc.code}",
        ) from exc
    snapshot = _parse_programme_page(
        payload,
        expected_year=now.year,
        observed_at=now,
    )
    if not valid_bathing_water_snapshot(snapshot):
        raise BathingWaterSourceError(
            "bathing-water programme snapshot is invalid",
            code="SCHEMA",
        )
    return snapshot
