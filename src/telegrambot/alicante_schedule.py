"""Daily Guardamar ↔ Alicante timetable and fare synchronization.

The timetable comes from the Generalitat Valenciana interurban-bus GTFS feed.
The optional basic fare comes from the current Avanza/Costa Azul public
planner. Both adapters are bounded and fail closed.
"""

import asyncio
import csv
import html
import io
import json
import logging
import os
import re
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
import http.client
import socket
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Dict, Iterable, Mapping, Optional, Sequence

from ._transport import BoundedFetchError, fetch_bounded
from .branding import FOOTER, with_footer
from .pinned import PinnedGuideState, build_leaf_message, telegram_message_link
from .state import StateError
from .telegram import TelegramError

GTFS_URL = (
    "https://dadesobertes.gva.es/dataset/"
    "2f380ffd-b389-4ff4-9f7c-be92b30fbf28/resource/"
    "3c8a2e6b-5b5e-49f5-872f-5f33fcd52547/download/gtfs.zip"
)
PLANNER_URL = "https://regular.autobusing.com/info?empresa=costa-azul&locale=es"
GTFS_HOST = "dadesobertes.gva.es"
PLANNER_HOST = "regular.autobusing.com"
GTFS_LIMIT_BYTES = 48_000_000
GTFS_UNCOMPRESSED_LIMIT_BYTES = 140_000_000
PLANNER_LIMIT_BYTES = 512_000
REQUEST_TIMEOUT_SECONDS = 25
STATE_VERSION = 1
USER_AGENT = "GuardamarMorningDigest/0.13"
TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
PRICE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})[,.](\d{2})\s*€")
GTFS_MEMBERS = frozenset({
    "calendar_dates.txt",
    "routes.txt",
    "stops.txt",
    "stop_times.txt",
    "trips.txt",
})
MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
WEEKDAYS_RU = (
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
)

SendText = Callable[[str], Awaitable[int]]
EditText = Callable[[int, str], Awaitable[None]]


class AlicanteScheduleError(RuntimeError):
    """A source response that is unsafe to publish."""


@dataclass(frozen=True)
class AlicanteFare:
    cents: int
    from_price: bool


@dataclass(frozen=True)
class AlicanteSchedule:
    service_date: date
    to_alicante: tuple[str, ...]
    from_alicante: tuple[str, ...]
    fare: Optional[AlicanteFare] = None


@dataclass(frozen=True)
class AlicanteScheduleBundle:
    current: AlicanteSchedule
    next: Optional[AlicanteSchedule]


def _allowed_gtfs_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == GTFS_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _allowed_planner_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == PLANNER_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    return " ".join(
        "".join(ch for ch in text if not unicodedata.combining(ch))
        .casefold()
        .split()
    )


def _read_csv(member: zipfile.ZipExtFile) -> Iterable[dict[str, str]]:
    wrapper = io.TextIOWrapper(member, encoding="utf-8-sig", newline="")
    yield from csv.DictReader(wrapper)


def _classify_stop(row: Mapping[str, str]) -> Optional[str]:
    name = _normalize(row.get("stop_name", ""))
    try:
        lat = float(row.get("stop_lat", ""))
        lon = float(row.get("stop_lon", ""))
    except ValueError:
        return None
    if (
        "guardamar" in name
        and 38.05 <= lat <= 38.12
        and -0.70 <= lon <= -0.62
    ):
        return "guardamar"
    if (
        ("alicante" in name or "alacant" in name)
        and "aeropuerto" not in name
        and "aeroport" not in name
        and 38.31 <= lat <= 38.36
        and -0.53 <= lon <= -0.46
    ):
        return "alicante"
    return None


