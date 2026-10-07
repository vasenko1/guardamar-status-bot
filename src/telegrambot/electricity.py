"""Official next-day PVPC prices from Red Eléctrica APIs."""

import asyncio
import html
import json
import logging
import os
import tempfile
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer

ESIOS_HOST = "api.esios.ree.es"
REDATA_HOST = "apidatos.ree.es"
ESIOS_SOURCE = "ESIOS / Red Eléctrica"
REDATA_SOURCE = "REData / Red Eléctrica"
INDICATOR_ID = 1001
PENINSULA_GEO_ID = 8741
PENINSULA_GEO_NAME = "península"
SNAPSHOT_SOURCES = frozenset({ESIOS_SOURCE, REDATA_SOURCE})
TIMEZONE = ZoneInfo("Europe/Madrid")
TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 1_000_000
SNAPSHOT_LIMIT_BYTES = 16_384
SNAPSHOT_VERSION = 1
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
    source: str = ESIOS_SOURCE


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
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=lambda value: (
                urllib.parse.urlparse(value).hostname == ESIOS_HOST
            ),
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=TIMEOUT_SECONDS,
            headers={
                "Accept": (
                    "application/json; application/vnd.esios-api-v1+json"
                ),
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "User-Agent": USER_AGENT,
            },
            # Never follow a redirect: the personal token stays on the
            # configured API request only.
            follow_redirects=False,
        )
    except BoundedFetchError as exc:
        if exc.status is not None:
            retryable = exc.status == 429 or 500 <= exc.status <= 599
        else:
            retryable = exc.code != "REDIRECT"
        raise ElectricityError(
            f"ESIOS request failed: {exc.code}",
            code=exc.code,
            retryable=retryable,
        ) from None
    return payload


def _request_redata_payload(target_date: date) -> bytes:
    query = urllib.parse.urlencode({
        "start_date": f"{target_date.isoformat()}T00:00",
        "end_date": f"{target_date.isoformat()}T23:59",
        "time_trunc": "hour",
        "geo_trunc": "electric_system",
        "geo_limit": "peninsular",
        "geo_ids": str(PENINSULA_GEO_ID),
    })
    url = (
        f"https://{REDATA_HOST}/es/datos/mercados/"
        f"precios-mercados-tiempo-real?{query}"
    )
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=lambda value: (
                urllib.parse.urlparse(value).hostname == REDATA_HOST
            ),
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            follow_redirects=False,
        )
    except BoundedFetchError as exc:
        if exc.status is not None:
            retryable = exc.status == 429 or 500 <= exc.status <= 599
        else:
            retryable = exc.code != "REDIRECT"
        raise ElectricityError(
            f"REData request failed: {exc.code}",
            code=f"REDATA-{exc.code}",
            retryable=retryable,
        ) from None
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
        if (
            moment.date() != target_date
            or not price.is_finite()
            or not Decimal("-1") <= price <= Decimal("5")
        ):
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
    data = DailyPrices(
        target_date,
        tuple(HourlyPrice(hour, by_hour[hour]) for hour in range(24)),
        ESIOS_SOURCE,
    )
    _validate_daily_prices(data)
    return data


def normalize_redata_prices(payload: bytes, target_date: date) -> DailyPrices:
    try:
        root = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ElectricityError(
            "REData returned invalid JSON",
            code="REDATA-INVALID-JSON",
            retryable=True,
        ) from exc

    included = root.get("included") if isinstance(root, dict) else None
    if not isinstance(included, list):
        raise ElectricityError(
            "REData response has no included series",
            code="REDATA-INVALID-STRUCTURE",
            retryable=True,
        )

    candidates = []
    for item in included:
        if not isinstance(item, dict) or str(item.get("id")) != str(INDICATOR_ID):
            continue
        attributes = item.get("attributes")
        if not isinstance(attributes, dict):
            continue
        label = " ".join(
            value
            for value in (item.get("type"), attributes.get("title"))
            if isinstance(value, str)
        ).casefold()
        if "pvpc" not in label:
            continue
        candidates.append(attributes)

    if len(candidates) != 1 or not isinstance(candidates[0].get("values"), list):
        raise ElectricityError(
            "REData response has no unique PVPC series",
            code="REDATA-INVALID-STRUCTURE",
            retryable=True,
        )

    by_hour: Dict[int, Decimal] = {}
    for item in candidates[0]["values"]:
        if not isinstance(item, dict):
            continue
        raw_datetime = item.get("datetime")
        try:
            moment = datetime.fromisoformat(raw_datetime)
            if moment.tzinfo is None:
                raise ValueError("REData datetime has no timezone")
            moment = moment.astimezone(TIMEZONE)
            price = Decimal(str(item.get("value"))) / Decimal("1000")
        except (TypeError, ValueError, InvalidOperation):
            continue
        if (
            moment.date() != target_date
            or not price.is_finite()
            or not Decimal("-1") <= price <= Decimal("5")
        ):
            continue
        if moment.minute or moment.second or moment.hour in by_hour:
            raise ElectricityError(
                "REData returned duplicate or non-hourly values",
                code="REDATA-INVALID-HOURS",
                retryable=True,
            )
        by_hour[moment.hour] = price

    if set(by_hour) != set(range(24)):
        raise ElectricityError(
            "REData has not published all 24 hours",
            code="REDATA-INCOMPLETE",
            retryable=True,
        )

    data = DailyPrices(
        target_date,
        tuple(HourlyPrice(hour, by_hour[hour]) for hour in range(24)),
        REDATA_SOURCE,
    )
    _validate_daily_prices(data)
    return data


