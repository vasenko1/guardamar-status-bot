"""First-party Guardamar supermarket schedule adapters.

The adapters keep retailer-specific contracts here and return only small,
normalized exact-date observations.  They never infer closures from the
municipal holiday calendar and never persist raw retailer responses.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Dict, FrozenSet, Optional, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded


GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
REQUEST_TIMEOUT_SECONDS = 15
MAX_FUTURE_DAYS = 90

MERCADONA_LOCATOR_URL = "https://info.mercadona.es/es/supermercados"
MERCADONA_STORE_ID = 283185312286
# Reviewed against the exact Guardamar first-party store schedule on 2026-10-07.
MERCADONA_REGULAR_OPEN_WEEKDAYS = frozenset(range(6))
MERCADONA_DATA_PATH = "/pro-bucket-wcorp-files/json/data.js"
DIA_DETAIL_URL = (
    "https://www.dia.es/tiendas/buscadorTiendas.html"
    "?action=buscarInformacionTienda&id=1003631"
)
DIA_STORE_CODE = 36111
MASYMAS_LOCATOR_URL = "https://www.masymas.com/localizadordetiendas/localizador.php"

STORE_ORDER = ("mercadona_guardamar", "masymas_guardamar", "dia_guardamar")
STORE_NAMES = {
    "mercadona_guardamar": "Mercadona",
    "masymas_guardamar": "masymas",
    "dia_guardamar": "DIA",
}
STORE_ADDRESSES = {
    "mercadona_guardamar": "Avinguda del Mediterrani, 14",
    "masymas_guardamar": "Av. del Puerto, 18–20",
    "dia_guardamar": "C/ La Redonda, 40",
}


class SupermarketSourceError(RuntimeError):
    """One retailer source cannot safely support public schedule claims."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


@dataclass(frozen=True)
class StoreDayStatus:
    day: date
    is_open: bool
    intervals: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StoreScheduleObservation:
    store_key: str
    store_name: str
    address: str
    observed_at: datetime
    regular_open_weekdays: FrozenSet[int]
    days: Tuple[StoreDayStatus, ...]

    def status_on(self, target_day: date) -> Optional[StoreDayStatus]:
        for status in self.days:
            if status.day == target_day:
                return status
        return None

    @property
    def closures(self) -> FrozenSet[date]:
        return frozenset(
            status.day
            for status in self.days
            if not status.is_open
            and status.day.weekday() in self.regular_open_weekdays
        )

    @property
    def explicit_open_days(self) -> FrozenSet[date]:
        return frozenset(status.day for status in self.days if status.is_open)




def _local_day(now: datetime) -> date:
    if now.tzinfo is None:
        raise SupermarketSourceError("supermarket observation time is naive", code="TIME")
    return now.astimezone(GUARDAMAR_TIMEZONE).date()


def _within_window(target: date, today: date) -> bool:
    return today <= target <= today + timedelta(days=MAX_FUTURE_DAYS)


def _normalize_interval(value: str) -> str:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", value)
    if match is None:
        raise SupermarketSourceError("retailer hours are outside the reviewed format")
    start_hour, start_minute, end_hour, end_minute = (int(part) for part in match.groups())
    if (
        start_hour > 23
        or end_hour > 23
        or start_minute > 59
        or end_minute > 59
        or (start_hour, start_minute) >= (end_hour, end_minute)
    ):
        raise SupermarketSourceError("retailer hours are invalid")
    return f"{start_hour:02d}:{start_minute:02d}–{end_hour:02d}:{end_minute:02d}"


def _compact_time(value: str) -> str:
    if not re.fullmatch(r"\d{4}", value):
        raise SupermarketSourceError("Mercadona time token is invalid")
    hour = int(value[:2])
    minute = int(value[2:])
    if hour > 23 or minute > 59:
        raise SupermarketSourceError("Mercadona time token is invalid")
    return f"{hour:02d}:{minute:02d}"


def _merge_status(target: Dict[date, StoreDayStatus], candidate: StoreDayStatus) -> None:
    previous = target.get(candidate.day)
    if previous is not None and previous.is_open != candidate.is_open:
        raise SupermarketSourceError("retailer exact-date schedule is internally inconsistent")
    if previous is None or (candidate.is_open and candidate.intervals):
        target[candidate.day] = candidate