def _parse_gtfs(
    payload: bytes,
    service_dates: Sequence[date],
) -> Dict[date, AlicanteSchedule]:
    """Extract direct central-bus-station departures for the requested dates."""

    if not payload.startswith(b"PK"):
        raise AlicanteScheduleError("Alicante GTFS response is not a ZIP")
    wanted_dates = tuple(dict.fromkeys(service_dates))
    if not wanted_dates or len(wanted_dates) > 3:
        raise AlicanteScheduleError("Alicante GTFS date request is invalid")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as exc:
        raise AlicanteScheduleError("Alicante GTFS ZIP is invalid") from exc
    with archive:
        infos = {info.filename: info for info in archive.infolist()}
        if not GTFS_MEMBERS.issubset(infos):
            raise AlicanteScheduleError("Alicante GTFS is missing required files")
        aggregate = sum(
            infos[name].file_size for name in GTFS_MEMBERS
        )
        if (
            aggregate <= 0
            or aggregate > GTFS_UNCOMPRESSED_LIMIT_BYTES
            or any(
                infos[name].file_size <= 0
                or infos[name].file_size > GTFS_UNCOMPRESSED_LIMIT_BYTES
                for name in GTFS_MEMBERS
            )
        ):
            raise AlicanteScheduleError("Alicante GTFS files exceed limits")

        date_keys = {item.strftime("%Y%m%d"): item for item in wanted_dates}
        service_dates_by_id: Dict[str, set[date]] = {}
        with archive.open("calendar_dates.txt") as member:
            for row in _read_csv(member):
                if row.get("exception_type") != "1":
                    continue
                service_date = date_keys.get(row.get("date", ""))
                service_id = row.get("service_id", "")
                if service_date is not None and service_id:
                    service_dates_by_id.setdefault(service_id, set()).add(service_date)
        if not service_dates_by_id:
            raise AlicanteScheduleError("Alicante GTFS has no service for requested dates")

        stop_kinds: Dict[str, str] = {}
        with archive.open("stops.txt") as member:
            for row in _read_csv(member):
                kind = _classify_stop(row)
                stop_id = row.get("stop_id", "")
                if kind is not None and stop_id:
                    stop_kinds[stop_id] = kind
        if not {"guardamar", "alicante"}.issubset(set(stop_kinds.values())):
            raise AlicanteScheduleError("Alicante GTFS endpoint stops are incomplete")

        trip_dates: Dict[str, set[date]] = {}
        with archive.open("trips.txt") as member:
            for row in _read_csv(member):
                dates = service_dates_by_id.get(row.get("service_id", ""))
                trip_id = row.get("trip_id", "")
                if dates and trip_id:
                    trip_dates[trip_id] = dates
        if not trip_dates:
            raise AlicanteScheduleError("Alicante GTFS has no active trips")

        endpoints: Dict[str, Dict[str, tuple[int, str]]] = {}
        with archive.open("stop_times.txt") as member:
            for row in _read_csv(member):
                trip_id = row.get("trip_id", "")
                if trip_id not in trip_dates:
                    continue
                kind = stop_kinds.get(row.get("stop_id", ""))
                if kind is None:
                    continue
                raw_time = row.get("departure_time", "")
                time_value = raw_time[:5]
                if not TIME_PATTERN.fullmatch(time_value):
                    continue
                try:
                    sequence = int(row.get("stop_sequence", ""))
                except ValueError:
                    continue
                trip = endpoints.setdefault(trip_id, {})
                previous = trip.get(kind)
                if previous is None or sequence < previous[0]:
                    trip[kind] = (sequence, time_value)

        collected: Dict[date, Dict[str, set[str]]] = {
            item: {"to_alicante": set(), "from_alicante": set()}
            for item in wanted_dates
        }
        for trip_id, points in endpoints.items():
            if set(points) != {"guardamar", "alicante"}:
                continue
            guardamar_seq, guardamar_time = points["guardamar"]
            alicante_seq, alicante_time = points["alicante"]
            if guardamar_seq == alicante_seq:
                continue
            for service_date in trip_dates[trip_id]:
                if guardamar_seq < alicante_seq:
                    collected[service_date]["to_alicante"].add(guardamar_time)
                else:
                    collected[service_date]["from_alicante"].add(alicante_time)

        result: Dict[date, AlicanteSchedule] = {}
        for service_date in wanted_dates:
            to_alicante = tuple(sorted(collected[service_date]["to_alicante"]))
            from_alicante = tuple(sorted(collected[service_date]["from_alicante"]))
            if (
                not 1 <= len(to_alicante) <= 64
                or not 1 <= len(from_alicante) <= 64
            ):
                raise AlicanteScheduleError(
                    f"Alicante GTFS directions are incomplete for {service_date}"
                )
            result[service_date] = AlicanteSchedule(
                service_date=service_date,
                to_alicante=to_alicante,
                from_alicante=from_alicante,
            )
        return result


