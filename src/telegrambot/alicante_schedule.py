"""Daily Guardamar ↔ Alicante timetable synchronization.

The Avanza/Costa Azul public planner is the single source for exact-date
departures and the basic one-way fare. The adapter is bounded, HTML-only and
fails closed; it does not need a browser or persist source HTML.
"""

import asyncio
import html
import http.client
import http.cookiejar
import json
import logging
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Dict, Mapping, Optional, Sequence

from .branding import FOOTER, with_footer
from .pinned import (
    GUARDAMAR_BUS_STATION_MAP_URL,
    PinnedGuideState,
    build_leaf_message,
    telegram_message_link,
)
from .state import StateError
from .telegram import TelegramError

PLANNER_URL = "https://regular.autobusing.com/info?empresa=costa-azul&locale=es"
PLANNER_HOST = "regular.autobusing.com"
PLANNER_LIMIT_BYTES = 512_000
REQUEST_TIMEOUT_SECONDS = 25
STATE_VERSION = 1
USER_AGENT = "GuardamarMorningDigest/0.13"
TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
PRICE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})[,.](\d{2})\s*€")
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


@dataclass(frozen=True)
class _Direction:
    departures: tuple[str, ...]
    fare: Optional[AlicanteFare]


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
        and parsed.path.startswith("/info")
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


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
        tag = tag.casefold()
        if tag == "form" and self.current is None:
            self.current = {
                "action": values.get("action", ""),
                "method": values.get("method", "get").casefold(),
                "inputs": [],
            }
        elif tag == "input" and self.current is not None:
            self.current["inputs"].append(values)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


class _PlannerPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.row: Optional[list[str]] = None
        self.cell: Optional[list[str]] = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data)
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


def _planner_open(
    opener,
    request: urllib.request.Request,
) -> tuple[bytes, str]:
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
                "text/html",
                "application/xhtml+xml",
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
        if input_type == "hidden":
            if name in values:
                raise AlicanteScheduleError(
                    "Alicante planner form has duplicate hidden fields"
                )
            values[name] = item.get("value", "")

    action = urllib.parse.urljoin(base_url, str(form["action"] or base_url))
    if not _allowed_planner_url(action):
        raise AlicanteScheduleError(
            "Alicante planner form action is not allowed"
        )
    return action, values


def _parse_schedule_page(
    payload: bytes,
    service_date: date,
    origin: str,
    destination: str,
) -> _Direction:
    try:
        page = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AlicanteScheduleError(
            "Alicante planner result is not UTF-8"
        ) from exc

    parser = _PlannerPageParser()
    parser.feed(page)
    page_text = _normalize(" ".join(parser.text))
    expected_date = service_date.strftime("%d/%m/%Y")
    if (
        origin.casefold() not in page_text
        or destination.casefold() not in page_text
        or expected_date.casefold() not in page_text
    ):
        raise AlicanteScheduleError(
            "Alicante planner result does not match requested route/date"
        )

    headers: list[tuple[int, int, Optional[int]]] = []
    for row in parser.rows:
        normalized = [_normalize(cell) for cell in row]
        departure = next(
            (
                index
                for index, cell in enumerate(normalized)
                if cell in {"salida", "departure"}
            ),
            None,
        )
        arrival = next(
            (
                index
                for index, cell in enumerate(normalized)
                if cell in {"llegada", "arrival"}
            ),
            None,
        )
        price = next(
            (
                index
                for index, cell in enumerate(normalized)
                if cell in {"precio", "price", "tarifa"}
            ),
            None,
        )
        if departure is not None and arrival is not None:
            headers.append((departure, arrival, price))

    if len(headers) != 1:
        raise AlicanteScheduleError(
            "Alicante planner schedule table is ambiguous"
        )
    departure_index, arrival_index, price_index = headers[0]

    departures: list[str] = []
    prices: list[int] = []
    price_complete = price_index is not None
    for row in parser.rows:
        if max(departure_index, arrival_index) >= len(row):
            continue
        departure = row[departure_index]
        arrival = row[arrival_index]
        if not (
            TIME_PATTERN.fullmatch(departure)
            and TIME_PATTERN.fullmatch(arrival)
        ):
            continue
        departures.append(departure)
        if price_index is None or price_index >= len(row):
            price_complete = False
            continue
        match = PRICE_PATTERN.search(row[price_index])
        if match is None:
            price_complete = False
            continue
        cents = int(match.group(1)) * 100 + int(match.group(2))
        if not 100 <= cents <= 2_000:
            price_complete = False
            continue
        prices.append(cents)

    unique_departures = tuple(sorted(set(departures)))
    if (
        not 1 <= len(departures) <= 64
        or not 1 <= len(unique_departures) <= 64
    ):
        raise AlicanteScheduleError(
            "Alicante planner has no validated departures"
        )

    fare = None
    if price_complete and len(prices) == len(departures):
        unique_prices = sorted(set(prices))
        fare = AlicanteFare(
            cents=unique_prices[0],
            from_price=len(unique_prices) > 1,
        )
    return _Direction(departures=unique_departures, fare=fare)