async def fetch_prices(
    api_key: str,
    target_date: date,
) -> DailyPrices:
    """Perform one bounded request; external invocations provide retries."""

    payload = await asyncio.to_thread(
        _request_payload, api_key, target_date
    )
    return normalize_prices(payload, target_date)


async def fetch_redata_prices(target_date: date) -> DailyPrices:
    """Fetch the same official PVPC series from REData without a token."""

    payload = await asyncio.to_thread(_request_redata_payload, target_date)
    return normalize_redata_prices(payload, target_date)


def _validate_daily_prices(data: DailyPrices) -> None:
    if data.source not in SNAPSHOT_SOURCES:
        raise ElectricityError(
            "price snapshot source is invalid",
            code="SNAPSHOT-INVALID",
            retryable=True,
        )
    if len(data.hours) != 24:
        raise ElectricityError(
            "price snapshot does not contain 24 hours",
            code="SNAPSHOT-INVALID",
            retryable=True,
        )
    expected_hours = tuple(range(24))
    actual_hours = tuple(item.hour for item in data.hours)
    if actual_hours != expected_hours or any(
        not item.eur_kwh.is_finite()
        or not Decimal("-1") <= item.eur_kwh <= Decimal("5")
        for item in data.hours
    ):
        raise ElectricityError(
            "price snapshot contains invalid hourly values",
            code="SNAPSHOT-INVALID",
            retryable=True,
        )
    if all(item.eur_kwh == 0 for item in data.hours):
        raise ElectricityError(
            "official PVPC source returned an all-zero day",
            code="ZERO-DAY",
            retryable=True,
        )