def fetch_schedules(service_dates: Sequence[date]) -> Dict[date, AlicanteSchedule]:
    try:
        payload, _, _ = fetch_bounded(
            GTFS_URL,
            is_allowed_url=_allowed_gtfs_url,
            limit_bytes=GTFS_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/zip,application/octet-stream",
                "User-Agent": USER_AGENT,
            },
            accepted_types=frozenset({
                "application/zip",
                "application/octet-stream",
                "application/x-zip-compressed",
            }),
        )
    except BoundedFetchError as exc:
        raise AlicanteScheduleError(
            f"Alicante GTFS is unavailable: {exc.code}"
        ) from exc
    return _parse_gtfs(payload, service_dates)


class _PlannerRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed_planner_url(newurl):
            raise AlicanteScheduleError(
                "Alicante planner redirected outside allowlist"
            )
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class _PlannerFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[dict[str, object]] = []
        self.current: Optional[dict[str, object]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag.casefold() == "form" and self.current is None:
            self.current = {
                "action": values.get("action", ""),
                "method": values.get("method", "get").casefold(),
                "inputs": [],
            }
        elif tag.casefold() == "input" and self.current is not None:
            self.current["inputs"].append(values)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


class _PlannerTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.row: Optional[list[str]] = None
        self.cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"td", "th"} and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
            self.cell = None


def _planner_open(opener, request: urllib.request.Request) -> tuple[bytes, str]:
    if not _allowed_planner_url(request.full_url):
        raise AlicanteScheduleError("Alicante planner URL is not allowed")
    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise AlicanteScheduleError("Alicante planner is unavailable") from exc
    with response:
        final_url = response.geturl()
        payload = response.read(PLANNER_LIMIT_BYTES + 1)
        if (
            response.status != 200
            or not _allowed_planner_url(final_url)
            or len(payload) > PLANNER_LIMIT_BYTES
            or response.headers.get_content_type() not in {
                "text/html", "application/xhtml+xml"
            }
        ):
            raise AlicanteScheduleError("Alicante planner response is invalid")
        return payload, final_url


def _search_form(payload: bytes, base_url: str) -> tuple[str, Dict[str, str]]:
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AlicanteScheduleError("Alicante planner form is not UTF-8") from exc
    parser = _PlannerFormParser()
    parser.feed(page)
    required = {
        "venta[origen_nombre]",
        "venta[destino_nombre]",
        "venta[fecha_ida]",
    }
    candidates = []
    for form in parser.forms:
        inputs = form["inputs"]
        names = {item.get("name", "") for item in inputs}
        if required.issubset(names) and form["method"] == "post":
            candidates.append(form)
    if len(candidates) != 1:
        raise AlicanteScheduleError("Alicante planner form is ambiguous")
    form = candidates[0]
    values: Dict[str, str] = {}
    for item in form["inputs"]:
        name = item.get("name", "")
        if not name:
            continue
        input_type = item.get("type", "text").casefold()
        if input_type in {"checkbox", "radio"} and "checked" not in item:
            continue
        if input_type == "hidden" or name in required:
            if name in values:
                raise AlicanteScheduleError("Alicante planner form has duplicate fields")
            values[name] = item.get("value", "")
    action = urllib.parse.urljoin(base_url, str(form["action"] or base_url))
    if not _allowed_planner_url(action):
        raise AlicanteScheduleError("Alicante planner form action is not allowed")
    return action, values