def _decode_utf8(payload: bytes, label: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupermarketSourceError(f"{label} response is not UTF-8") from exc


def _parse_dmy(value: str) -> date:
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise SupermarketSourceError("retailer date is outside the reviewed format")


def parse_mercadona_data(payload: bytes, now: datetime) -> StoreScheduleObservation:
    """Normalize the reviewed Mercadona ``data.js`` contract for Guardamar."""

    text = _decode_utf8(payload, "Mercadona")
    marker = re.search(r"\bvar\s+dataJson\s*=\s*", text)
    if marker is None:
        raise SupermarketSourceError("Mercadona dataJson marker is missing", code="CONTRACT")
    try:
        root, _ = json.JSONDecoder().raw_decode(text[marker.end():])
    except json.JSONDecodeError as exc:
        raise SupermarketSourceError("Mercadona dataJson is invalid JSON", code="CONTRACT") from exc
    if not isinstance(root, dict):
        raise SupermarketSourceError("Mercadona dataJson is not an object", code="CONTRACT")

    today = _local_day(now)
    try:
        source_day = datetime.strptime(root["fechaCreacion"], "%d-%m-%Y").date()
    except (KeyError, TypeError, ValueError) as exc:
        raise SupermarketSourceError("Mercadona creation date is invalid", code="CONTRACT") from exc
    if source_day != today:
        raise SupermarketSourceError("Mercadona dataset is stale", code="STALE")

    stores = root.get("tiendasFull")
    if not isinstance(stores, list):
        raise SupermarketSourceError("Mercadona store list is missing", code="CONTRACT")
    matches = [row for row in stores if isinstance(row, dict) and row.get("id") == MERCADONA_STORE_ID]
    if len(matches) != 1:
        raise SupermarketSourceError("Mercadona Guardamar store identity is not unique", code="IDENTITY")
    store = matches[0]
    if (
        str(store.get("cp")) != "03140"
        or str(store.get("lc", "")).casefold() != "guardamar del segura"
        or "MEDITERR" not in str(store.get("dr", "")).upper()
    ):
        raise SupermarketSourceError("Mercadona Guardamar identity markers changed", code="IDENTITY")

    openings = str(store.get("in", "")).split("#")
    closings = str(store.get("fi", "")).split("#")
    if len(openings) != 7 or len(closings) != 7:
        raise SupermarketSourceError("Mercadona rolling schedule must contain seven days", code="CONTRACT")

    statuses: Dict[date, StoreDayStatus] = {}
    for offset, (opening, closing) in enumerate(zip(openings, closings)):
        target_day = source_day + timedelta(days=offset)
        if opening == "C" and closing == "C":
            _merge_status(statuses, StoreDayStatus(target_day, False))
            continue
        if opening == "C" or closing == "C":
            raise SupermarketSourceError("Mercadona rolling schedule is inconsistent", code="CONTRACT")
        interval = f"{_compact_time(opening)}–{_compact_time(closing)}"
        _merge_status(statuses, StoreDayStatus(target_day, True, (interval,)))

    raw_specials = store.get("fs")
    if not isinstance(raw_specials, str):
        raise SupermarketSourceError("Mercadona special-day field is missing", code="CONTRACT")
    if raw_specials:
        for token in raw_specials.split("#"):
            match = re.fullmatch(r"(\d{2}/\d{2}/\d{2})-(C|FA|FM|CR)", token)
            if match is None:
                raise SupermarketSourceError("Mercadona special-day token is invalid", code="CONTRACT")
            try:
                target_day = datetime.strptime(match.group(1), "%d/%m/%y").date()
            except ValueError as exc:
                raise SupermarketSourceError("Mercadona special-day date is invalid", code="CONTRACT") from exc
            if not _within_window(target_day, today):
                continue
            code = match.group(2)
            _merge_status(statuses, StoreDayStatus(target_day, code in {"FA", "FM"}))

    return StoreScheduleObservation(
        store_key="mercadona_guardamar",
        store_name=STORE_NAMES["mercadona_guardamar"],
        address=STORE_ADDRESSES["mercadona_guardamar"],
        observed_at=now.astimezone(GUARDAMAR_TIMEZONE),
        regular_open_weekdays=MERCADONA_REGULAR_OPEN_WEEKDAYS,
        days=tuple(
            statuses[day]
            for day in sorted(statuses)
            if _within_window(day, today)
        ),
    )


def parse_dia_detail(payload: bytes, now: datetime) -> StoreScheduleObservation:
    """Normalize DIA's exact Guardamar detail JSON."""

    try:
        root = json.loads(_decode_utf8(payload, "DIA"))
    except json.JSONDecodeError as exc:
        raise SupermarketSourceError("DIA detail is invalid JSON", code="CONTRACT") from exc
    if not isinstance(root, dict):
        raise SupermarketSourceError("DIA detail is not an object", code="CONTRACT")
    serialized = json.dumps(root, ensure_ascii=False).casefold()
    if (
        root.get("tiendaCodigo") != DIA_STORE_CODE
        or str(root.get("codigoPostal")) != "03140"
        or str(root.get("localidad", "")).casefold() != "guardamar del segura"
        or "redonda" not in serialized
    ):
        raise SupermarketSourceError("DIA Guardamar identity markers changed", code="IDENTITY")

    weekly = root.get("horariosTienda")
    if not isinstance(weekly, dict):
        raise SupermarketSourceError("DIA weekly schedule is missing", code="CONTRACT")
    regular = set()
    for raw_day, hours in weekly.items():
        try:
            iso_day = int(raw_day)
        except (TypeError, ValueError) as exc:
            raise SupermarketSourceError("DIA weekday key is invalid", code="CONTRACT") from exc
        if iso_day not in range(1, 8) or not isinstance(hours, str):
            raise SupermarketSourceError("DIA weekly schedule is invalid", code="CONTRACT")
        if hours.strip():
            _normalize_interval(hours)
            regular.add(iso_day - 1)
    if not set(range(6)).issubset(regular):
        raise SupermarketSourceError("DIA reviewed Monday-Saturday baseline changed", code="CONTRACT")

    holidays = root.get("festivosTienda")
    holiday_hours = root.get("horariosAperturaFestivo")
    if (
        not isinstance(holidays, list)
        or not isinstance(holiday_hours, list)
        or len(holidays) != len(holiday_hours)
        or len(holidays) > 64
    ):
        raise SupermarketSourceError("DIA holiday arrays are invalid", code="CONTRACT")

    today = _local_day(now)
    statuses: Dict[date, StoreDayStatus] = {}
    for raw_day, raw_hours in zip(holidays, holiday_hours):
        if not isinstance(raw_day, str) or not isinstance(raw_hours, str):
            raise SupermarketSourceError("DIA holiday entry is invalid", code="CONTRACT")
        target_day = _parse_dmy(raw_day)
        if not _within_window(target_day, today):
            continue
        if raw_hours.strip():
            _merge_status(
                statuses,
                StoreDayStatus(target_day, True, (_normalize_interval(raw_hours),)),
            )
        else:
            _merge_status(statuses, StoreDayStatus(target_day, False))

    temp_start = root.get("inicioCierreTemp")
    temp_end = root.get("finCierreTemp")
    if temp_start or temp_end:
        if not isinstance(temp_start, str) or not isinstance(temp_end, str):
            raise SupermarketSourceError("DIA temporary-closure range is incomplete", code="CONTRACT")
        first = _parse_dmy(temp_start)
        last = _parse_dmy(temp_end)
        if first > last or last - first > timedelta(days=MAX_FUTURE_DAYS):
            raise SupermarketSourceError("DIA temporary-closure range is invalid", code="CONTRACT")
        cursor = max(first, today)
        horizon = min(last, today + timedelta(days=MAX_FUTURE_DAYS))
        while cursor <= horizon:
            if cursor.weekday() in regular:
                _merge_status(statuses, StoreDayStatus(cursor, False))
            cursor += timedelta(days=1)

    return StoreScheduleObservation(
        store_key="dia_guardamar",
        store_name=STORE_NAMES["dia_guardamar"],
        address=STORE_ADDRESSES["dia_guardamar"],
        observed_at=now.astimezone(GUARDAMAR_TIMEZONE),
        # Sunday openings can be seasonal in Guardamar. One exact Sunday difference
        # does not prove a regime boundary, so v1 only automates the reviewed Mon-Sat baseline.
        regular_open_weekdays=frozenset(range(6)),
        days=tuple(statuses[day] for day in sorted(statuses)),
    )


class _TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.row_stack = []
        self.rows = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag.casefold() == "tr":
            # The legacy masymas page nests tables inside table rows. Keep
            # each <tr> independent instead of collapsing nested rows into
            # one parent buffer.
            self.row_stack.append([])

    def handle_endtag(self, tag) -> None:
        if tag.casefold() != "tr" or not self.row_stack:
            return
        parts = self.row_stack.pop()
        value = " ".join(" ".join(parts).split())
        if value:
            self.rows.append(value)

    def handle_data(self, data) -> None:
        if self.row_stack:
            value = " ".join(data.split())
            if value:
                self.row_stack[-1].append(value)


def parse_masymas_locator(payload: bytes, now: datetime) -> StoreScheduleObservation:
    """Normalize the exact Guardamar row returned by the official form."""

    parser = _TableRows()
    try:
        parser.feed(_decode_utf8(payload, "masymas"))
        parser.close()
    except Exception as exc:
        raise SupermarketSourceError("masymas locator HTML is invalid", code="CONTRACT") from exc
    matches = []
    for row in parser.rows:
        folded = row.casefold()
        if (
            "alicante" in folded
            and "guardamar del segura" in folded
            and "avda. puerto, 18 y 20" in folded
        ):
            matches.append(row)
    if len(matches) != 1:
        raise SupermarketSourceError("masymas Guardamar row is not unique", code="IDENTITY")
    row = matches[0]

    weekly = re.search(
        r"Lun\s*-\s*Sab\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})",
        row,
        flags=re.IGNORECASE,
    )
    if weekly is None:
        raise SupermarketSourceError("masymas reviewed Monday-Saturday schedule changed", code="CONTRACT")
    _normalize_interval(f"{weekly.group(1)}-{weekly.group(2)}")

    today = _local_day(now)
    statuses: Dict[date, StoreDayStatus] = {}
    for match in re.finditer(r"Cierra\s+el\s+(\d{2}/\d{2}/\d{4})", row, flags=re.IGNORECASE):
        target_day = _parse_dmy(match.group(1))
        if _within_window(target_day, today):
            _merge_status(statuses, StoreDayStatus(target_day, False))
    for match in re.finditer(
        r"Abre\s+el\s+(\d{2}/\d{2}/\d{4})\s+"
        r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})",
        row,
        flags=re.IGNORECASE,
    ):
        target_day = _parse_dmy(match.group(1))
        if _within_window(target_day, today):
            _merge_status(
                statuses,
                StoreDayStatus(
                    target_day,
                    True,
                    (_normalize_interval(f"{match.group(2)}-{match.group(3)}"),),
                ),
            )

    return StoreScheduleObservation(
        store_key="masymas_guardamar",
        store_name=STORE_NAMES["masymas_guardamar"],
        address=STORE_ADDRESSES["masymas_guardamar"],
        observed_at=now.astimezone(GUARDAMAR_TIMEZONE),
        regular_open_weekdays=frozenset(range(6)),
        days=tuple(statuses[day] for day in sorted(statuses)),
    )


