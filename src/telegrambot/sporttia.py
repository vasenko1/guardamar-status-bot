"""One bounded Sporttia read for municipal recurring sports.

The public centre page is a server-rendered registration surface. One daily
read supplies the current published course rows; unexpired last-good rows are
retained when registration closes so an activity does not disappear merely
because it is no longer offered for new enrolment.
"""

import asyncio
import re
import unicodedata
import urllib.parse
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Optional, Tuple

from ._transport import BoundedFetchError, fetch_bounded

SPORTTIA_CENTER_URL = (
    "https://sporttia.com/centros/ayuntamiento-guardamar-del-segura"
)
SPORTTIA_CENTER_ID = "1509"
SPORTTIA_ACTIVITY_KEYS = (
    "rhythmic_gymnastics",
    "judo",
    "multisport",
    "inclusive_multisport",
    "senior_gymnastics",
    "women_gymnastics",
    "deporte_plus",
    "psychomotricity",
)
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "guardamar-status-bot/1.0",
}
_SPANISH_MONTHS = {
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "febrero": 2,
    "mar": 3,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "jul": 7,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "septiembre": 9,
    "oct": 10,
    "octubre": 10,
    "nov": 11,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}
_DAY_TRANSLATIONS = (
    ("lunes", "Пн"),
    ("martes", "Вт"),
    ("miércoles", "Ср"),
    ("miercoles", "Ср"),
    ("jueves", "Чт"),
    ("viernes", "Пт"),
    ("sábado", "Сб"),
    ("sabado", "Сб"),
    ("domingo", "Вс"),
)


class SporttiaSourceError(RuntimeError):
    """A Sporttia observation that is unsafe to publish."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = code


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _allowed_sporttia_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "sporttia.com"
        and port in {None, 443}
        and parsed.path
        == "/centros/ayuntamiento-guardamar-del-segura"
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


def _allowed_activity_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "play.sporttia.com"
        and port in {None, 443}
        and re.fullmatch(r"/activities/[1-9][0-9]*", parsed.path)
        is not None
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


class _SporttiaOfferParser(HTMLParser):
    """Collect one activity row from each centre offer tbody."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen_offer_container = False
        self.seen_center = False
        self.invalid = False
        self.rows = []
        self._row = None
        self._anchor_parts = None
        self._paragraph_parts = None
        self._cell_parts = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if "data-offer-blocks" in attributes:
            self.seen_offer_container = True
            center_ids = str(attributes.get("data-center-ids") or "")
            if SPORTTIA_CENTER_ID in re.split(r"[\s,]+", center_ids):
                self.seen_center = True

        if tag.casefold() == "tbody":
            identifier = attributes.get("id")
            if (
                isinstance(identifier, str)
                and identifier.startswith(
                    f"oferta-{SPORTTIA_CENTER_ID}-"
                )
            ):
                if self._row is not None:
                    self.invalid = True
                self._row = {
                    "activity_url": None,
                    "title": None,
                    "paragraphs": [],
                    "cells": [],
                }
                self._anchor_parts = None
                self._paragraph_parts = None
                self._cell_parts = None
                return

        if self._row is None:
            return

        lowered = tag.casefold()
        if lowered == "a":
            href = attributes.get("href")
            if isinstance(href, str) and _allowed_activity_url(href):
                if self._row["activity_url"] is not None:
                    self.invalid = True
                else:
                    self._row["activity_url"] = href
                    self._anchor_parts = []
        elif lowered == "p":
            if self._paragraph_parts is not None:
                self.invalid = True
            self._paragraph_parts = []
        elif lowered == "td":
            if self._cell_parts is not None:
                self.invalid = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._row is None:
            return
        if self._anchor_parts is not None:
            self._anchor_parts.append(data)
        if self._paragraph_parts is not None:
            self._paragraph_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._row is None:
            return
        lowered = tag.casefold()
        if lowered == "a" and self._anchor_parts is not None:
            self._row["title"] = _normalized_text(
                "".join(self._anchor_parts)
            )
            self._anchor_parts = None
        elif lowered == "p" and self._paragraph_parts is not None:
            value = _normalized_text("".join(self._paragraph_parts))
            if value:
                self._row["paragraphs"].append(value)
            self._paragraph_parts = None
        elif lowered == "td" and self._cell_parts is not None:
            self._row["cells"].append(
                _normalized_text("".join(self._cell_parts))
            )
            self._cell_parts = None
        elif lowered == "tbody":
            if (
                isinstance(self._row.get("activity_url"), str)
                and isinstance(self._row.get("title"), str)
                and len(self._row["cells"]) >= 3
            ):
                self.rows.append(self._row)
            else:
                self.invalid = True
            self._row = None
            self._anchor_parts = None
            self._paragraph_parts = None
            self._cell_parts = None