def _parse_price_page(payload: bytes) -> AlicanteFare:
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AlicanteScheduleError("Alicante planner result is not UTF-8") from exc
    parser = _PlannerTableParser()
    parser.feed(page)
    prices: list[int] = []
    header: Optional[tuple[int, int, int]] = None
    for row in parser.rows:
        normalized = [_normalize(cell) for cell in row]
        if header is None:
            departure = next(
                (i for i, cell in enumerate(normalized) if "salida" in cell or "departure" in cell),
                None,
            )
            arrival = next(
                (i for i, cell in enumerate(normalized) if "llegada" in cell or "arrival" in cell),
                None,
            )
            price = next(
                (i for i, cell in enumerate(normalized) if "precio" in cell or "price" in cell),
                None,
            )
            if departure is not None and arrival is not None and price is not None:
                header = (departure, arrival, price)
            continue
        departure, arrival, price = header
        if max(header) >= len(row):
            continue
        if not TIME_PATTERN.fullmatch(row[departure]) or not TIME_PATTERN.fullmatch(row[arrival]):
            continue
        match = PRICE_PATTERN.search(row[price])
        if match is None:
            continue
        cents = int(match.group(1)) * 100 + int(match.group(2))
        if 100 <= cents <= 2_000:
            prices.append(cents)
    if not prices:
        raise AlicanteScheduleError("Alicante planner has no validated basic fare")
    unique = sorted(set(prices))
    return AlicanteFare(cents=unique[0], from_price=len(unique) > 1)


def fetch_fares(service_dates: Sequence[date]) -> Dict[date, AlicanteFare]:
    """Fetch basic one-way fares for both directions with one planner session."""

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        _PlannerRedirectHandler(),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    initial = urllib.request.Request(
        PLANNER_URL,
        headers={"Accept": "text/html", "User-Agent": USER_AGENT},
    )
    payload, final_url = _planner_open(opener, initial)
    action, base_fields = _search_form(payload, final_url)
    result: Dict[date, AlicanteFare] = {}
    for service_date in tuple(dict.fromkeys(service_dates)):
        direction_fares = []
        for origin, destination in (
            ("GUARDAMAR", "ALICANTE"),
            ("ALICANTE", "GUARDAMAR"),
        ):
            fields = dict(base_fields)
            fields.update({
                "venta[origen_nombre]": origin,
                "venta[destino_nombre]": destination,
                "venta[fecha_ida]": service_date.strftime("%d/%m/%Y"),
            })
            body = urllib.parse.urlencode(fields).encode("utf-8")
            request = urllib.request.Request(
                action,
                data=body,
                headers={
                    "Accept": "text/html",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": USER_AGENT,
                    "Referer": final_url,
                },
                method="POST",
            )
            page, _ = _planner_open(opener, request)
            direction_fares.append(_parse_price_page(page))
        cents = min(item.cents for item in direction_fares)
        result[service_date] = AlicanteFare(
            cents=cents,
            from_price=(
                any(item.from_price for item in direction_fares)
                or len({item.cents for item in direction_fares}) > 1
            ),
        )
    return result


def _encode_schedule(schedule: AlicanteSchedule) -> dict:
    return {
        "service_date": schedule.service_date.isoformat(),
        "to_alicante": list(schedule.to_alicante),
        "from_alicante": list(schedule.from_alicante),
        "fare": (
            None
            if schedule.fare is None
            else {
                "cents": schedule.fare.cents,
                "from_price": schedule.fare.from_price,
            }
        ),
    }


