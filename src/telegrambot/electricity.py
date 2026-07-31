"""Official next-day PVPC prices from the lightweight ESIOS API."""

import asyncio
import html
import http.client
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Awaitable, Callable, Dict, Sequence, Tuple
from zoneinfo import ZoneInfo

from .telegram import TelegramError

ESIOS_HOST = "api.esios.ree.es"
INDICATOR_ID = 1001
PENINSULA_GEO_NAME = "península"
TIMEZONE = ZoneInfo("Europe/Madrid")
TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 1_000_000
USER_AGENT = "GuardamarMorningDigest/0.13"


class ElectricityError(RuntimeError):
    """Safe, classified ESIOS failure."""

    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.retryable = retryable


@dataclass(frozen=True)
class HourlyPrice:
    hour: int
    eur_kwh: Decimal


@dataclass(frozen=True)
class DailyPrices:
    local_date: date
    hours: Tuple[HourlyPrice, ...]


def _request_payload(api_key: str, target_date: date) -> bytes:
    if not api_key or any(character.isspace() for character in api_key):
        raise ElectricityError(
            "ESIOS_API_KEY is required", code="CONFIG", retryable=False
        )
    start = datetime.combine(target_date, time.min, TIMEZONE)
    end = datetime.combine(target_date, time.max, TIMEZONE)
    query = urllib.parse.urlencode({
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    })
    url = f"https://{ESIOS_HOST}/indicators/{INDICATOR_ID}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json; application/vnd.esios-api-v1+json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if urllib.parse.urlparse(response.geturl()).hostname != ESIOS_HOST:
                raise ElectricityError(
                    "ESIOS redirected outside its API host",
                    code="REDIRECT",
                    retryable=False,
                )
            if response.headers.get_content_type() != "application/json":
                raise ElectricityError(
                    "ESIOS returned an unexpected content type",
                    code="CONTENT-TYPE",
                    retryable=True,
                )
            payload = response.read(RESPONSE_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        retryable = exc.code == 429 or 500 <= exc.code <= 599
        raise ElectricityError(
            f"ESIOS returned HTTP {exc.code}",
            code=f"HTTP-{exc.code}",
            retryable=retryable,
        ) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout,
            OSError, http.client.HTTPException) as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, (TimeoutError, socket.timeout))
        )
        raise ElectricityError(
            "ESIOS request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
            retryable=True,
        ) from None
    if len(payload) > RESPONSE_LIMIT_BYTES:
        raise ElectricityError(
            "ESIOS response is too large", code="TOO-LARGE", retryable=True
        )
    return payload


def normalize_prices(payload: bytes, target_date: date) -> DailyPrices:
    try:
        root = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ElectricityError(
            "ESIOS returned invalid JSON", code="INVALID-JSON", retryable=True
        ) from exc
    indicator = root.get("indicator") if isinstance(root, dict) else None
    values = indicator.get("values") if isinstance(indicator, dict) else None
    if not isinstance(values, list):
        raise ElectricityError(
            "ESIOS response has no values", code="INVALID-STRUCTURE", retryable=True
        )

    by_hour: Dict[int, Decimal] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        geo_name = item.get("geo_name")
        if not isinstance(geo_name, str) or geo_name.casefold() != PENINSULA_GEO_NAME:
            continue
        raw_datetime = item.get("datetime")
        try:
            moment = datetime.fromisoformat(raw_datetime)
            if moment.tzinfo is None:
                raise ValueError("ESIOS datetime has no timezone")
            moment = moment.astimezone(TIMEZONE)
            price = Decimal(str(item.get("value"))) / Decimal("1000")
        except (TypeError, ValueError, InvalidOperation):
            continue
        if moment.date() != target_date or not Decimal("-1") <= price <= Decimal("5"):
            continue
        if moment.minute or moment.second or moment.hour in by_hour:
            raise ElectricityError(
                "ESIOS returned duplicate or non-hourly values",
                code="INVALID-HOURS",
                retryable=True,
            )
        by_hour[moment.hour] = price

    if set(by_hour) != set(range(24)):
        raise ElectricityError(
            "ESIOS has not published all 24 hours",
            code="INCOMPLETE",
            retryable=True,
        )
    return DailyPrices(
        target_date,
        tuple(HourlyPrice(hour, by_hour[hour]) for hour in range(24)),
    )


async def fetch_prices(
    api_key: str,
    target_date: date,
) -> DailyPrices:
    """Perform one bounded request; external invocations provide retries."""

    payload = await asyncio.to_thread(
        _request_payload, api_key, target_date
    )
    return normalize_prices(payload, target_date)


