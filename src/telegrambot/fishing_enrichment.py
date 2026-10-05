"""Bounded FEPyC/FPCV enrichment for Guardamar fishing events."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import unicodedata
import urllib.parse
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded


GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

FPCV_INDEX_URL = (
    "https://federacionpescacv.com/convocatorias-clasificaciones-2026/"
)
FEPYC_26MC26_URL = "https://www.fepyc.es/26MC26"

DEFAULT_FEPYC_AUTHORITY_STATE_PATH = "state/fepyc_fishing_authority.json"
DEFAULT_FPCV_DETAILS_STATE_PATH = "state/pesca_cv_details.json"

_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_PDF_TYPES = frozenset({"application/pdf"})
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/pdf",
    "User-Agent": "guardamar-status-bot/1.0",
}

_FEPYC_HTML_LIMIT_BYTES = 128 * 1024
_FPCV_INDEX_LIMIT_BYTES = 512 * 1024
_FPCV_PDF_LIMIT_BYTES = 1024 * 1024
_FPCV_PDF_TEXT_LIMIT_BYTES = 64 * 1024
_REQUEST_TIMEOUT_SECONDS = 15.0
_PDF_PARSE_TIMEOUT_SECONDS = 10.0
_MAX_FEPYC_AUTHORITIES = 4
_MAX_FPCV_DETAILS = 8
_STATE_VERSION = 1

_FEPYC_SPECS = (
    {
        "source_id": "26MC26",
        "url": FEPYC_26MC26_URL,
        "match_title": "Mar Costa Dúos",
    },
)

_SPANISH_MONTHS = {
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


class FishingEnrichmentError(RuntimeError):
    """An authority/details observation that is unsafe to use."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", " ".join(value.split())).casefold()
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _allowed_exact_url(url: str, *, hosts: set[str], path: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in hosts
        and port in {None, 443}
        and parsed.path == path
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


def _allowed_fepyc_url(url: str) -> bool:
    return _allowed_exact_url(
        url,
        hosts={"fepyc.es", "www.fepyc.es"},
        path="/26MC26",
    )


def _allowed_fpcv_index_url(url: str) -> bool:
    return _allowed_exact_url(
        url,
        hosts={"federacionpescacv.com", "www.federacionpescacv.com"},
        path="/convocatorias-clasificaciones-2026/",
    )


def _allowed_fpcv_pdf_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {
            "federacionpescacv.com",
            "www.federacionpescacv.com",
        }
        and port in {None, 443}
        and parsed.path.startswith("/wp-content/uploads/2026/")
        and parsed.path.casefold().endswith(".pdf")
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style"}:
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


class _LinkedTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._row: Optional[list[dict[str, Any]]] = None
        self._cell_parts: Optional[list[str]] = None
        self._cell_links: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.casefold()
        if lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._cell_links = []
        elif lowered == "a" and self._cell_links is not None:
            for name, value in attrs:
                if name.casefold() == "href" and value:
                    self._cell_links.append(value)

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"td", "th"} and self._cell_parts is not None:
            assert self._row is not None
            self._row.append(
                {
                    "text": " ".join("".join(self._cell_parts).split()),
                    "links": tuple(self._cell_links or ()),
                }
            )
            self._cell_parts = None
            self._cell_links = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell_parts = None
            self._cell_links = None


def _parse_spanish_month(value: str) -> int:
    try:
        return _SPANISH_MONTHS[_fold(value)]
    except KeyError as exc:
        raise FishingEnrichmentError(
            "unsupported Spanish month", code="SCHEMA"
        ) from exc


def _parse_spanish_date(day: str, month: str, year: str) -> date:
    try:
        return date(int(year), _parse_spanish_month(month), int(day))
    except ValueError as exc:
        raise FishingEnrichmentError("invalid Spanish date", code="SCHEMA") from exc


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_json(path: Path, validator, label: str) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FishingEnrichmentError(
            f"{label} state is unreadable", code="STATE"
        ) from exc
    if not validator(value):
        raise FishingEnrichmentError(
            f"{label} state is invalid", code="STATE"
        )
    return value