def _decode_schedule(raw: object) -> AlicanteSchedule:
    if not isinstance(raw, dict):
        raise StateError("Alicante schedule state is invalid")
    try:
        service_date = date.fromisoformat(raw["service_date"])
        to_alicante = tuple(raw["to_alicante"])
        from_alicante = tuple(raw["from_alicante"])
        raw_fare = raw.get("fare")
    except (KeyError, TypeError, ValueError) as exc:
        raise StateError("Alicante schedule state is invalid") from exc
    if (
        not 1 <= len(to_alicante) <= 64
        or not 1 <= len(from_alicante) <= 64
        or len(set(to_alicante)) != len(to_alicante)
        or len(set(from_alicante)) != len(from_alicante)
        or tuple(sorted(to_alicante)) != to_alicante
        or tuple(sorted(from_alicante)) != from_alicante
        or not all(isinstance(value, str) and TIME_PATTERN.fullmatch(value) for value in to_alicante)
        or not all(isinstance(value, str) and TIME_PATTERN.fullmatch(value) for value in from_alicante)
    ):
        raise StateError("Alicante schedule state is invalid")
    fare = None
    if raw_fare is not None:
        if not isinstance(raw_fare, dict):
            raise StateError("Alicante schedule state is invalid")
        cents = raw_fare.get("cents")
        from_price = raw_fare.get("from_price")
        if (
            not isinstance(cents, int)
            or isinstance(cents, bool)
            or not 100 <= cents <= 2_000
            or not isinstance(from_price, bool)
        ):
            raise StateError("Alicante schedule state is invalid")
        fare = AlicanteFare(cents=cents, from_price=from_price)
    return AlicanteSchedule(
        service_date=service_date,
        to_alicante=to_alicante,
        from_alicante=from_alicante,
        fare=fare,
    )