def _classify_activity(title: str) -> Optional[str]:
    folded = _fold(title)
    if re.search(r"\bdeporte\s*\+", folded):
        return "deporte_plus"
    if "psicomotricidad" in folded:
        return "psychomotricity"
    if "multideporte inclusivo" in folded:
        return "inclusive_multisport"
    if "gimnasia ritmica" in folded:
        return "rhythmic_gymnastics"
    if re.search(r"\bjudo\b", folded):
        return "judo"
    if "gimnasia mayores" in folded:
        return "senior_gymnastics"
    if "gimnasia" in folded and "asociacion mujeres" in folded:
        return "women_gymnastics"
    if re.search(r"\bmultideporte\b", folded):
        return "multisport"
    return None


def _group_order(title: str) -> int:
    folded = _fold(title)
    for marker, value in (
        ("primer turno", 1),
        ("segundo turno", 2),
        ("tercer turno", 3),
        ("cuarto turno", 4),
        ("turno unico", 1),
    ):
        if marker in folded:
            return value
    raise SporttiaSourceError(
        "Sporttia target activity has no recognized group order",
        code="SCHEMA",
    )


def _activity_group_order(key: str, title: str) -> int:
    """Allow only DEPORTE+ to represent its one visible unnumbered group."""

    if key == "deporte_plus":
        return 1
    return _group_order(title)


def _audience(title: str) -> Optional[str]:
    match = re.search(
        r"Nacidos(?:\s+entre|\s+en)?\s+(\d{4})\s*(?:-|y)\s*(\d{4})",
        title,
        flags=re.I,
    )
    if match:
        return f"{match.group(1)}–{match.group(2)} г.р."
    match = re.search(r"Mayores\s+de\s+(\d+)\s+años", title, flags=re.I)
    if match:
        return f"от {match.group(1)} лет"
    return None


def _parse_spanish_date_range(value: str) -> Tuple[date, date]:
    match = re.search(
        r"(\d{1,2})\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+(\d{4})"
        r"\s*[–-]\s*"
        r"(\d{1,2})\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+(\d{4})",
        value,
    )
    if match is None:
        raise SporttiaSourceError(
            "Sporttia target activity has an invalid season",
            code="SCHEMA",
        )
    first_month = _SPANISH_MONTHS.get(_fold(match.group(2)))
    second_month = _SPANISH_MONTHS.get(_fold(match.group(5)))
    if first_month is None or second_month is None:
        raise SporttiaSourceError(
            "Sporttia target activity has an unknown month",
            code="SCHEMA",
        )
    try:
        start = date(int(match.group(3)), first_month, int(match.group(1)))
        end = date(int(match.group(6)), second_month, int(match.group(4)))
    except ValueError as exc:
        raise SporttiaSourceError(
            "Sporttia target activity has an invalid season date",
            code="SCHEMA",
        ) from exc
    if end < start:
        raise SporttiaSourceError(
            "Sporttia target activity season is reversed",
            code="SCHEMA",
        )
    return start, end


def _parse_registration(paragraphs) -> tuple[list[dict], bool]:
    intervals = []
    until_full = False
    for paragraph in paragraphs:
        folded = _fold(paragraph)
        if not folded.startswith("nuevas inscripciones"):
            continue
        until_full = until_full or "hasta completar" in folded
        for match in re.finditer(
            r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s*al\s*"
            r"(\d{1,2})/(\d{1,2})/(\d{2,4})",
            folded,
        ):
            first_year = int(match.group(3))
            second_year = int(match.group(6))
            if first_year < 100:
                first_year += 2000
            if second_year < 100:
                second_year += 2000
            try:
                start = date(
                    first_year,
                    int(match.group(2)),
                    int(match.group(1)),
                )
                end = date(
                    second_year,
                    int(match.group(5)),
                    int(match.group(4)),
                )
            except ValueError as exc:
                raise SporttiaSourceError(
                    "Sporttia registration date is invalid",
                    code="SCHEMA",
                ) from exc
            if end < start:
                raise SporttiaSourceError(
                    "Sporttia registration interval is reversed",
                    code="SCHEMA",
                )
            intervals.append(
                {"start": start.isoformat(), "end": end.isoformat()}
            )
    if not intervals:
        raise SporttiaSourceError(
            "Sporttia target activity has no explicit registration window",
            code="SCHEMA",
        )
    return intervals, until_full