def _write_price_snapshot(path: Path, data: DailyPrices) -> None:
    """Atomically store one complete normalized official PVPC day."""

    _validate_daily_prices(data)
    document = {
        "version": SNAPSHOT_VERSION,
        "source": data.source,
        "indicator_id": INDICATOR_ID,
        "geo_name": "Península",
        "local_date": data.local_date.isoformat(),
        "hours": [
            {
                "hour": item.hour,
                "eur_kwh": str(item.eur_kwh),
            }
            for item in data.hours
        ],
    }
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(
                document,
                output,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError as exc:
        raise ElectricityError(
            "normalized ESIOS snapshot could not be saved",
            code="SNAPSHOT-WRITE",
            retryable=True,
        ) from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _load_price_snapshot(
    path: Path,
    target_date: date,
) -> Optional[DailyPrices]:
    """Load only a complete normalized snapshot for the requested date."""

    if not path.exists():
        return None
    try:
        with path.open("rb") as source:
            payload = source.read(SNAPSHOT_LIMIT_BYTES + 1)
    except OSError as exc:
        raise ElectricityError(
            "normalized ESIOS snapshot could not be read",
            code="SNAPSHOT-READ",
            retryable=True,
        ) from exc
    if len(payload) > SNAPSHOT_LIMIT_BYTES:
        raise ElectricityError(
            "normalized ESIOS snapshot is too large",
            code="SNAPSHOT-INVALID",
            retryable=True,
        )
    try:
        document = json.loads(payload.decode("utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("version") != SNAPSHOT_VERSION
            or document.get("source") not in SNAPSHOT_SOURCES
            or document.get("indicator_id") != INDICATOR_ID
            or document.get("geo_name") != "Península"
        ):
            raise ValueError
        snapshot_date = date.fromisoformat(document["local_date"])
        raw_hours = document["hours"]
        if not isinstance(raw_hours, list) or len(raw_hours) != 24:
            raise ValueError
        hours = []
        for expected_hour, raw in enumerate(raw_hours):
            if (
                not isinstance(raw, dict)
                or raw.get("hour") != expected_hour
                or not isinstance(raw.get("eur_kwh"), str)
                or len(raw["eur_kwh"]) > 32
            ):
                raise ValueError
            hours.append(
                HourlyPrice(
                    expected_hour,
                    Decimal(raw["eur_kwh"]),
                )
            )
        data = DailyPrices(snapshot_date, tuple(hours), document["source"])
        _validate_daily_prices(data)
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        InvalidOperation,
    ) as exc:
        raise ElectricityError(
            "normalized ESIOS snapshot is invalid",
            code="SNAPSHOT-INVALID",
            retryable=True,
        ) from exc
    if snapshot_date != target_date:
        return None
    return data


async def load_or_fetch_prices(
    api_key: str,
    target_date: date,
    snapshot_path: Path,
) -> DailyPrices:
    """Use the stored target day, or fetch, persist, and verify it once."""

    try:
        stored = await asyncio.to_thread(
            _load_price_snapshot, snapshot_path, target_date
        )
    except ElectricityError as exc:
        logging.warning(
            "Ignoring unusable normalized PVPC snapshot [%s]",
            exc.diagnostic_code,
        )
        stored = None
    if stored is not None:
        return stored

    try:
        collected = await fetch_prices(api_key, target_date)
    except ElectricityError as primary_error:
        if not primary_error.retryable:
            raise
        logging.warning(
            "ESIOS PVPC unavailable [%s]; trying official REData fallback",
            primary_error.diagnostic_code,
        )
        collected = await fetch_redata_prices(target_date)
        logging.info(
            "Using official REData PVPC fallback after ESIOS [%s]",
            primary_error.diagnostic_code,
        )
    await asyncio.to_thread(
        _write_price_snapshot, snapshot_path, collected
    )
    verified = await asyncio.to_thread(
        _load_price_snapshot, snapshot_path, target_date
    )
    if verified is None:
        raise ElectricityError(
            "normalized PVPC snapshot has the wrong date",
            code="SNAPSHOT-INVALID",
            retryable=True,
        )
    return verified


def _display_price(value: Decimal) -> Decimal:
    """Use the same precision for visible prices and visible comparisons."""

    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return abs(rounded) if rounded == 0 else rounded


def _price(value: Decimal) -> str:
    return str(_display_price(value)).replace(".", ",")


def _colors(prices: Sequence[HourlyPrice]) -> Dict[int, str]:
    """Split the local day into cheap, middle, and expensive price thirds.

    Boundary ties keep one color. If both boundaries collapse onto the same
    value, that shared level is neutral yellow rather than being split by hour.
    """

    visible_prices = {
        item.hour: _display_price(item.eur_kwh) for item in prices
    }
    ordered = sorted(visible_prices.values())
    if not ordered:
        return {}
    third = len(ordered) // 3
    if third == 0:
        return {item.hour: "🟡" for item in prices}
    cheap_boundary = ordered[third - 1]
    expensive_boundary = ordered[-third]
    colors: Dict[int, str] = {}
    for item in prices:
        visible = visible_prices[item.hour]
        if cheap_boundary == expensive_boundary:
            if visible < cheap_boundary:
                colors[item.hour] = "🟢"
            elif visible > expensive_boundary:
                colors[item.hour] = "🔴"
            else:
                colors[item.hour] = "🟡"
        elif visible <= cheap_boundary:
            colors[item.hour] = "🟢"
        elif visible >= expensive_boundary:
            colors[item.hour] = "🔴"
        else:
            colors[item.hour] = "🟡"
    return colors


def _best_green_window(
    prices: Sequence[HourlyPrice],
    colors: Dict[int, str],
) -> Optional[Tuple[int, int]]:
    """Choose the longest continuous run of the day's green hours."""

    windows = []
    start = None
    for index, item in enumerate(prices):
        if colors.get(item.hour) == "🟢":
            if start is None:
                start = index
            continue
        if start is not None:
            windows.append((start, index))
            start = None
    if start is not None:
        windows.append((start, len(prices)))
    if not windows:
        return None
    first, last = min(
        windows,
        key=lambda window: (
            -(window[1] - window[0]),
            sum(
                (
                    _display_price(item.eur_kwh)
                    for item in prices[window[0]:window[1]]
                ),
                Decimal(0),
            ),
            prices[window[0]].hour,
        ),
    )
    return prices[first].hour, prices[last - 1].hour + 1


def _extreme_windows(
    prices: Sequence[HourlyPrice],
    *,
    cheapest: bool,
) -> Tuple[Decimal, Tuple[Tuple[int, int], ...]]:
    """Return every continuous window at the visible daily extreme."""

    visible = tuple(
        (item.hour, _display_price(item.eur_kwh)) for item in prices
    )
    target = (min if cheapest else max)(value for _, value in visible)
    windows = []
    start = None
    previous = None
    for hour, value in sorted(visible):
        if value == target:
            if start is None or previous is None or hour != previous + 1:
                if start is not None and previous is not None:
                    windows.append((start, previous + 1))
                start = hour
            previous = hour
            continue
        if start is not None and previous is not None:
            windows.append((start, previous + 1))
            start = None
            previous = None
    if start is not None and previous is not None:
        windows.append((start, previous + 1))
    return target, tuple(windows)


def _window_label(windows: Sequence[Tuple[int, int]]) -> str:
    return ", ".join(
        f"{start:02d}:00–{end:02d}:00" for start, end in windows
    )


def build_price_message(
    data: DailyPrices,
    *,
    day_context: str = "tomorrow",
) -> str:
    if day_context not in {"today", "tomorrow"}:
        raise ValueError("day_context must be today or tomorrow")
    colors = _colors(data.hours)
    cheapest_price, cheapest_windows = _extreme_windows(
        data.hours, cheapest=True
    )
    expensive_price, expensive_windows = _extreme_windows(
        data.hours, cheapest=False
    )
    best_window = _best_green_window(data.hours, colors)
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
    recommendation = ""
    if day_context == "tomorrow" and best_window is not None:
        best_start, best_end = best_window
        recommendation = (
            "\n\n💡 Энергоёмкие дела лучше запланировать "
            f"на период с {best_start:02d}:00 до {best_end:02d}:00."
        )
    if cheapest_price == expensive_price:
        extremes = (
            "🟡 <b>Одинаковая цена весь день</b>\n"
            f"00:00–24:00 · {_price(cheapest_price)} €/кВт·ч"
        )
    else:
        extremes = (
            "🟢 <b>Выгоднее всего</b>\n"
            f"{_window_label(cheapest_windows)} · "
            f"{_price(cheapest_price)} €/кВт·ч\n\n"
            "🔴 <b>Дороже всего</b>\n"
            f"{_window_label(expensive_windows)} · "
            f"{_price(expensive_price)} €/кВт·ч"
        )
    title_day = "сегодня" if day_context == "today" else "завтра"
    return with_footer(
        f"⚡ <b>Цены на электричество {title_day}</b>\n"
        f"{weekday.capitalize()}, {data.local_date.day} {months[data.local_date.month]}\n\n"
        "🕐 <b>По часам</b>\n"
        f"<pre>{table}</pre>\n\n"
        f"{extremes}"
        f"{recommendation}"
    )


def build_explanation_message() -> str:
    return with_footer(
        "💡 <b>Как читать таблицу</b>\n\n"
        "Это почасовая цена электроэнергии на конкретную дату. "
        "Она помогает выбрать время для стирки, нагрева воды, зарядки "
        "автомобиля и других энергоёмких дел.\n\n"
        "🟢 Самые дешёвые часы этого дня\n"
        "🟡 Средние по цене часы\n"
        "🔴 Самые дорогие часы этого дня\n\n"
        "Цвета сравнивают часы только между собой в пределах одного дня. "
        "🟢 не означает, что электричество дешёвое вообще, а 🔴 — что цена "
        "необычно высокая по сравнению с другими днями.\n\n"
        "PVPC — регулируемый тариф на электричество в Испании. Проверить "
        "свой тариф можно в счёте: в типе договора должно быть указано "
        "PVPC.\n\n"
        "Таблица показывает почасовую стоимость потреблённой энергии для "
        "тарифа PVPC 2.0TD. Цена меняется каждый час вслед за оптовым "
        "рынком: на неё влияют спрос, объём солнечной и ветровой энергии "
        "и стоимость работы энергосистемы.\n\n"
        "Это не окончательная стоимость: отдельно учитываются "
        "мощность, налоги и другие платежи.\n\n"
        "Если у вас фиксированный тариф, эти почасовые цены не "
        "применяются.\n\n"
        "Источник: Red Eléctrica (ESIOS / REData)"
    )


async def publish_prices(
    target_date: date,
    state,
    collect: Callable[[], Awaitable[DailyPrices]],
    send_main: Callable[[str, Optional[int]], Awaitable[int]],
    send_explanation: Callable[[str], Awaitable[int]],
    *,
    day_context: str = "tomorrow",
) -> str:
    """Publish one daily table under one persistent explanation anchor."""

    if day_context not in {"today", "tomorrow"}:
        raise ValueError("day_context must be today or tomorrow")

    with state.exclusive_run():
        if state.is_published(target_date):
            return "duplicate"
        data = await collect()
        if data.local_date != target_date:
            raise ElectricityError(
                "official PVPC source returned the wrong local date",
                code="WRONG-DATE",
                retryable=True,
            )
        explanation_id = state.electricity_explanation_message_id()
        if explanation_id is None:
            explanation_id = await send_explanation(
                build_explanation_message()
            )
            state.mark_electricity_explanation(explanation_id)
        await send_main(
            build_price_message(data, day_context=day_context), explanation_id
        )
        state.mark_electricity_published(target_date)
        return "success"