def _price(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)).replace(".", ",")


def _colors(prices: Sequence[HourlyPrice]) -> Dict[int, str]:
    red_threshold = max(item.eur_kwh for item in prices) * Decimal("0.90")
    colors = {}
    for item in prices:
        if item.eur_kwh > Decimal("0.15") and item.eur_kwh >= red_threshold:
            colors[item.hour] = "🔴"
        elif item.eur_kwh < Decimal("0.10"):
            colors[item.hour] = "🟢"
        elif item.eur_kwh <= Decimal("0.15"):
            colors[item.hour] = "🟡"
        else:
            colors[item.hour] = "🟠"
    return colors


def _best_window(prices: Sequence[HourlyPrice]) -> Tuple[int, int]:
    """Choose the cheapest continuous six-hour planning window."""

    duration = 6
    start = min(
        range(0, 24 - duration + 1),
        key=lambda first: (
            sum(item.eur_kwh for item in prices[first:first + duration]),
            first,
        ),
    )
    return start, start + duration


def build_price_message(data: DailyPrices) -> str:
    colors = _colors(data.hours)
    cheapest = min(data.hours, key=lambda item: (item.eur_kwh, item.hour))
    expensive = max(data.hours, key=lambda item: (item.eur_kwh, -item.hour))
    best_start, best_end = _best_window(data.hours)
    rows = []
    for left, right in zip(data.hours[:12], data.hours[12:]):
        rows.append(
            f"{left.hour:02d}  {colors[left.hour]} {_price(left.eur_kwh)} │ "
            f"{right.hour:02d}  {colors[right.hour]} {_price(right.eur_kwh)}"
        )
    weekday = (
        "понедельник", "вторник", "среда", "четверг",
        "пятница", "суббота", "воскресенье",
    )[data.local_date.weekday()]
    months = ("", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
    table = html.escape("\n".join(rows))
    return (
        "⚡ <b>Цены на электричество завтра</b>\n"
        f"{weekday.capitalize()}, {data.local_date.day} {months[data.local_date.month]}\n\n"
        "🟢 <b>Выгоднее всего</b>\n"
        f"{cheapest.hour:02d}:00–{cheapest.hour + 1:02d}:00 · {_price(cheapest.eur_kwh)} €/кВт·ч\n\n"
        "🔴 <b>Дороже всего</b>\n"
        f"{expensive.hour:02d}:00–{expensive.hour + 1:02d}:00 · {_price(expensive.eur_kwh)} €/кВт·ч\n\n"
        "🕐 <b>По часам</b>\n"
        f"<pre>{table}</pre>\n"
        "💡 Энергоёмкие дела лучше запланировать "
        f"на период с {best_start:02d}:00 до {best_end:02d}:00.\n\n"
        "Для PVPC; для индексированных тарифов — ориентир.\n"
        "Источник: ESIOS / Red Eléctrica"
    )


def build_explanation_message() -> str:
    return (
        "💡 <b>Как читать таблицу</b>\n\n"
        "Цена указана за 1 кВт·ч без учёта вашего фиксированного тарифа и индивидуальных условий договора.\n\n"
        "🟢 дешевле 0,10 €\n"
        "🟡 от 0,10 до 0,15 €\n"
        "🟠 дороже 0,15 €\n"
        "🔴 самый дорогой диапазон дня\n\n"
        "Данные: официальный показатель PVPC 2.0TD для Península от ESIOS / Red Eléctrica."
    )


async def publish_prices(
    target_date: date,
    state,
    collect: Callable[[], Awaitable[DailyPrices]],
    send_main: Callable[[str], Awaitable[int]],
    send_explanation: Callable[[str, int], Awaitable[int]],
) -> str:
    """Publish at most one main price table for a target local date."""

    with state.exclusive_run():
        if state.is_published(target_date):
            return "duplicate"
        data = await collect()
        if data.local_date != target_date:
            raise ElectricityError(
                "ESIOS returned the wrong local date",
                code="WRONG-DATE",
                retryable=True,
            )
        message_id = await send_main(build_price_message(data))
        state.mark_published(target_date)
        try:
            await send_explanation(build_explanation_message(), message_id)
        except TelegramError:
            # The price table is the product. A failed optional explanation
            # must not cause a duplicate table on the next invocation.
            logging.warning(
                "Electricity explanation reply failed after main publication"
            )
            return "success-without-explanation"
        return "success"