def _translate_schedule(value: str) -> str:
    result = _normalized_text(value).rstrip(".")
    result = re.sub(r"^Horarios?:\s*", "", result, flags=re.I)
    for spanish, russian in _DAY_TRANSLATIONS:
        result = re.sub(
            rf"\b{spanish}\b",
            russian,
            result,
            flags=re.I,
        )
    result = re.sub(r"\by\b", "и", result, flags=re.I)
    result = re.sub(r"\s+de\s+(?=\d)", " · ", result, flags=re.I)
    result = re.sub(r"(?<=\d)\s+a\s+(?=\d)", "–", result, flags=re.I)
    result = re.sub(r"\s+horas?\b", "", result, flags=re.I)
    result = re.sub(
        r"(?<![:\d])(\d{1,2})(?=\s*–)",
        lambda match: f"{int(match.group(1)):02d}:00",
        result,
    )
    result = re.sub(
        r"(?<=–)(\d{1,2})(?![:\d])",
        lambda match: f"{int(match.group(1)):02d}:00",
        result,
    )
    return _normalized_text(result)


def _extract_schedule(paragraphs) -> str:
    for paragraph in paragraphs:
        folded = _fold(paragraph)
        if not any(_fold(day) in folded for day, _ in _DAY_TRANSLATIONS):
            continue
        if re.search(r"\d{1,2}(?::\d{2})?\s+a\s+\d{1,2}", folded):
            return _translate_schedule(paragraph)
    raise SporttiaSourceError(
        "Sporttia target activity has no schedule",
        code="SCHEMA",
    )


def _extract_venue(paragraphs) -> str:
    for paragraph in paragraphs:
        match = re.match(r"Clases\s+en\s+(.+?)\.?$", paragraph, flags=re.I)
        if match:
            venue = _normalized_text(match.group(1)).rstrip(".")
            if venue and len(venue) <= 200:
                return venue
    raise SporttiaSourceError(
        "Sporttia target activity has no venue",
        code="SCHEMA",
    )


def _normalize_activity_row(row: dict) -> Optional[dict]:
    title = row["title"]
    key = _classify_activity(title)
    if key is None:
        return None
    activity_url = row["activity_url"]
    parsed = urllib.parse.urlsplit(activity_url)
    source_id = int(parsed.path.rsplit("/", 1)[1])
    season_start, season_end = _parse_spanish_date_range(row["cells"][1])
    registrations, until_full = _parse_registration(row["paragraphs"])
    schedule = _extract_schedule(row["paragraphs"])
    venue = _extract_venue(row["paragraphs"])
    details = _fold(" ".join(row["paragraphs"]))
    title_folded = _fold(title)
    return {
        "source_id": source_id,
        "key": key,
        "activity_url": activity_url,
        "season_start": season_start.isoformat(),
        "season_end": season_end.isoformat(),
        "group_order": _activity_group_order(key, title),
        "audience": _audience(title),
        "schedule": schedule,
        "venue": venue,
        "registrations": registrations,
        "registration_until_full": until_full,
        "medical_certificate": "certificado medico" in details,
        "group_may_change": (
            "variaciones" in details
            and ("grupos" in details or "turnos" in details)
        ),
        "racket_sports": "deportes de raqueta" in details,
        "independent": "alumno con autonomia" in title_folded,
        "requires_companion": (
            "alumno sin autonomia" in title_folded
            or "acompanante adulto" in details
        ),
        "women_membership": "cuota de socia" in details,
    }


def _extract_sporttia_catalog(payload: bytes, now: datetime) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Sporttia observation time must be timezone-aware")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SporttiaSourceError(
            "Sporttia HTML is invalid",
            code="HTML",
        ) from exc
    parser = _SporttiaOfferParser()
    parser.feed(text)
    parser.close()
    if (
        parser.invalid
        or not parser.seen_offer_container
        or not parser.seen_center
        or not 1 <= len(parser.rows) <= 128
    ):
        raise SporttiaSourceError(
            "Sporttia offer structure is invalid",
            code="SCHEMA",
        )
    activities = []
    seen_source_ids = set()
    for row in parser.rows:
        normalized = _normalize_activity_row(row)
        if normalized is None:
            continue
        if normalized["source_id"] in seen_source_ids:
            raise SporttiaSourceError(
                "Sporttia target activity is duplicated",
                code="SCHEMA",
            )
        seen_source_ids.add(normalized["source_id"])
        activities.append(normalized)
    activities.sort(
        key=lambda item: (
            item["key"],
            item["season_start"],
            item["group_order"],
            item["source_id"],
        )
    )
    return {
        "observed_at": now.isoformat(),
        "activities": activities,
    }