def _fetch_direction(
    opener,
    action: str,
    referer: str,
    base_fields: Mapping[str, str],
    service_date: date,
    origin: str,
    destination: str,
) -> _Direction:
    fields = dict(base_fields)
    fields.update(
        {
            "venta[origen_nombre]": origin,
            "venta[destino_nombre]": destination,
            "venta[fecha_ida]": service_date.strftime("%d/%m/%Y"),
            "venta[fecha_vta]": "",
            "venta[tipo_iyv]": "ida",
        }
    )
    request = urllib.request.Request(
        action,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer,
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    payload, _ = _planner_open(opener, request)
    return _parse_schedule_page(
        payload,
        service_date,
        origin,
        destination,
    )


def fetch_schedules(
    service_dates: Sequence[date],
) -> Dict[date, AlicanteSchedule]:
    """Fetch exact-date departures and fare for requested service dates."""

    wanted_dates = tuple(dict.fromkeys(service_dates))
    if not wanted_dates or len(wanted_dates) > 3:
        raise AlicanteScheduleError(
            "Alicante planner date request is invalid"
        )

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        _PlannerRedirectHandler(),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    initial_request = urllib.request.Request(
        PLANNER_URL,
        headers={"Accept": "text/html", "User-Agent": USER_AGENT},
    )
    initial_payload, final_url = _planner_open(opener, initial_request)
    action, base_fields = _search_form(initial_payload, final_url)

    result: Dict[date, AlicanteSchedule] = {}
    for service_date in wanted_dates:
        try:
            outbound = _fetch_direction(
                opener,
                action,
                final_url,
                base_fields,
                service_date,
                "GUARDAMAR",
                "ALICANTE",
            )
            inbound = _fetch_direction(
                opener,
                action,
                final_url,
                base_fields,
                service_date,
                "ALICANTE",
                "GUARDAMAR",
            )
        except AlicanteScheduleError as exc:
            logging.warning(
                "Alicante planner rejected %s: %s",
                service_date,
                exc,
            )
            continue

        fares = [
            item.fare
            for item in (outbound, inbound)
            if item.fare is not None
        ]
        fare = None
        if len(fares) == 2:
            cents = min(item.cents for item in fares)
            fare = AlicanteFare(
                cents=cents,
                from_price=(
                    any(item.from_price for item in fares)
                    or len({item.cents for item in fares}) > 1
                ),
            )

        result[service_date] = AlicanteSchedule(
            service_date=service_date,
            to_alicante=outbound.departures,
            from_alicante=inbound.departures,
            fare=fare,
        )

    if not result:
        raise AlicanteScheduleError(
            "Alicante planner has no validated requested dates"
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
        or not all(
            isinstance(value, str) and TIME_PATTERN.fullmatch(value)
            for value in to_alicante
        )
        or not all(
            isinstance(value, str) and TIME_PATTERN.fullmatch(value)
            for value in from_alicante
        )
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
        next_schedule = (
            None if next_raw is None else _decode_schedule(next_raw)
        )
        if (
            next_schedule is not None
            and next_schedule.service_date
            != current.service_date + timedelta(days=1)
        ):
            raise StateError("Alicante schedule state is invalid")
        return AlicanteScheduleBundle(
            current=current,
            next=next_schedule,
        )

    def write(self, bundle: AlicanteScheduleBundle) -> None:
        if (
            bundle.next is not None
            and bundle.next.service_date
            != bundle.current.service_date + timedelta(days=1)
        ):
            raise StateError("Alicante schedule state is invalid")
        payload = {
            "version": STATE_VERSION,
            "current": _encode_schedule(bundle.current),
            "next": (
                None
                if bundle.next is None
                else _encode_schedule(bundle.next)
            ),
        }
        _decode_schedule(payload["current"])
        if payload["next"] is not None:
            _decode_schedule(payload["next"])

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
        )
        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                )
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
        amount = (
            f"{schedule.fare.cents // 100},"
            f"{schedule.fare.cents % 100:02d} €"
        )
        prefix = "от " if schedule.fare.from_price else ""
        fare_line = (
            f"\n\n🎟 <b>Билет в одну сторону:</b> {prefix}{amount}"
        )

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
        '<a href="'
        + html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)
        + '">'
        "автовокзал Гуардамара</a>"
        " ↔ "
        '<a href="https://www.google.com/maps/search/?api=1&amp;query='
        'Estaci%C3%B3n+de+Autobuses+de+Alicante">'
        "автовокзал в Alicante</a>"
        + "\n\n"
        + f'🕒 <a href="{PLANNER_URL}">'
        "Найти расписание на другую дату</a>"
        + '\n\n⬅️ <a href="'
        + html.escape(transport_link, quote=True)
        + '"><b>К списку транспорта</b></a>'
    )
    if (
        len(message) > 4096
        or message.count(FOOTER) != 1
        or "—" in message
    ):
        raise AlicanteScheduleError(
            "Alicante message is not Telegram-safe"
        )
    return message