def _url_parts(url: str):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return None, None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
    ):
        return None, None
    return parsed, urllib.parse.parse_qs(parsed.query, keep_blank_values=True)


def _allow_mercadona_locator(url: str) -> bool:
    parsed, query = _url_parts(url)
    return bool(
        parsed
        and parsed.hostname == "info.mercadona.es"
        and parsed.path == "/es/supermercados"
        and query == {}
    )


def _allow_mercadona_data(url: str) -> bool:
    parsed, query = _url_parts(url)
    return bool(
        parsed
        and parsed.hostname == "storage.googleapis.com"
        and parsed.path == MERCADONA_DATA_PATH
        and set(query) == {"timestamp"}
        and len(query["timestamp"]) == 1
        and query["timestamp"][0].isdigit()
    )


def _allow_dia(url: str) -> bool:
    parsed, query = _url_parts(url)
    return bool(
        parsed
        and parsed.hostname == "www.dia.es"
        and parsed.path == "/tiendas/buscadorTiendas.html"
        and query == {"action": ["buscarInformacionTienda"], "id": ["1003631"]}
    )


def _allow_masymas(url: str) -> bool:
    parsed, query = _url_parts(url)
    return bool(
        parsed
        and parsed.hostname == "www.masymas.com"
        and parsed.path == "/localizadordetiendas/localizador.php"
        and query == {}
    )


