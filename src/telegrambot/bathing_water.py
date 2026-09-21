"""Official Guardamar bathing-water programme and weekly quality reports.

The adapter discovers the current municipal control programme from its small
index page and, only when a new report period appears, parses the linked
text-readable PDF. It accepts the reviewed seven-beach table and the official
EXCELENTE / BUENA / SUFICIENTE / INSUFICIENTE labels; it never derives a
quality class from microbiological values itself.
"""

import asyncio
import re
import subprocess
import unicodedata
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
_PDF_TYPES = frozenset({"application/pdf"})
_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "guardamar-status-bot/1.0",
}
_PDF_REQUEST_HEADERS = {
    "Accept": "application/pdf",
    "User-Agent": "guardamar-status-bot/1.0",
}
_PDF_LIMIT_BYTES = 4 * 1024 * 1024
_PDF_TEXT_LIMIT_BYTES = 256 * 1024
_PDF_PARSE_TIMEOUT_SECONDS = 8.0
_RATINGS = {
    "EXCELENTE": "excellent",
    "EXCELLENT": "excellent",
    "BUENA": "good",
    "BONA": "good",
    "SUFICIENTE": "sufficient",
    "SUFICIENT": "sufficient",
    "INSUFICIENTE": "insufficient",
    "INSUFICIENT": "insufficient",
}
_BEACH_ROWS = (
    (("PLAYA DE TUSALES", "PLATJA DELS TOSSALS"), "Tusales"),
    (("PLAYA DE VIVERS", "PLATJA DELS VIVERS"), "Vivers"),
    (("PLAYA DE BABILONIA", "PLATJA DE BABILONIA"), "Babilonia"),
    (("PLAYA CENTRO", "PLATJA CENTRE"), "Centro"),
    (("PLAYA DE LA ROQUETA", "PLATJA DE LA ROQUETA"), "La Roqueta"),
    (("PLAYA DEL MONCAYO", "PLATJA DEL MONCAIO"), "Moncayo"),
    (
        ("PLAYA DE ORTIGUES", "PLATJA DE LES ORTIGUES-CAMPO"),
        "Ortigues",
    ),
)
_REPORT_PERIOD_RE = re.compile(
    r"(?:Fecha|Data):\s*(\d{2})\.(\d{2})\.(\d{4})\s*[-–—]\s*"
    r"(\d{2})\.(\d{2})\.(\d{4})",
    re.IGNORECASE,
)
_SAMPLE_DATE_RE = re.compile(
    r"(?:Fecha\s+desc\.\s*punto1|Data\s+desc\.\s*punt1):\s*"
    r"(\d{2}/\d{2}/\d{2})",
    re.IGNORECASE,
)
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


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.replace("·", "").upper().split())


def _fold_layout(value: str) -> str:
    """Remove accents while preserving column positions from pdftotext -layout."""

    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    ).replace("·", "").upper()