async def fetch_sporttia_catalog(now: datetime) -> dict:
    """Perform exactly one bounded, non-redirecting Sporttia GET."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Sporttia observation time must be timezone-aware")
    try:
        payload, _, _ = await asyncio.to_thread(
            fetch_bounded,
            SPORTTIA_CENTER_URL,
            is_allowed_url=_allowed_sporttia_url,
            limit_bytes=256 * 1024,
            timeout_seconds=15.0,
            headers=_REQUEST_HEADERS,
            accepted_types=_HTML_TYPES,
            follow_redirects=False,
        )
    except BoundedFetchError as exc:
        raise SporttiaSourceError(
            "Sporttia request failed",
            code=exc.code,
        ) from exc
    return _extract_sporttia_catalog(payload, now)


def _valid_registration(value) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        start = date.fromisoformat(value.get("start", ""))
        end = date.fromisoformat(value.get("end", ""))
    except (TypeError, ValueError):
        return False
    return end >= start


def valid_sporttia_snapshot(value) -> bool:
    if not isinstance(value, dict):
        return False
    observed_at = value.get("observed_at")
    activities = value.get("activities")
    if not isinstance(observed_at, str) or not isinstance(activities, list):
        return False
    if len(activities) > 128:
        return False
    try:
        parsed_observed = datetime.fromisoformat(observed_at)
    except ValueError:
        return False
    if parsed_observed.tzinfo is None or parsed_observed.utcoffset() is None:
        return False
    seen = set()
    for item in activities:
        if not isinstance(item, dict):
            return False
        source_id = item.get("source_id")
        if (
            not isinstance(source_id, int)
            or isinstance(source_id, bool)
            or source_id <= 0
            or source_id in seen
        ):
            return False
        seen.add(source_id)
        if item.get("key") not in SPORTTIA_ACTIVITY_KEYS:
            return False
        if not isinstance(item.get("activity_url"), str) or not _allowed_activity_url(
            item["activity_url"]
        ):
            return False
        try:
            start = date.fromisoformat(item.get("season_start", ""))
            end = date.fromisoformat(item.get("season_end", ""))
        except (TypeError, ValueError):
            return False
        if end < start:
            return False
        order = item.get("group_order")
        if not isinstance(order, int) or isinstance(order, bool) or not 1 <= order <= 20:
            return False
        audience = item.get("audience")
        if audience is not None and (
            not isinstance(audience, str) or not audience or len(audience) > 100
        ):
            return False
        for field in ("schedule", "venue"):
            candidate = item.get(field)
            if not isinstance(candidate, str) or not candidate or len(candidate) > 200:
                return False
        registrations = item.get("registrations")
        if (
            not isinstance(registrations, list)
            or len(registrations) > 8
            or not all(_valid_registration(entry) for entry in registrations)
        ):
            return False
        for flag in (
            "registration_until_full",
            "medical_certificate",
            "group_may_change",
            "racket_sports",
            "independent",
            "requires_companion",
            "women_membership",
        ):
            if not isinstance(item.get(flag), bool):
                return False
    return True


def merge_sporttia_catalog(
    previous: Optional[dict],
    current: dict,
    local_day: date,
) -> dict:
    """Merge one registration-surface observation with unexpired last-good rows."""

    if not valid_sporttia_snapshot(current):
        raise SporttiaSourceError(
            "Sporttia snapshot is invalid",
            code="SCHEMA",
        )
    retained = {}
    if previous is not None:
        if not valid_sporttia_snapshot(previous):
            raise SporttiaSourceError(
                "Previous Sporttia snapshot is invalid",
                code="SCHEMA",
            )
        for item in previous["activities"]:
            if date.fromisoformat(item["season_end"]) >= local_day:
                retained[item["source_id"]] = dict(item)
    for item in current["activities"]:
        if date.fromisoformat(item["season_end"]) >= local_day:
            retained[item["source_id"]] = dict(item)
    activities = sorted(
        retained.values(),
        key=lambda item: (
            item["key"],
            item["season_start"],
            item["group_order"],
            item["source_id"],
        ),
    )
    return {
        "observed_at": current["observed_at"],
        "observed_source_ids": sorted(
            item["source_id"] for item in current["activities"]
        ),
        "activities": activities,
    }


def select_sport_groups(
    catalog: dict,
    key: str,
    local_day: date,
) -> Tuple[dict, ...]:
    """Select the current season, or otherwise the nearest future season."""

    if key not in SPORTTIA_ACTIVITY_KEYS or not valid_sporttia_snapshot(catalog):
        return ()
    candidates = [
        item
        for item in catalog["activities"]
        if item["key"] == key
        and date.fromisoformat(item["season_end"]) >= local_day
    ]
    if not candidates:
        return ()
    seasons = sorted(
        {
            (
                date.fromisoformat(item["season_start"]),
                date.fromisoformat(item["season_end"]),
            )
            for item in candidates
        }
    )
    active = [season for season in seasons if season[0] <= local_day <= season[1]]
    if active:
        selected = max(active, key=lambda season: season[0])
    else:
        future = [season for season in seasons if season[0] > local_day]
        if not future:
            return ()
        selected = min(future, key=lambda season: season[0])
    result = [
        item
        for item in candidates
        if date.fromisoformat(item["season_start"]) == selected[0]
        and date.fromisoformat(item["season_end"]) == selected[1]
    ]
    result.sort(key=lambda item: (item["group_order"], item["source_id"]))
    return tuple(result)