def _fetch(
    url: str,
    *,
    policy,
    limit: int,
    types: FrozenSet[str],
    accept: str,
    method: str = "GET",
    data: Optional[bytes] = None,
    navigation_fallback: bool = False,
) -> bytes:
    headers = {
        "Accept": accept,
        "Accept-Language": "es-ES,es;q=0.9",
        "User-Agent": "GuardamarMorningDigest/0.14",
    }
    if method == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    def request(active_headers):
        return fetch_bounded(
            url,
            is_allowed_url=policy,
            accepted_types=types,
            limit_bytes=limit,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers=active_headers,
            method=method,
            data=data,
        )

    try:
        payload, _, _ = request(headers)
    except BoundedFetchError as exc:
        if navigation_fallback and getattr(exc, "status", None) in {403, 406}:
            fallback = dict(headers)
            fallback.update({
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 14; Mobile) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Mobile Safari/537.36"
                ),
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
            })
            try:
                payload, _, _ = request(fallback)
            except BoundedFetchError as fallback_exc:
                raise SupermarketSourceError(
                    "retailer source is unavailable", code=fallback_exc.code
                ) from fallback_exc
        else:
            raise SupermarketSourceError("retailer source is unavailable", code=exc.code) from exc
    return payload


def _fetch_mercadona_sync(now: datetime) -> StoreScheduleObservation:
    page = _fetch(
        MERCADONA_LOCATOR_URL,
        policy=_allow_mercadona_locator,
        limit=512 * 1024,
        types=frozenset({"text/html", "application/xhtml+xml"}),
        accept="text/html,application/xhtml+xml",
        navigation_fallback=True,
    )
    text = _decode_utf8(page, "Mercadona locator").replace("\\/", "/")
    urls = sorted(set(re.findall(
        r"https://storage\.googleapis\.com/pro-bucket-wcorp-files/json/data\.js\?timestamp=\d+",
        text,
    )))
    if len(urls) != 1:
        raise SupermarketSourceError("Mercadona data.js URL is not unique", code="CONTRACT")
    data = _fetch(
        urls[0],
        policy=_allow_mercadona_data,
        limit=1024 * 1024,
        types=frozenset({"text/javascript", "application/javascript", "application/x-javascript", "text/plain"}),
        accept="application/javascript,text/javascript,*/*;q=0.1",
    )
    return parse_mercadona_data(data, now)


