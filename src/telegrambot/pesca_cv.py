"""Bounded Federación de Pesca CV source for resident-relevant Guardamar events."""

import asyncio
import re
import unicodedata
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Optional

from ._transport import BoundedFetchError, fetch_bounded

PESCA_CV_URL = "https://federacionpescacv.com/competiciones-de-nuestros-clubes/"
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "guardamar-status-bot/1.0",
}
_MAX_BYTES = 1536 * 1024
_TIMEOUT_SECONDS = 15.0
_MAX_EVENTS = 64
_ALLOWED_LEVELS = frozenset({"mundial", "nacional", "autonomico", "provincial"})


class PescaCvSourceError(RuntimeError):
    """A Pesca CV observation that is unsafe to use."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", " ".join(value.split())).casefold()
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "federacionpescacv.com"
        and port in {None, 443}
        and parsed.path == "/competiciones-de-nuestros-clubes/"
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.casefold()
        if lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"td", "th"} and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _parse_date(value: str) -> date:
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", value)
    if match is None:
        raise PescaCvSourceError("Pesca CV event date is invalid", code="SCHEMA")
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError as exc:
        raise PescaCvSourceError("Pesca CV event date is invalid", code="SCHEMA") from exc


def _header_map(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    # Current production table: FECHA | CLUB | ENTIDAD | AMBITO |
    # MODALIDAD | ESCENARIO | PROVINCIA | ZONA. Keep a few language aliases,
    # but deliberately do not treat CLUB (the short code) as the organizer.
    aliases = {
        "date": {"fecha", "data"},
        "organizer": {"entidad", "organizador", "organiza"},
        "level": {"ambito", "ámbito", "nivel", "tipo"},
        "modality": {"modalidad", "modalitat"},
        "location": {"escenario", "localidad", "poblacion", "población", "lugar"},
        "zone": {"zona", "pesquero"},
    }
    folded_aliases = {key: {_fold(item) for item in values} for key, values in aliases.items()}
    for row_index, row in enumerate(rows):
        mapped: dict[str, int] = {}
        for index, cell in enumerate(row):
            folded = _fold(cell)
            for key, values in folded_aliases.items():
                if folded in values and key not in mapped:
                    mapped[key] = index
        if {"date", "organizer", "level", "modality", "location"}.issubset(mapped):
            return row_index, mapped
    raise PescaCvSourceError("Pesca CV competition table header is missing", code="SCHEMA")


def _event_title(modality: str) -> str:
    folded = _fold(modality)
    if folded == "mar costa duos":
        return "Mar Costa Dúos"
    return " ".join(modality.split())


def parse_pesca_cv_html(payload: bytes, local_day: date, observed_at: datetime) -> dict:
    """Normalize high-value current/future Guardamar competitions."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PescaCvSourceError("Pesca CV HTML is invalid", code="HTML") from exc
    parser = _TableParser()
    parser.feed(text)
    header_index, columns = _header_map(parser.rows)
    required_max = max(columns.values())
    raw = []
    for row in parser.rows[header_index + 1 :]:
        if len(row) <= required_max:
            continue
        location = " ".join(row[columns["location"]].split())
        if _fold(location) != "guardamar":
            continue
        level = " ".join(row[columns["level"]].split())
        if _fold(level) not in _ALLOWED_LEVELS:
            continue
        modality = " ".join(row[columns["modality"]].split())
        organizer = " ".join(row[columns["organizer"]].split())
        zone = ""
        if "zone" in columns and columns["zone"] < len(row):
            zone = " ".join(row[columns["zone"]].split()).rstrip("*# ")
        if not modality or not organizer or len(modality) > 180 or len(organizer) > 180 or len(zone) > 120:
            raise PescaCvSourceError("Pesca CV target row is invalid", code="SCHEMA")
        day = _parse_date(row[columns["date"]])
        if day < local_day:
            continue
        raw.append(
            {
                "date": day,
                "organizer": organizer,
                "level": level,
                "modality": modality,
                "location": location,
                "zone": zone,
            }
        )

    grouped: dict[tuple[str, ...], list[date]] = defaultdict(list)
    values: dict[tuple[str, ...], dict] = {}
    for row in raw:
        identity = (
            _fold(row["organizer"]),
            _fold(row["level"]),
            _fold(row["modality"]),
            _fold(row["location"]),
            _fold(row["zone"]),
        )
        grouped[identity].append(row["date"])
        values[identity] = row

    events = []
    for identity, days in grouped.items():
        unique_days = sorted(set(days))
        if not unique_days:
            continue
        runs = []
        run_start = run_end = unique_days[0]
        for day in unique_days[1:]:
            if day == run_end + timedelta(days=1):
                run_end = day
            else:
                runs.append((run_start, run_end))
                run_start = run_end = day
        runs.append((run_start, run_end))
        row = values[identity]
        for start, end in runs:
            events.append(
                {
                    "sport": "fishing",
                    "title": _event_title(row["modality"]),
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "place": "Guardamar" if not row["zone"] else f"Guardamar · {row['zone'].title()}",
                    "organizer": row["organizer"],
                    "level": row["level"],
                    "source_url": PESCA_CV_URL,
                }
            )
            if len(events) > _MAX_EVENTS:
                raise PescaCvSourceError("Pesca CV Guardamar event set is too large", code="SCHEMA")
    events.sort(key=lambda item: (item["start"], item["title"].casefold()))
    return {"observed_at": observed_at.isoformat(), "events": events}


def valid_pesca_cv_snapshot(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"observed_at", "events"}:
        return False
    try:
        observed = datetime.fromisoformat(value["observed_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    events = value.get("events")
    if not isinstance(events, list) or len(events) > _MAX_EVENTS:
        return False
    required = {"sport", "title", "start", "end", "place", "organizer", "level", "source_url"}
    for event in events:
        if not isinstance(event, dict) or set(event) != required:
            return False
        if event.get("sport") != "fishing" or event.get("source_url") != PESCA_CV_URL:
            return False
        if _fold(str(event.get("level", ""))) not in _ALLOWED_LEVELS:
            return False
        if not all(isinstance(event.get(key), str) and event[key] for key in ("title", "place", "organizer")):
            return False
        try:
            start = date.fromisoformat(event["start"])
            end = date.fromisoformat(event["end"])
        except (TypeError, ValueError):
            return False
        if end < start:
            return False
    return True


async def fetch_pesca_cv_snapshot(now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Pesca CV observation time must be timezone-aware")
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            PESCA_CV_URL,
            is_allowed_url=_allowed_url,
            accepted_types=_HTML_TYPES,
            limit_bytes=_MAX_BYTES,
            timeout_seconds=_TIMEOUT_SECONDS,
            headers=_HEADERS,
        )
    except BoundedFetchError as exc:
        raise PescaCvSourceError("Pesca CV request failed", code=exc.code) from exc
    return parse_pesca_cv_html(payload, now.date(), now)