async def sync_alicante_schedule(
    now: datetime,
    chat_id: str,
    pinned_state: PinnedGuideState,
    schedule_state: AlicanteScheduleState,
    send_text: SendText,
    edit_text: EditText,
) -> dict[str, int]:
    """Refresh the Alicante card during the existing transport sync."""

    payload = await asyncio.to_thread(
        pinned_state.read_payload,
        chat_id,
    )
    messages = payload["messages"]
    if "transport" not in messages or "alicante" not in messages:
        raise AlicanteScheduleError(
            "Alicante guide message is missing from state"
        )

    cached = None
    try:
        cached = await asyncio.to_thread(schedule_state.read)
    except StateError as exc:
        logging.warning(
            "Alicante schedule state rejected: %s",
            exc,
        )

    today = now.date()
    tomorrow = today + timedelta(days=1)
    bundle = None
    try:
        schedules = await asyncio.to_thread(
            fetch_schedules,
            (today, tomorrow),
        )
        current = schedules.get(today)
        if current is None:
            raise AlicanteScheduleError(
                "Alicante planner has no validated current date"
            )
        bundle = AlicanteScheduleBundle(
            current=current,
            next=schedules.get(tomorrow),
        )
        await asyncio.to_thread(schedule_state.write, bundle)
    except AlicanteScheduleError as exc:
        logging.warning(
            "Alicante timetable unavailable; keeping accepted message: %s",
            exc,
        )
        bundle = cached

    transport_link = telegram_message_link(
        chat_id,
        messages["transport"],
    )
    message = (
        build_alicante_message(
            bundle.current,
            today,
            transport_link,
        )
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
                pinned_state.mark_uncertain,
                chat_id,
                "alicante",
            )
        raise

    messages["alicante"] = new_id
    payload["messages"] = messages
    await asyncio.to_thread(
        pinned_state.write_payload,
        chat_id,
        payload,
    )
    return dict(messages)