def _fetch_dia_sync(now: datetime) -> StoreScheduleObservation:
    payload = _fetch(
        DIA_DETAIL_URL,
        policy=_allow_dia,
        limit=64 * 1024,
        types=frozenset({"application/json", "text/json", "text/plain"}),
        accept="application/json,text/plain;q=0.5",
    )
    return parse_dia_detail(payload, now)


def _fetch_masymas_sync(now: datetime) -> StoreScheduleObservation:
    body = urllib.parse.urlencode({
        "IdProvincia": "ALICANTE",
        "IdLocalidad": "GUARDAMAR DEL SEGURA",
        "enviado": " Buscar ",
    }).encode("utf-8")
    payload = _fetch(
        MASYMAS_LOCATOR_URL,
        policy=_allow_masymas,
        limit=128 * 1024,
        types=frozenset({"text/html", "application/xhtml+xml"}),
        accept="text/html,application/xhtml+xml",
        method="POST",
        data=body,
        navigation_fallback=True,
    )
    return parse_masymas_locator(payload, now)


async def fetch_mercadona(now: datetime) -> StoreScheduleObservation:
    return await asyncio.to_thread(_fetch_mercadona_sync, now)


async def fetch_dia(now: datetime) -> StoreScheduleObservation:
    return await asyncio.to_thread(_fetch_dia_sync, now)


async def fetch_masymas(now: datetime) -> StoreScheduleObservation:
    return await asyncio.to_thread(_fetch_masymas_sync, now)


SOURCE_FETCHERS = (fetch_mercadona, fetch_masymas, fetch_dia)