def _authority_record_valid(record: Any) -> bool:
    required = {
        "source_id",
        "match_title",
        "specialty",
        "category",
        "competition_type",
        "start",
        "end",
        "place",
        "source_url",
        "observed_at",
    }
    if not isinstance(record, dict) or set(record) != required:
        return False
    if record["source_id"] != "26MC26":
        return False
    if record["source_url"] != FEPYC_26MC26_URL:
        return False
    if _fold(str(record["competition_type"])) != "nacional":
        return False
    if "guardamar" not in _fold(str(record["place"])):
        return False
    try:
        start = date.fromisoformat(record["start"])
        end = date.fromisoformat(record["end"])
        observed = datetime.fromisoformat(record["observed_at"])
    except (TypeError, ValueError):
        return False
    return (
        start <= end
        and observed.tzinfo is not None
        and observed.utcoffset() is not None
        and all(
            isinstance(record[key], str) and record[key]
            for key in (
                "match_title",
                "specialty",
                "category",
                "place",
            )
        )
    )


def valid_fepyc_authority_state(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"version", "records"}:
        return False
    if value.get("version") != _STATE_VERSION:
        return False
    records = value.get("records")
    return (
        isinstance(records, list)
        and len(records) <= _MAX_FEPYC_AUTHORITIES
        and all(_authority_record_valid(record) for record in records)
    )


def load_fepyc_authority_state(path: Path) -> Optional[dict]:
    return _load_json(path, valid_fepyc_authority_state, "FEPyC authority")


def parse_fepyc_authority_html(
    payload: bytes,
    *,
    observed_at: datetime,
    spec: dict,
) -> dict:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FishingEnrichmentError(
            "FEPyC authority HTML is not UTF-8", code="HTML"
        ) from exc
    parser = _VisibleTextParser()
    parser.feed(text)
    parser.close()
    visible = _fold(" ".join(parser.parts))

    source_id = spec["source_id"]
    if not re.search(rf"\bid\s*:\s*{re.escape(_fold(source_id))}\b", visible):
        raise FishingEnrichmentError("FEPyC event ID changed", code="SCHEMA")

    required_markers = {
        "specialty": "especialidad: lanzado mar costa",
        "category": "categoria: duos",
        "competition_type": "tipo competicion: nacional",
        "place": "lugar: guardamar del segura (alicante)",
    }
    for label, marker in required_markers.items():
        if marker not in visible:
            raise FishingEnrichmentError(
                f"FEPyC {label} marker changed", code="SCHEMA"
            )

    match = re.search(
        r"fecha:\s*del\s+(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+"
        r"([a-z]+)\s+de\s+(20\d{2})",
        visible,
    )
    if match is None:
        raise FishingEnrichmentError("FEPyC date range changed", code="SCHEMA")
    start = _parse_spanish_date(match.group(1), match.group(3), match.group(4))
    end = _parse_spanish_date(match.group(2), match.group(3), match.group(4))
    if end < start:
        raise FishingEnrichmentError("FEPyC date range is invalid", code="SCHEMA")

    return {
        "source_id": source_id,
        "match_title": spec["match_title"],
        "specialty": "Lanzado Mar Costa",
        "category": "Dúos",
        "competition_type": "Nacional",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "place": "Guardamar del Segura (Alicante)",
        "source_url": spec["url"],
        "observed_at": observed_at.isoformat(),
    }


async def _fetch_fepyc_record(now: datetime, spec: dict) -> dict:
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            spec["url"],
            is_allowed_url=_allowed_fepyc_url,
            accepted_types=_HTML_TYPES,
            limit_bytes=_FEPYC_HTML_LIMIT_BYTES,
            timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            headers=_HEADERS,
        )
    except BoundedFetchError as exc:
        raise FishingEnrichmentError(
            "FEPyC authority request failed", code=exc.code
        ) from exc
    return parse_fepyc_authority_html(payload, observed_at=now, spec=spec)