def _extract_report_text(payload: bytes) -> str:
    if not payload.startswith(b"%PDF-") or len(payload) > _PDF_LIMIT_BYTES:
        raise BathingWaterSourceError(
            "bathing-water report is not a bounded PDF",
            code="REPORT-PDF",
        )
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_PDF_PARSE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BathingWaterSourceError(
            "pdftotext is unavailable",
            code="REPORT-PDF-TO-TEXT",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BathingWaterSourceError(
            "bathing-water PDF parsing timed out",
            code="REPORT-PDF-TIMEOUT",
        ) from exc
    except OSError as exc:
        raise BathingWaterSourceError(
            "bathing-water PDF parsing failed",
            code="REPORT-PDF-TO-TEXT",
        ) from exc
    if completed.returncode != 0:
        raise BathingWaterSourceError(
            "pdftotext rejected bathing-water PDF",
            code="REPORT-PDF-PARSE",
        )
    if (
        not completed.stdout
        or len(completed.stdout) > _PDF_TEXT_LIMIT_BYTES
    ):
        raise BathingWaterSourceError(
            "bathing-water PDF text is empty or too large",
            code="REPORT-PDF-PARSE",
        )
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BathingWaterSourceError(
            "bathing-water PDF text encoding is invalid",
            code="REPORT-PDF-PARSE",
        ) from exc


def _rating(value: str) -> str:
    normalized = _fold(value)
    matches = [
        canonical
        for label, canonical in _RATINGS.items()
        if re.search(rf"\b{label}\b", normalized)
    ]
    if len(matches) != 1:
        raise BathingWaterSourceError(
            "bathing-water rating is missing or ambiguous",
            code="REPORT-SCHEMA",
        )
    return matches[0]


def _parse_report_text(
    text: str,
    *,
    report_url: str,
    report_start: date,
    report_end: date,
    observed_at: datetime,
) -> dict:
    """Parse the reviewed Spanish/Valencian first-page weekly beach table."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("bathing-water report time must be timezone-aware")
    if not _allowed_report_url(report_url):
        raise BathingWaterSourceError(
            "bathing-water report URL is outside policy",
            code="REPORT-URL",
        )
    if report_start > report_end or report_start.year != report_end.year:
        raise BathingWaterSourceError(
            "bathing-water report period is invalid",
            code="REPORT-PERIOD",
        )

    first_page = text.split("\f", 1)[0]
    folded_page = _fold(first_page)
    valid_heading = (
        "PROGRAMA DE CONTROL DE LAS ZONAS DE BANO" in folded_page
        or "PROGRAMA DE CONTROL DE LES ZONES DE BANY" in folded_page
    )
    if not valid_heading or "GUARDAMAR DEL SEGURA" not in folded_page:
        raise BathingWaterSourceError(
            "bathing-water report heading is invalid",
            code="REPORT-SCHEMA",
        )

    period = _REPORT_PERIOD_RE.search(first_page)
    if period is None:
        raise BathingWaterSourceError(
            "bathing-water report period is missing",
            code="REPORT-PERIOD",
        )
    try:
        embedded_start = date(
            int(period.group(3)),
            int(period.group(2)),
            int(period.group(1)),
        )
        embedded_end = date(
            int(period.group(6)),
            int(period.group(5)),
            int(period.group(4)),
        )
    except ValueError as exc:
        raise BathingWaterSourceError(
            "bathing-water report period is invalid",
            code="REPORT-PERIOD",
        ) from exc
    if embedded_start != report_start or embedded_end != report_end:
        raise BathingWaterSourceError(
            "bathing-water report period does not match index",
            code="REPORT-PERIOD",
        )

    sample_dates = []
    for raw in _SAMPLE_DATE_RE.findall(first_page):
        try:
            sampled = datetime.strptime(raw, "%d/%m/%y").date()
        except ValueError as exc:
            raise BathingWaterSourceError(
                "bathing-water sample date is invalid",
                code="REPORT-SAMPLE-DATE",
            ) from exc
        if not report_start <= sampled <= report_end:
            raise BathingWaterSourceError(
                "bathing-water sample date is outside report period",
                code="REPORT-SAMPLE-DATE",
            )
        sample_dates.append(sampled)
    sample_dates = sorted(set(sample_dates))
    if not sample_dates:
        raise BathingWaterSourceError(
            "bathing-water sample dates are missing",
            code="REPORT-SAMPLE-DATE",
        )

    lines = first_page.splitlines()
    header_index = None
    positions = None
    header_variants = (
        ("ANALISIS AGUA", "ASPECTO AGUA", "ASPECTO ARENA"),
        ("ANALISI AIGUA", "ASPECTE AIGUA", "ASPECTE ARENA"),
    )
    for index, line in enumerate(lines):
        folded = _fold_layout(line)
        for labels in header_variants:
            if not all(label in folded for label in labels):
                continue
            analytics_marker = "ENTEROC"
            if analytics_marker not in folded:
                continue
            candidate = (
                folded.index(labels[0]),
                folded.index(labels[1]),
                folded.index(labels[2]),
                folded.index(analytics_marker),
            )
            if candidate == tuple(sorted(candidate)) and len(set(candidate)) == 4:
                header_index = index
                positions = candidate
                break
        if header_index is not None:
            break
    if header_index is None or positions is None:
        raise BathingWaterSourceError(
            "bathing-water report table header is missing",
            code="REPORT-SCHEMA",
        )

    water_start, water_appearance_start, sand_start, analytics_start = positions
    table_beach_lines = [
        line
        for line in lines[header_index + 1:]
        if _fold(line).startswith(("PLAYA ", "PLATJA "))
    ]
    if len(table_beach_lines) != len(_BEACH_ROWS):
        raise BathingWaterSourceError(
            "bathing-water report beach topology changed",
            code="REPORT-SCHEMA",
        )

    def matching_rows(line: str):
        folded = _fold(line)
        return [
            (aliases, public_name)
            for aliases, public_name in _BEACH_ROWS
            if any(alias in folded for alias in aliases)
        ]

    for line in table_beach_lines:
        if len(matching_rows(line)) != 1:
            raise BathingWaterSourceError(
                "bathing-water report contains an unknown beach row",
                code="REPORT-SCHEMA",
            )

    rows = []
    for aliases, public_name in _BEACH_ROWS:
        matches = []
        for line in lines[header_index + 1:]:
            folded = _fold(line)
            if any(alias in folded for alias in aliases):
                matches.append(line)
        if len(matches) != 1:
            raise BathingWaterSourceError(
                f"bathing-water row {public_name} is missing or ambiguous",
                code="REPORT-SCHEMA",
            )
        line = matches[0]
        if len(line) < analytics_start:
            line = line.ljust(analytics_start)
        rows.append({
            "name": public_name,
            "water_analysis": _rating(
                line[water_start:water_appearance_start]
            ),
            "water_appearance": _rating(
                line[water_appearance_start:sand_start]
            ),
            "sand_appearance": _rating(
                line[sand_start:analytics_start]
            ),
        })

    snapshot = {
        "observed_at": observed_at.isoformat(),
        "report_start": report_start.isoformat(),
        "report_end": report_end.isoformat(),
        "report_url": report_url,
        "sample_dates": [item.isoformat() for item in sample_dates],
        "beaches": rows,
    }
    if not valid_bathing_water_report_snapshot(snapshot):
        raise BathingWaterSourceError(
            "bathing-water report snapshot is invalid",
            code="REPORT-SCHEMA",
        )
    return snapshot


def valid_bathing_water_report_snapshot(value) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        observed_at = datetime.fromisoformat(value["observed_at"])
        report_start = date.fromisoformat(value["report_start"])
        report_end = date.fromisoformat(value["report_end"])
        report_url = value["report_url"]
        sample_dates_raw = value["sample_dates"]
        beaches = value["beaches"]
    except (KeyError, TypeError, ValueError):
        return False
    if (
        observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or report_start > report_end
        or report_start.year != report_end.year
        or not isinstance(report_url, str)
        or not _allowed_report_url(report_url)
        or not isinstance(sample_dates_raw, list)
        or not sample_dates_raw
        or not isinstance(beaches, list)
        or len(beaches) != len(_BEACH_ROWS)
    ):
        return False

    try:
        sample_dates = [date.fromisoformat(item) for item in sample_dates_raw]
    except (TypeError, ValueError):
        return False
    if (
        sample_dates != sorted(set(sample_dates))
        or any(not report_start <= item <= report_end for item in sample_dates)
    ):
        return False

    expected_names = [public_name for _, public_name in _BEACH_ROWS]
    actual_names = []
    allowed = set(_RATINGS.values())
    for beach in beaches:
        if not isinstance(beach, dict) or set(beach) != {
            "name",
            "water_analysis",
            "water_appearance",
            "sand_appearance",
        }:
            return False
        if (
            not isinstance(beach["name"], str)
            or beach["water_analysis"] not in allowed
            or beach["water_appearance"] not in allowed
            or beach["sand_appearance"] not in allowed
        ):
            return False
        actual_names.append(beach["name"])
    return actual_names == expected_names


def bathing_water_report_fingerprint(value: dict) -> tuple:
    """Return semantic weekly report facts, excluding URL/observation time."""

    return (
        value["report_start"],
        value["report_end"],
        tuple(value["sample_dates"]),
        tuple(
            (
                beach["name"],
                beach["water_analysis"],
                beach["water_appearance"],
                beach["sand_appearance"],
            )
            for beach in value["beaches"]
        ),
    )


async def fetch_bathing_water_report(
    programme_snapshot: dict,
    now: datetime,
) -> dict:
    """Fetch and parse the newest weekly report discovered by the index."""

    if not valid_bathing_water_snapshot(programme_snapshot):
        raise BathingWaterSourceError(
            "bathing-water programme snapshot is invalid",
            code="REPORT-PROGRAMME",
        )
    report_url = programme_snapshot.get("latest_report_url")
    report_start_raw = programme_snapshot.get("latest_report_start")
    report_end_raw = programme_snapshot.get("latest_report_end")
    if not all((report_url, report_start_raw, report_end_raw)):
        raise BathingWaterSourceError(
            "bathing-water programme has no weekly report",
            code="REPORT-MISSING",
        )
    try:
        report_start = date.fromisoformat(report_start_raw)
        report_end = date.fromisoformat(report_end_raw)
    except (TypeError, ValueError) as exc:
        raise BathingWaterSourceError(
            "bathing-water programme report period is invalid",
            code="REPORT-PERIOD",
        ) from exc
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            report_url,
            is_allowed_url=_allowed_report_url,
            limit_bytes=_PDF_LIMIT_BYTES,
            timeout_seconds=15.0,
            headers=_PDF_REQUEST_HEADERS,
            accepted_types=_PDF_TYPES,
        )
    except BoundedFetchError as exc:
        raise BathingWaterSourceError(
            "bathing-water report request failed",
            code=f"REPORT-{exc.code}",
        ) from exc
    text = await asyncio.to_thread(_extract_report_text, payload)
    return _parse_report_text(
        text,
        report_url=report_url,
        report_start=report_start,
        report_end=report_end,
        observed_at=now,
    )
