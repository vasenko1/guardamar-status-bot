"""Bounded municipal Dinamización Social discovery and normalization."""

import asyncio
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Optional

from ._transport import BoundedFetchError, fetch_bounded

FEED_URL = "https://www.guardamardelsegura.es/feed/"
AYTO_HOSTS = frozenset({
    "guardamardelsegura.es",
    "www.guardamardelsegura.es",
})
GOOGLE_FORM_HOST = "docs.google.com"
REQUEST_TIMEOUT_SECONDS = 15
FEED_LIMIT_BYTES = 64 * 1024
DETAIL_LIMIT_BYTES = 128 * 1024
FORM_LIMIT_BYTES = 128 * 1024

_CAMPAIGN_TITLE_RE = re.compile(
    r"programa\s+(?:de\s+)?dinamizaci[oó]n\s+social.*?"
    r"(20\d{2})\s*[/–-]\s*(20\d{2})",
    re.IGNORECASE,
)
_REGISTRATION_RE = re.compile(
    r"plazo\s+de\s+inscripci[oó]n\s*:\s*del\s+"
    r"(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre)\s+de\s+(20\d{2})",
    re.IGNORECASE,
)
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2})\s*(?:[–—-]|a)\s*(\d{1,2}:\d{2})"
)
_DATE_RANGE_RE = re.compile(
    r"\((\d{1,2})\s+"
    r"(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s*[-–—]\s*"
    r"(\d{1,2})\s+"
    r"(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+"
    r"(20\d{2})\)",
    re.IGNORECASE,
)
_START_NOTE_RE = re.compile(
    r"a\s+partir\s+del\s+(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre)",
    re.IGNORECASE,
)
_WORKSHOP_ROW_RE = re.compile(
    r"\d+\s*h(?:\s*\d+\s*min)?\s*/\s*semana\.\s*"
    r"(.*?)(?="
    r"\d+\s*h(?:\s*\d+\s*min)?\s*/\s*semana\."
    r"|¿Quiere indicarnos|$)",
    re.IGNORECASE | re.DOTALL,
)
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_SHORT_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

_GROUPS = (
    ("mindful_movement", "MOVIMIENTO CONSCIENTE"),
    ("mobile", "USO DEL MOVIL"),
    ("recycled_art", "ARTE RECICLADO CREATIVO"),
    ("textile_painting", "PINTURA TEXTIL"),
    ("senior_hiking", "SENDERISMO PARA MAYORES"),
    ("senior_memory", "MEMORIA PARA MAYORES"),
    ("senior_computing", "INFORMÁTICA PARA MAYORES"),
    ("emotions_school", "ESCUELA DE EMOCIONES"),
)
_GROUP_MARKERS = {
    marker.casefold(): key
    for key, marker in _GROUPS
}