def _base_event_is_relevant_national(raw: dict, spec: dict, local_day: date) -> bool:
    try:
        end = date.fromisoformat(raw["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        end >= local_day
        and _fold(str(raw.get("level", ""))) == "nacional"
        and _fold(str(raw.get("title", ""))) == _fold(spec["match_title"])
        and str(raw.get("place", "")).startswith("Guardamar")
    )


async def refresh_fepyc_authority(
    now: datetime,
    base_events: tuple[dict, ...],
    state_path: Path,
) -> tuple[dict, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FEPyC authority time must be timezone-aware")
    if len(_FEPYC_SPECS) > _MAX_FEPYC_AUTHORITIES:
        raise FishingEnrichmentError("too many FEPyC authority specs", code="BOUNDS")

    previous = None
    try:
        previous = await asyncio.to_thread(load_fepyc_authority_state, state_path)
    except FishingEnrichmentError as exc:
        logging.warning(
            "FEPyC authority state ignored [%s]", exc.diagnostic_code
        )

    previous_by_id = {
        item["source_id"]: item
        for item in (previous or {}).get("records", [])
    }
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    records = []
    for spec in _FEPYC_SPECS:
        if not any(
            _base_event_is_relevant_national(raw, spec, local_day)
            for raw in base_events
        ):
            continue
        try:
            record = await _fetch_fepyc_record(now, spec)
        except FishingEnrichmentError as exc:
            old = previous_by_id.get(spec["source_id"])
            if old is None:
                logging.warning(
                    "FEPyC authority unavailable [%s]; no last-good record",
                    exc.diagnostic_code,
                )
                continue
            logging.warning(
                "FEPyC authority unavailable [%s]; preserving last-good %s",
                exc.diagnostic_code,
                spec["source_id"],
            )
            record = old
        records.append(record)

    state = {"version": _STATE_VERSION, "records": records}
    if not valid_fepyc_authority_state(state):
        raise FishingEnrichmentError(
            "FEPyC authority state failed validation", code="STATE"
        )
    await asyncio.to_thread(_write_json, state_path, state)
    return tuple(records)


def _index_header_map(rows: list[list[dict[str, Any]]]) -> tuple[int, dict[str, int]]:
    aliases = {
        "date": {"fecha"},
        "scope": {"ambito", "ámbito"},
        "modality": {"modalidad"},
        "venue": {"escenario"},
        "province": {"provincia"},
        "convocatoria": {"convocatoria"},
    }
    folded_aliases = {
        key: {_fold(value) for value in values}
        for key, values in aliases.items()
    }
    for row_index, row in enumerate(rows):
        mapped: dict[str, int] = {}
        for index, cell in enumerate(row):
            folded = _fold(str(cell["text"]))
            for key, values in folded_aliases.items():
                if folded in values and key not in mapped:
                    mapped[key] = index
        if set(aliases).issubset(mapped):
            return row_index, mapped
    raise FishingEnrichmentError(
        "FPCV convocatoria table header is missing", code="SCHEMA"
    )


def _parse_index_date(value: str) -> date:
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", value)
    if match is None:
        raise FishingEnrichmentError("FPCV index date is invalid", code="SCHEMA")
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError as exc:
        raise FishingEnrichmentError(
            "FPCV index date is invalid", code="SCHEMA"
        ) from exc


def _scope_level(value: str) -> Optional[str]:
    folded = _fold(value)
    for level in ("mundial", "nacional", "autonomico", "provincial"):
        if folded.startswith(level):
            return level
    return None


def _modality_matches(base_title: str, modality: str) -> bool:
    base_tokens = set(re.findall(r"[a-z0-9]+", _fold(base_title)))
    candidate_tokens = set(re.findall(r"[a-z0-9]+", _fold(modality)))
    return bool(base_tokens) and base_tokens <= candidate_tokens


def _base_match_candidates(
    *,
    row_day: date,
    scope: str,
    modality: str,
    venue: str,
    base_events: tuple[dict, ...],
) -> list[dict]:
    level = _scope_level(scope)
    if level is None:
        return []
    venue_folded = _fold(venue)
    cancelled = venue_folded == "cancelado"
    candidates = []
    for raw in base_events:
        try:
            start = date.fromisoformat(raw["start"])
            end = date.fromisoformat(raw["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not start <= row_day <= end:
            continue
        if _fold(str(raw.get("level", ""))) != level:
            continue
        if not _modality_matches(str(raw.get("title", "")), modality):
            continue
        if not cancelled and "guardamar" not in venue_folded:
            continue
        candidates.append(raw)
    return candidates


def _join_key(raw: dict) -> str:
    return "|".join(
        (
            str(raw["start"]),
            _fold(str(raw["level"])),
            _fold(str(raw["title"])),
        )
    )


def _document_identity(
    *,
    row_day: date,
    scope: str,
    modality: str,
    venue: str,
    pdf_url: Optional[str],
) -> str:
    semantic = json.dumps(
        {
            "date": row_day.isoformat(),
            "scope": " ".join(scope.split()),
            "modality": " ".join(modality.split()),
            "venue": " ".join(venue.split()),
            "pdf_url": pdf_url,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(semantic).hexdigest()


def parse_fpcv_index_html(
    payload: bytes,
    *,
    local_day: date,
    base_events: tuple[dict, ...],
) -> tuple[dict, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FishingEnrichmentError(
            "FPCV index HTML is not UTF-8", code="HTML"
        ) from exc
    parser = _LinkedTableParser()
    parser.feed(text)
    parser.close()
    header_index, columns = _index_header_map(parser.rows)
    required_max = max(columns.values())

    descriptors = []
    seen_keys = set()
    for row in parser.rows[header_index + 1 :]:
        if len(row) <= required_max:
            continue
        raw_date = str(row[columns["date"]]["text"])
        if re.search(r"\b\d{1,2}/\d{1,2}/20\d{2}\b", raw_date) is None:
            # Ignore decorative/service rows that may share the table shape.
            continue
        row_day = _parse_index_date(raw_date)
        if row_day < local_day:
            continue
        scope = str(row[columns["scope"]]["text"])
        modality = str(row[columns["modality"]]["text"])
        venue = str(row[columns["venue"]]["text"])
        candidates = _base_match_candidates(
            row_day=row_day,
            scope=scope,
            modality=modality,
            venue=venue,
            base_events=base_events,
        )
        if not candidates:
            continue
        if len(candidates) != 1:
            raise FishingEnrichmentError(
                "FPCV index row matches multiple Guardamar events", code="SCHEMA"
            )
        raw = candidates[0]
        key = _join_key(raw)
        if key in seen_keys:
            raise FishingEnrichmentError(
                "FPCV index has duplicate Guardamar detail rows", code="SCHEMA"
            )
        seen_keys.add(key)

        pdf_links = []
        for href in row[columns["convocatoria"]]["links"]:
            candidate = urllib.parse.urljoin(FPCV_INDEX_URL, href)
            if _allowed_fpcv_pdf_url(candidate):
                pdf_links.append(candidate)
        pdf_links = sorted(set(pdf_links))
        if len(pdf_links) > 1:
            raise FishingEnrichmentError(
                "FPCV index has multiple convocatoria PDFs", code="SCHEMA"
            )
        cancelled = _fold(venue) == "cancelado"
        pdf_url = pdf_links[0] if pdf_links else None
        descriptors.append(
            {
                "join_key": key,
                "base_start": str(raw["start"]),
                "base_level": str(raw["level"]),
                "base_title": str(raw["title"]),
                "index_date": row_day.isoformat(),
                "scope": " ".join(scope.split()),
                "modality": " ".join(modality.split()),
                "venue": " ".join(venue.split()),
                "cancelled": cancelled,
                "pdf_url": pdf_url,
                "document_identity": _document_identity(
                    row_day=row_day,
                    scope=scope,
                    modality=modality,
                    venue=venue,
                    pdf_url=pdf_url,
                ),
            }
        )
        if len(descriptors) > _MAX_FPCV_DETAILS:
            raise FishingEnrichmentError(
                "too many relevant FPCV convocatoria rows", code="BOUNDS"
            )
    return tuple(descriptors)


async def _fetch_fpcv_index(
    now: datetime,
    base_events: tuple[dict, ...],
) -> tuple[dict, ...]:
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            FPCV_INDEX_URL,
            is_allowed_url=_allowed_fpcv_index_url,
            accepted_types=_HTML_TYPES,
            limit_bytes=_FPCV_INDEX_LIMIT_BYTES,
            timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            headers=_HEADERS,
        )
    except BoundedFetchError as exc:
        raise FishingEnrichmentError(
            "FPCV convocatoria index request failed", code=exc.code
        ) from exc
    return parse_fpcv_index_html(
        payload,
        local_day=now.astimezone(GUARDAMAR_TIMEZONE).date(),
        base_events=base_events,
    )


def extract_fpcv_pdf_text(payload: bytes) -> str:
    if (
        not payload.startswith(b"%PDF-")
        or len(payload) > _FPCV_PDF_LIMIT_BYTES
    ):
        raise FishingEnrichmentError(
            "FPCV convocatoria is not a bounded PDF", code="PDF"
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
        raise FishingEnrichmentError(
            "pdftotext is unavailable", code="PDF-TO-TEXT"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FishingEnrichmentError(
            "pdftotext timed out", code="PDF-TIMEOUT"
        ) from exc
    except OSError as exc:
        raise FishingEnrichmentError(
            "pdftotext failed", code="PDF-TO-TEXT"
        ) from exc
    if completed.returncode != 0:
        raise FishingEnrichmentError(
            "pdftotext rejected FPCV convocatoria", code="PDF-PARSE"
        )
    if (
        not completed.stdout
        or len(completed.stdout) > _FPCV_PDF_TEXT_LIMIT_BYTES
    ):
        raise FishingEnrichmentError(
            "FPCV convocatoria text is empty or too large", code="PDF-PARSE"
        )
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FishingEnrichmentError(
            "FPCV convocatoria text is not UTF-8", code="PDF-PARSE"
        ) from exc


async def _fetch_fpcv_pdf_text(url: str) -> str:
    if not _allowed_fpcv_pdf_url(url):
        raise FishingEnrichmentError(
            "FPCV convocatoria URL is outside policy", code="URL-POLICY"
        )
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            url,
            is_allowed_url=_allowed_fpcv_pdf_url,
            accepted_types=_PDF_TYPES,
            limit_bytes=_FPCV_PDF_LIMIT_BYTES,
            timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            headers=_HEADERS,
        )
    except BoundedFetchError as exc:
        raise FishingEnrichmentError(
            "FPCV convocatoria PDF request failed", code=exc.code
        ) from exc
    return await asyncio.to_thread(extract_fpcv_pdf_text, payload)


def _parse_clock(value: str) -> time:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if match is None:
        raise FishingEnrichmentError("invalid programme time", code="PDF-SCHEMA")
    try:
        return time(int(match.group(1)), int(match.group(2)))
    except ValueError as exc:
        raise FishingEnrichmentError(
            "invalid programme time", code="PDF-SCHEMA"
        ) from exc


def _datetime_on(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=GUARDAMAR_TIMEZONE)


def parse_fpcv_convocatoria_text(
    text: str,
    *,
    descriptor: dict,
    observed_at: datetime,
) -> dict:
    folded = _fold(text)
    if "campeonato provincial de alicante" not in folded:
        raise FishingEnrichmentError(
            "FPCV convocatoria competition marker changed", code="PDF-SCHEMA"
        )
    qualification = re.search(
        r"clasificatorio\s+para\s+el\s+comunidad\s+valenciana\s+"
        r"(20\d{2})",
        folded,
    )
    if qualification is None:
        raise FishingEnrichmentError(
            "FPCV qualification marker changed", code="PDF-SCHEMA"
        )
    if "playas la roqueta y centro" not in folded or "guardamar" not in folded:
        raise FishingEnrichmentError(
            "FPCV convocatoria Guardamar venue changed", code="PDF-SCHEMA"
        )

    event_match = re.search(
        r"lugar,\s*fecha:\s*(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(20\d{2})",
        folded,
    )
    if event_match is None:
        raise FishingEnrichmentError(
            "FPCV convocatoria event date changed", code="PDF-SCHEMA"
        )
    event_day = _parse_spanish_date(
        event_match.group(1), event_match.group(2), event_match.group(3)
    )
    if event_day.isoformat() != descriptor["index_date"]:
        raise FishingEnrichmentError(
            "FPCV PDF date disagrees with convocatoria index", code="PDF-SCHEMA"
        )

    deadline_match = re.search(
        r"inscripciones\s+se\s+realizaran\s+por\s+los\s+clubes\s+hasta\s+el\s+"
        r"(\d{1,2})\s+de\s+([a-z]+)\s+a\s+las\s+(\d{1,2})(?::(\d{2}))?\s*h",
        folded,
    )
    if deadline_match is None:
        raise FishingEnrichmentError(
            "FPCV registration deadline changed", code="PDF-SCHEMA"
        )
    deadline_day = _parse_spanish_date(
        deadline_match.group(1),
        deadline_match.group(2),
        str(event_day.year),
    )
    deadline_clock = time(
        int(deadline_match.group(3)),
        int(deadline_match.group(4) or "0"),
    )
    registration_deadline = _datetime_on(deadline_day, deadline_clock)
    if registration_deadline.date() >= event_day:
        raise FishingEnrichmentError(
            "FPCV registration deadline is not before event", code="PDF-SCHEMA"
        )

    heat_match = re.search(r"mangas\.\s*-?\s*(\d+)\s+mangas\s+de\s+(\d+)\s+horas", folded)
    if heat_match is None:
        raise FishingEnrichmentError(
            "FPCV heat duration changed", code="PDF-SCHEMA"
        )
    heat_count = int(heat_match.group(1))
    heat_hours = int(heat_match.group(2))
    if heat_count <= 0 or heat_hours <= 0:
        raise FishingEnrichmentError(
            "FPCV heat duration is invalid", code="PDF-SCHEMA"
        )

    programme_patterns = {
        "concentration": r"(\d{1,2}:\d{2})\s*h\.\s*concentracion",
        "first_start": r"(\d{1,2}:\d{2})\s*h\.\s*comienzo\s+de\s+la\s+primera\s+manga",
        "first_end": r"(\d{1,2}:\d{2})\s*h\.\s*fin\s+de\s+la\s+primera\s+manga",
        "second_start": r"(\d{1,2}:\d{2})\s*h\.\s*inicio\s+de\s+la\s+segunda\s+manga",
        "second_end": r"(\d{1,2}:\d{2})\s*h\.\s*fin\s+de\s+la\s+segunda\s+manga",
    }
    clocks: dict[str, time] = {}
    labels: dict[str, str] = {}
    for key, pattern in programme_patterns.items():
        match = re.search(pattern, folded)
        if match is None:
            raise FishingEnrichmentError(
                f"FPCV programme marker {key} changed", code="PDF-SCHEMA"
            )
        labels[key] = match.group(1)
        clocks[key] = _parse_clock(match.group(1))

    start_at = _datetime_on(event_day, clocks["first_start"])
    end_day = event_day
    if clocks["second_end"] <= clocks["first_start"]:
        end_day += timedelta(days=1)
    end_at = _datetime_on(end_day, clocks["second_end"])
    if end_at <= start_at:
        raise FishingEnrichmentError(
            "FPCV programme end is not after start", code="PDF-SCHEMA"
        )

    fee_match = re.search(
        r"cada\s+participante\s+debera\s+abonar\s+(\d+)\s*€\s+por\s+su\s+inscripcion",
        folded,
    )
    fee_cents = int(fee_match.group(1)) * 100 if fee_match else None

    schedule_may_shift = (
        "horario podra modificarse levemente segun la ocupacion de banistas"
        in folded
    )
    qualification_year = qualification.group(1)
    details = [
        (
            "Провинциальный чемпионат Аликанте · "
            f"отбор на Comunidad Valenciana {qualification_year}"
        ),
        f"{heat_count} тура по {heat_hours} часа",
        f"Сбор участников: {labels['concentration']}",
        f"1-й тур: {labels['first_start']}–{labels['first_end']}",
        f"2-й тур: {labels['second_start']}–{labels['second_end']}",
    ]

    return {
        "join_key": descriptor["join_key"],
        "base_start": descriptor["base_start"],
        "base_level": descriptor["base_level"],
        "base_title": descriptor["base_title"],
        "index_date": descriptor["index_date"],
        "cancelled": False,
        "source_url": descriptor["pdf_url"],
        "document_identity": descriptor["document_identity"],
        "competition_context": details[0],
        "details": details,
        "starts_at": start_at.isoformat(),
        "ends_at": end_at.isoformat(),
        "place": "Playas La Roqueta y Centro",
        "schedule_note": (
            "Время может немного измениться из-за занятости пляжей"
            if schedule_may_shift
            else None
        ),
        "registration_method": "clubs",
        "registration_deadline": registration_deadline.isoformat(),
        "registration_fee_cents": fee_cents,
        "observed_at": observed_at.isoformat(),
    }


_DETAILS_KEYS = {
    "join_key",
    "base_start",
    "base_level",
    "base_title",
    "index_date",
    "cancelled",
    "source_url",
    "document_identity",
    "competition_context",
    "details",
    "starts_at",
    "ends_at",
    "place",
    "schedule_note",
    "registration_method",
    "registration_deadline",
    "registration_fee_cents",
    "observed_at",
}


def _details_record_valid(record: Any) -> bool:
    if not isinstance(record, dict) or set(record) != _DETAILS_KEYS:
        return False
    if not isinstance(record["join_key"], str) or not record["join_key"]:
        return False
    if not isinstance(record["cancelled"], bool):
        return False
    if (
        not isinstance(record["document_identity"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", record["document_identity"])
    ):
        return False
    try:
        date.fromisoformat(record["base_start"])
        date.fromisoformat(record["index_date"])
        observed = datetime.fromisoformat(record["observed_at"])
    except (TypeError, ValueError):
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    if not all(
        isinstance(record[key], str) and record[key]
        for key in ("base_level", "base_title")
    ):
        return False
    if record["cancelled"]:
        return all(
            record[key] is None or record[key] == []
            for key in (
                "source_url",
                "competition_context",
                "details",
                "starts_at",
                "ends_at",
                "place",
                "schedule_note",
                "registration_method",
                "registration_deadline",
                "registration_fee_cents",
            )
        )

    if not isinstance(record["source_url"], str) or not _allowed_fpcv_pdf_url(
        record["source_url"]
    ):
        return False
    if not isinstance(record["competition_context"], str) or not record[
        "competition_context"
    ]:
        return False
    if (
        not isinstance(record["details"], list)
        or not 1 <= len(record["details"]) <= 8
        or not all(isinstance(item, str) and item for item in record["details"])
    ):
        return False
    try:
        starts_at = datetime.fromisoformat(record["starts_at"])
        ends_at = datetime.fromisoformat(record["ends_at"])
        deadline = datetime.fromisoformat(record["registration_deadline"])
    except (TypeError, ValueError):
        return False
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in (starts_at, ends_at, deadline)
    ):
        return False
    if ends_at <= starts_at or deadline >= starts_at:
        return False
    if record["registration_method"] != "clubs":
        return False
    if record["registration_fee_cents"] is not None and (
        not isinstance(record["registration_fee_cents"], int)
        or isinstance(record["registration_fee_cents"], bool)
        or record["registration_fee_cents"] < 0
    ):
        return False
    return (
        isinstance(record["place"], str)
        and bool(record["place"])
        and (
            record["schedule_note"] is None
            or isinstance(record["schedule_note"], str)
        )
    )


def valid_fpcv_details_state(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"version", "records"}:
        return False
    if value.get("version") != _STATE_VERSION:
        return False
    records = value.get("records")
    if (
        not isinstance(records, list)
        or len(records) > _MAX_FPCV_DETAILS
        or not all(_details_record_valid(record) for record in records)
    ):
        return False
    keys = [record["join_key"] for record in records]
    return len(keys) == len(set(keys))


def load_fpcv_details_state(path: Path) -> Optional[dict]:
    return _load_json(path, valid_fpcv_details_state, "FPCV details")


def _cancelled_record(descriptor: dict, observed_at: datetime) -> dict:
    return {
        "join_key": descriptor["join_key"],
        "base_start": descriptor["base_start"],
        "base_level": descriptor["base_level"],
        "base_title": descriptor["base_title"],
        "index_date": descriptor["index_date"],
        "cancelled": True,
        "source_url": None,
        "document_identity": descriptor["document_identity"],
        "competition_context": None,
        "details": [],
        "starts_at": None,
        "ends_at": None,
        "place": None,
        "schedule_note": None,
        "registration_method": None,
        "registration_deadline": None,
        "registration_fee_cents": None,
        "observed_at": observed_at.isoformat(),
    }


def _reuse_current_record(record: dict, observed_at: datetime) -> dict:
    reused = dict(record)
    reused["observed_at"] = observed_at.isoformat()
    return reused


async def refresh_fpcv_details(
    now: datetime,
    base_events: tuple[dict, ...],
    state_path: Path,
) -> tuple[dict, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FPCV details time must be timezone-aware")

    previous = None
    try:
        previous = await asyncio.to_thread(load_fpcv_details_state, state_path)
    except FishingEnrichmentError as exc:
        logging.warning("FPCV details state ignored [%s]", exc.diagnostic_code)
    previous_by_key = {
        item["join_key"]: item
        for item in (previous or {}).get("records", [])
    }

    descriptors = await _fetch_fpcv_index(now, base_events)
    records = []
    for descriptor in descriptors:
        key = descriptor["join_key"]
        old = previous_by_key.get(key)
        if descriptor["cancelled"]:
            records.append(_cancelled_record(descriptor, now))
            continue
        if (
            old is not None
            and not old["cancelled"]
            and old["document_identity"] == descriptor["document_identity"]
        ):
            records.append(_reuse_current_record(old, now))
            continue
        if descriptor["pdf_url"] is None:
            logging.warning(
                "FPCV detail row has no eligible PDF; omitting %s", key
            )
            continue
        try:
            text = await _fetch_fpcv_pdf_text(descriptor["pdf_url"])
            record = parse_fpcv_convocatoria_text(
                text,
                descriptor=descriptor,
                observed_at=now,
            )
        except FishingEnrichmentError as exc:
            if old is not None:
                logging.warning(
                    "FPCV detail refresh failed [%s]; preserving last-good %s",
                    exc.diagnostic_code,
                    key,
                )
                records.append(old)
                continue
            logging.warning(
                "FPCV detail refresh failed [%s]; no last-good %s",
                exc.diagnostic_code,
                key,
            )
            continue
        records.append(record)

    state = {"version": _STATE_VERSION, "records": records}
    if not valid_fpcv_details_state(state):
        raise FishingEnrichmentError(
            "FPCV details state failed validation", code="STATE"
        )
    await asyncio.to_thread(_write_json, state_path, state)
    return tuple(records)


def matching_authority(raw: dict, state: Optional[dict]) -> Optional[dict]:
    if _fold(str(raw.get("level", ""))) != "nacional":
        return None
    for record in (state or {}).get("records", []):
        if _fold(record["match_title"]) == _fold(str(raw.get("title", ""))):
            return record
    return None


def matching_detail(raw: dict, state: Optional[dict]) -> Optional[dict]:
    key = _join_key(raw)
    for record in (state or {}).get("records", []):
        if record["join_key"] == key:
            return record
    return None