class AlicanteScheduleState:
    """Strict current+next snapshots; raw source data is never persisted."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Optional[AlicanteScheduleBundle]:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("Alicante schedule state is invalid") from exc
        if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
            raise StateError("Alicante schedule state is invalid")
        current = _decode_schedule(raw.get("current"))
        next_raw = raw.get("next")
        next_schedule = None if next_raw is None else _decode_schedule(next_raw)
        if next_schedule is not None and next_schedule.service_date != current.service_date + timedelta(days=1):
            raise StateError("Alicante schedule state is invalid")
        return AlicanteScheduleBundle(current=current, next=next_schedule)

    def write(self, bundle: AlicanteScheduleBundle) -> None:
        if (
            bundle.next is not None
            and bundle.next.service_date != bundle.current.service_date + timedelta(days=1)
        ):
            raise StateError("Alicante schedule state is invalid")
        payload = {
            "version": STATE_VERSION,
            "current": _encode_schedule(bundle.current),
            "next": None if bundle.next is None else _encode_schedule(bundle.next),
        }
        _decode_schedule(payload["current"])
        if payload["next"] is not None:
            _decode_schedule(payload["next"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}."
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def _format_times(values: Sequence[str]) -> str:
    return "\n".join(
        " · ".join(values[index:index + 5])
        for index in range(0, len(values), 5)
    )


def build_alicante_message(
    schedule: AlicanteSchedule,
    today: date,
    transport_link: str,
) -> str:
    if schedule.service_date == today:
        date_label = (
            f"Сегодня, {today.day} {MONTHS_RU[today.month - 1]}, "
            f"{WEEKDAYS_RU[today.weekday()]}"
        )
    else:
        date_label = (
            f"Расписание на {schedule.service_date.day} "
            f"{MONTHS_RU[schedule.service_date.month - 1]}, "
            f"{WEEKDAYS_RU[schedule.service_date.weekday()]}"
        )
    fare_line = ""
    if schedule.fare is not None:
        amount = f"{schedule.fare.cents // 100},{schedule.fare.cents % 100:02d} €"
        prefix = "от " if schedule.fare.from_price else ""
        fare_line = f"\n\n🎟 <b>Билет в одну сторону:</b> {prefix}{amount}"
    message = with_footer(
        "🚌 <b>Гуардамар ↔ Alicante</b>\n"
        "Доехать можно без пересадок на автобусе Avanza.\n\n"
        "По дороге автобус заезжает в La Marina, Santa Pola и El Altet.\n\n"
        f"🗓 <b>{date_label}</b>\n\n"
        "➡️ <b>Гуардамар → Alicante</b>\n"
        + _format_times(schedule.to_alicante)
        + "\n\n⬅️ <b>Alicante → Гуардамар</b>\n"
        + _format_times(schedule.from_alicante)
        + fare_line
        + "\n\n📍 <b>Откуда и куда</b>\n"
        '<a href="https://www.google.com/maps/search/?api=1&amp;query=Carrer+Molivent%2C+Guardamar+del+Segura">автовокзал Гуардамара</a>'
        " ↔ "
        '<a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses+de+Alicante">автовокзал в Alicante</a>'
        + "\n\n"
        + f'🕒 <a href="{PLANNER_URL}">Найти расписание на другую дату</a>'
        + '\n\n⬅️ <a href="'
        + html.escape(transport_link, quote=True)
        + '"><b>К списку транспорта</b></a>'
    )
    if len(message) > 4096 or message.count(FOOTER) != 1 or "—" in message:
        raise AlicanteScheduleError("Alicante message is not Telegram-safe")
    return message


async def sync_alicante_schedule(
    now: datetime,
    chat_id: str,
    pinned_state: PinnedGuideState,
    schedule_state: AlicanteScheduleState,
    send_text: SendText,
    edit_text: EditText,
) -> dict[str, int]:
    """Refresh today+tomorrow once at the existing 05:00 transport sync."""

    payload = await asyncio.to_thread(pinned_state.read_payload, chat_id)
    messages = payload["messages"]
    if "transport" not in messages or "alicante" not in messages:
        raise AlicanteScheduleError("Alicante guide message is missing from state")

    cached = None
    try:
        cached = await asyncio.to_thread(schedule_state.read)
    except StateError as exc:
        logging.warning("Alicante schedule state rejected: %s", exc)

    bundle = None
    service_dates = (now.date(), now.date() + timedelta(days=1))
    try:
        schedules = await asyncio.to_thread(fetch_schedules, service_dates)
        try:
            fares = await asyncio.to_thread(fetch_fares, service_dates)
        except AlicanteScheduleError as exc:
            logging.warning("Alicante fare unavailable; omitting price: %s", exc)
            fares = {}
        current_base = schedules[now.date()]
        next_base = schedules[now.date() + timedelta(days=1)]
        bundle = AlicanteScheduleBundle(
            current=AlicanteSchedule(
                service_date=current_base.service_date,
                to_alicante=current_base.to_alicante,
                from_alicante=current_base.from_alicante,
                fare=fares.get(now.date()),
            ),
            next=AlicanteSchedule(
                service_date=next_base.service_date,
                to_alicante=next_base.to_alicante,
                from_alicante=next_base.from_alicante,
                fare=fares.get(now.date() + timedelta(days=1)),
            ),
        )
        await asyncio.to_thread(schedule_state.write, bundle)
    except AlicanteScheduleError as exc:
        logging.warning(
            "Alicante timetable unavailable; keeping accepted message: %s", exc
        )
        bundle = cached

    transport_link = telegram_message_link(chat_id, messages["transport"])
    message = (
        build_alicante_message(bundle.current, now.date(), transport_link)
        if bundle is not None
        else build_leaf_message("alicante", transport_link)
    )
    message_id = messages["alicante"]
    try:
        await edit_text(message_id, message)
        return dict(messages)
    except TelegramError as exc:
        if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
            return dict(messages)
        if exc.diagnostic_code != "MESSAGE-NOT-FOUND":
            raise
    try:
        new_id = await send_text(message)
    except TelegramError as exc:
        if exc.retryable and exc.server_status != 429:
            await asyncio.to_thread(
                pinned_state.mark_uncertain, chat_id, "alicante"
            )
        raise
    messages["alicante"] = new_id
    payload["messages"] = messages
    await asyncio.to_thread(pinned_state.write_payload, chat_id, payload)
    return dict(messages)