class DinamizacionSourceError(RuntimeError):
    """Operator-safe Dinamización source failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


class _HtmlParts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hrefs: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if isinstance(href, str):
            self.hrefs.append(href)


def _allowed_ayto_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in AYTO_HOSTS
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
    )


def _allowed_form_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == GOOGLE_FORM_HOST
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/forms/d/e/")
        and parsed.path.rstrip("/").endswith("/viewform")
    )


def _fetch(
    url: str,
    *,
    allowed,
    limit_bytes: int,
    accepted_types: frozenset[str],
) -> bytes:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=allowed,
            limit_bytes=limit_bytes,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": ",".join(sorted(accepted_types)),
                "Accept-Language": "es",
                "User-Agent": "guardamar-status-bot/1.0",
            },
            accepted_types=accepted_types,
        )
    except BoundedFetchError as exc:
        raise DinamizacionSourceError(
            "Dinamización source request failed", code=exc.code
        ) from exc
    return payload


def _read_feed() -> bytes:
    return _fetch(
        FEED_URL,
        allowed=_allowed_ayto_url,
        limit_bytes=FEED_LIMIT_BYTES,
        accepted_types=frozenset({
            "application/rss+xml",
            "application/xml",
            "text/xml",
        }),
    )


def _campaign_from_feed(payload: bytes) -> Optional[tuple[str, str]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DinamizacionSourceError(
            "municipal RSS is invalid", code="XML"
        ) from exc
    candidates = []
    for item in root.findall(".//item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        match = _CAMPAIGN_TITLE_RE.search(title)
        if match is None or not _allowed_ayto_url(link):
            continue
        start_year = int(match.group(1))
        end_year = int(match.group(2))
        if end_year != start_year + 1:
            continue
        candidates.append((start_year, link, f"{start_year}/{str(end_year)[2:]}"))
    if not candidates:
        return None
    _, link, season = max(candidates, key=lambda item: item[0])
    return link, season


async def discover_dinamizacion_campaign() -> Optional[tuple[str, str]]:
    payload = await asyncio.to_thread(_read_feed)
    return _campaign_from_feed(payload)


def _form_link(detail_payload: bytes, campaign_url: str) -> str:
    try:
        source = detail_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DinamizacionSourceError(
            "Dinamización detail HTML is invalid", code="HTML"
        ) from exc
    parser = _HtmlParts()
    parser.feed(source)
    parser.close()
    links = set()
    for href in parser.hrefs:
        candidate = urllib.parse.urljoin(campaign_url, href)
        if _allowed_form_url(candidate):
            links.add(candidate)
    if len(links) != 1:
        raise DinamizacionSourceError(
            "Dinamización form link is missing or ambiguous",
            code="FORM-LINK",
        )
    return links.pop()


def _normalized_form_parts(payload: bytes) -> list[str]:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DinamizacionSourceError(
            "Dinamización form HTML is invalid", code="HTML"
        ) from exc
    parser = _HtmlParts()
    parser.feed(source)
    parser.close()
    return parser.parts


def _time(value: str) -> str:
    """Normalize source times to zero-padded HH:MM after validating them."""

    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError) as exc:
        raise DinamizacionSourceError(
            "Dinamización workshop time is invalid",
            code="SCHEMA",
        ) from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise DinamizacionSourceError(
            "Dinamización workshop time is invalid",
            code="SCHEMA",
        )
    return f"{hour:02d}:{minute:02d}"


def _days(line: str) -> Optional[str]:
    folded = line.casefold()
    if "lunes y miércoles" in folded or "lunes y miercoles" in folded:
        return "Пн/Ср"
    if "martes y jueves" in folded:
        return "Вт/Чт"
    if "viernes" in folded:
        return "Пт"
    if "miércoles" in folded or "miercoles" in folded:
        return "Ср"
    return None


def _group_key(line: str) -> Optional[str]:
    folded = line.casefold()
    folded = folded.replace("móvil", "movil")
    for marker, key in _GROUP_MARKERS.items():
        normalized_marker = marker.replace("móvil", "movil")
        if normalized_marker in folded:
            return key
    return None


def _extract_groups(parts: list[str], season_start_year: int) -> list[dict]:
    grouped: dict[str, dict] = {}
    text = " ".join(parts)
    candidates = [
        " ".join(match.group(1).split())
        for match in _WORKSHOP_ROW_RE.finditer(text)
    ]
    for line in candidates:
        if _TIME_RANGE_RE.search(line) is None:
            raise DinamizacionSourceError(
                "Dinamización workshop row has no time range",
                code="SCHEMA",
            )
        key = _group_key(line)
        if key is None:
            raise DinamizacionSourceError(
                "Dinamización form contains an unknown workshop row",
                code="UNKNOWN-GROUP",
            )
        day_label = _days(line)
        times = _TIME_RANGE_RE.findall(line)
        if day_label is None or len(times) != 1:
            raise DinamizacionSourceError(
                "Dinamización workshop schedule is invalid",
                code="SCHEMA",
            )
        start_time, end_time = (_time(value) for value in times[0])
        if start_time >= end_time:
            raise DinamizacionSourceError(
                "Dinamización workshop time is reversed",
                code="SCHEMA",
            )
        bucket = grouped.setdefault(key, {
            "key": key,
            "schedules": [],
            "start_date": None,
            "end_date": None,
        })
        schedule = f"{day_label} · {start_time}–{end_time}"
        if schedule not in bucket["schedules"]:
            bucket["schedules"].append(schedule)

        start_note = _START_NOTE_RE.search(line)
        if start_note is not None:
            try:
                bucket["start_date"] = date(
                    season_start_year,
                    _MONTHS[start_note.group(2).casefold()],
                    int(start_note.group(1)),
                ).isoformat()
            except ValueError as exc:
                raise DinamizacionSourceError(
                    "Dinamización workshop start date is invalid",
                    code="SCHEMA",
                ) from exc

        date_range = _DATE_RANGE_RE.search(line)
        if date_range is not None:
            try:
                start = date(
                    int(date_range.group(5)),
                    _SHORT_MONTHS[date_range.group(2).casefold()],
                    int(date_range.group(1)),
                )
                end = date(
                    int(date_range.group(5)),
                    _SHORT_MONTHS[date_range.group(4).casefold()],
                    int(date_range.group(3)),
                )
            except ValueError as exc:
                raise DinamizacionSourceError(
                    "Dinamización workshop date range is invalid",
                    code="SCHEMA",
                ) from exc
            if end < start:
                raise DinamizacionSourceError(
                    "Dinamización workshop date range is reversed",
                    code="SCHEMA",
                )
            bucket["start_date"] = start.isoformat()
            bucket["end_date"] = end.isoformat()

    if not grouped:
        raise DinamizacionSourceError(
            "Dinamización form has no workshop rows", code="SCHEMA"
        )
    order = {key: index for index, (key, _) in enumerate(_GROUPS)}
    result = sorted(grouped.values(), key=lambda item: order[item["key"]])
    for item in result:
        item["schedules"].sort()
    return result


def _extract_snapshot(
    form_payload: bytes,
    campaign_url: str,
    form_url: str,
    season: str,
    now: datetime,
) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Dinamización observation time must be timezone-aware")
    parts = _normalized_form_parts(form_payload)
    text = " ".join(parts)
    registration = _REGISTRATION_RE.search(text)
    if registration is None:
        raise DinamizacionSourceError(
            "Dinamización registration window is missing", code="SCHEMA"
        )
    try:
        registration_start = date(
            int(registration.group(4)),
            _MONTHS[registration.group(3).casefold()],
            int(registration.group(1)),
        )
        registration_end = date(
            int(registration.group(4)),
            _MONTHS[registration.group(3).casefold()],
            int(registration.group(2)),
        )
    except ValueError as exc:
        raise DinamizacionSourceError(
            "Dinamización registration window is invalid", code="SCHEMA"
        ) from exc
    if registration_end < registration_start:
        raise DinamizacionSourceError(
            "Dinamización registration window is reversed", code="SCHEMA"
        )
    season_start_year = int(season.split("/", 1)[0])
    folded = text.casefold()
    until_full = (
        "inscripción continuará abierta hasta completarlas" in folded
        or "inscripcion continuara abierta hasta completarlas" in folded
    )
    resident_priority = (
        "podrá participar únicamente si quedan plazas disponibles" in folded
        or "podra participar unicamente si quedan plazas disponibles" in folded
    )
    if not until_full or not resident_priority:
        raise DinamizacionSourceError(
            "Dinamización participation rules are incomplete", code="SCHEMA"
        )
    return {
        "observed_at": now.isoformat(),
        "season": season,
        "campaign_url": campaign_url,
        "form_url": form_url,
        "registration_start": registration_start.isoformat(),
        "registration_end": registration_end.isoformat(),
        "registration_until_full": True,
        "resident_priority": True,
        "groups": _extract_groups(parts, season_start_year),
    }


async def fetch_dinamizacion_snapshot(
    campaign_url: str,
    season: str,
    now: datetime,
) -> dict:
    if not _allowed_ayto_url(campaign_url):
        raise DinamizacionSourceError(
            "Dinamización campaign URL is invalid", code="URL-POLICY"
        )
    detail = await asyncio.to_thread(
        _fetch,
        campaign_url,
        allowed=_allowed_ayto_url,
        limit_bytes=DETAIL_LIMIT_BYTES,
        accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
    )
    form_url = _form_link(detail, campaign_url)
    form = await asyncio.to_thread(
        _fetch,
        form_url,
        allowed=_allowed_form_url,
        limit_bytes=FORM_LIMIT_BYTES,
        accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
    )
    return _extract_snapshot(form, campaign_url, form_url, season, now)


def valid_dinamizacion_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    expected = {
        "observed_at",
        "season",
        "campaign_url",
        "form_url",
        "registration_start",
        "registration_end",
        "registration_until_full",
        "resident_priority",
        "groups",
    }
    if set(value) != expected:
        return False
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        registration_start = date.fromisoformat(value["registration_start"])
        registration_end = date.fromisoformat(value["registration_end"])
    except (KeyError, TypeError, ValueError):
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    if registration_end < registration_start:
        return False
    if (
        not isinstance(value.get("season"), str)
        or re.fullmatch(r"20\d{2}/\d{2}", value["season"]) is None
        or not _allowed_ayto_url(value.get("campaign_url", ""))
        or not _allowed_form_url(value.get("form_url", ""))
        or value.get("registration_until_full") is not True
        or value.get("resident_priority") is not True
    ):
        return False
    groups = value.get("groups")
    if not isinstance(groups, list) or not groups:
        return False
    seen = set()
    allowed = {key for key, _ in _GROUPS}
    for group in groups:
        if not isinstance(group, dict) or set(group) != {
            "key", "schedules", "start_date", "end_date"
        }:
            return False
        key = group.get("key")
        schedules = group.get("schedules")
        if (
            key not in allowed
            or key in seen
            or not isinstance(schedules, list)
            or not schedules
            or any(not isinstance(item, str) or not item for item in schedules)
        ):
            return False
        seen.add(key)
        for field in ("start_date", "end_date"):
            raw = group.get(field)
            if raw is not None:
                try:
                    date.fromisoformat(raw)
                except (TypeError, ValueError):
                    return False
        if group.get("end_date") is not None and group.get("start_date") is None:
            return False
        if (
            group.get("start_date") is not None
            and group.get("end_date") is not None
            and date.fromisoformat(group["end_date"])
            < date.fromisoformat(group["start_date"])
        ):
            return False
    return True
