"""Collect and publish user-facing transport change notifications."""

import asyncio
import html
import json
import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .airport_schedule import (
    AirportSchedule,
    AirportScheduleError,
    AirportScheduleState,
    fetch_schedule,
)
from .branding import FOOTER, with_footer
from .pinned import DEFAULT_PINNED_STATE_PATH, PinnedGuideState, telegram_message_link
from .telegram import TelegramError, send_message

STATE_VERSION = 1
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
LINE_NUMBERS = {"line_1": "1", "line_2": "2"}
MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


class TransportNotificationError(RuntimeError):
    """Safe failure while collecting or publishing transport changes."""


def _pinned_state_path() -> Path:
    return Path(
        os.environ.get("PINNED_GUIDE_STATE_PATH", DEFAULT_PINNED_STATE_PATH)
    )


def _notification_state_path() -> Path:
    pinned = _pinned_state_path()
    return Path(
        os.environ.get(
            "TRANSPORT_NOTIFICATION_STATE_PATH",
            str(pinned.with_name("transport_notifications.json")),
        )
    )


def _empty_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "urban": {},
        "fare": None,
        "airport_next": None,
        "pending": None,
        "delivery_state": "idle",
        "last_message_id": None,
    }


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _decode_airport_baseline(
    raw: Any,
) -> Tuple[date, Tuple[str, ...], Tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise TransportNotificationError(
            "airport notification baseline is invalid"
        )
    try:
        service_date = date.fromisoformat(raw["service_date"])
        to_airport = tuple(raw["to_airport"])
        from_airport = tuple(raw["from_airport"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransportNotificationError(
            "airport notification baseline is invalid"
        ) from exc
    if (
        not all(isinstance(value, str) for value in to_airport)
        or not all(isinstance(value, str) for value in from_airport)
    ):
        raise TransportNotificationError(
            "airport notification baseline is invalid"
        )
    return service_date, to_airport, from_airport


def _validate_state(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        raise TransportNotificationError(
            "transport notification state is invalid"
        )
    if raw.get("delivery_state") not in {"idle", "uncertain"}:
        raise TransportNotificationError(
            "transport notification delivery state is invalid"
        )

    urban = raw.get("urban")
    if not isinstance(urban, dict):
        raise TransportNotificationError(
            "transport notification urban state is invalid"
        )
    normalized_urban = {}
    for key, value in urban.items():
        if (
            key not in LINE_NUMBERS
            or not isinstance(value, dict)
            or not _is_sha256(value.get("pdf_sha256"))
            or not _is_sha256(value.get("image_sha256"))
        ):
            raise TransportNotificationError(
                "transport notification urban state is invalid"
            )
        normalized_urban[key] = {
            "pdf_sha256": value["pdf_sha256"],
            "image_sha256": value["image_sha256"],
        }

    fare = raw.get("fare")
    normalized_fare = None
    if fare is not None:
        if (
            not isinstance(fare, dict)
            or not isinstance(fare.get("cents"), int)
            or not 100 <= fare["cents"] <= 2_000
            or not isinstance(fare.get("effective_date"), str)
            or not _is_sha256(fare.get("pdf_sha256"))
        ):
            raise TransportNotificationError(
                "transport notification fare state is invalid"
            )
        try:
            date.fromisoformat(fare["effective_date"])
        except ValueError as exc:
            raise TransportNotificationError(
                "transport notification fare date is invalid"
            ) from exc
        normalized_fare = dict(fare)

    airport_next = raw.get("airport_next")
    if airport_next is not None:
        _decode_airport_baseline(airport_next)

    pending = raw.get("pending")
    if pending is not None and not isinstance(pending, dict):
        raise TransportNotificationError(
            "transport notification pending state is invalid"
        )

    last_message_id = raw.get("last_message_id")
    if last_message_id is not None and (
        not isinstance(last_message_id, int) or last_message_id <= 0
    ):
        raise TransportNotificationError(
            "transport notification message id is invalid"
        )

    return {
        "version": STATE_VERSION,
        "urban": normalized_urban,
        "fare": normalized_fare,
        "airport_next": None if airport_next is None else dict(airport_next),
        "pending": None if pending is None else dict(pending),
        "delivery_state": raw["delivery_state"],
        "last_message_id": last_message_id,
    }


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportNotificationError(
            "transport notification state is unreadable"
        ) from exc
    return _validate_state(raw)


def save_state(path: Path, state: Dict[str, Any]) -> None:
    normalized = _validate_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
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


def _fare_snapshot(
    schedule: Optional[AirportSchedule],
) -> Optional[Dict[str, Any]]:
    if schedule is None or schedule.fare is None:
        return None
    return {
        "cents": schedule.fare.cents,
        "effective_date": schedule.fare.effective_date.isoformat(),
        "pdf_sha256": schedule.fare.pdf_sha256,
    }


def _airport_baseline(schedule: AirportSchedule) -> Dict[str, Any]:
    return {
        "service_date": schedule.service_date.isoformat(),
        "to_airport": list(schedule.to_airport),
        "from_airport": list(schedule.from_airport),
    }


def _airport_diff(
    previous: Optional[Dict[str, Any]],
    current: Optional[AirportSchedule],
    today: date,
) -> Optional[Dict[str, Any]]:
    if previous is None or current is None or current.service_date != today:
        return None
    previous_date, old_to, old_from = _decode_airport_baseline(previous)
    if previous_date != today:
        return None

    added_to = [value for value in current.to_airport if value not in old_to]
    removed_to = [value for value in old_to if value not in current.to_airport]
    added_from = [
        value for value in current.from_airport if value not in old_from
    ]
    removed_from = [
        value for value in old_from if value not in current.from_airport
    ]
    if not any((added_to, removed_to, added_from, removed_from)):
        return None
    return {
        "service_date": today.isoformat(),
        "added_to": added_to,
        "removed_to": removed_to,
        "added_from": added_from,
        "removed_from": removed_from,
    }


def _merge_pending(
    existing: Optional[Dict[str, Any]],
    today: date,
    urban_lines: List[str],
    airport: Optional[Dict[str, Any]],
    fare: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if (
        existing is not None
        and existing.get("created_date") != today.isoformat()
    ):
        raise TransportNotificationError(
            "an older transport notification is still pending"
        )
    if not urban_lines and airport is None and fare is None:
        return existing

    if existing is None:
        return {
            "created_date": today.isoformat(),
            "urban_lines": list(urban_lines),
            "airport": airport,
            "fare": fare,
        }

    merged_lines = list(
        dict.fromkeys([*existing.get("urban_lines", []), *urban_lines])
    )
    return {
        "created_date": today.isoformat(),
        "urban_lines": merged_lines,
        "airport": airport or existing.get("airport"),
        "fare": fare or existing.get("fare"),
    }


def collect_changes(
    now: datetime,
    pinned_payload: Dict[str, Any],
    airport_schedule: Optional[AirportSchedule],
    state: Dict[str, Any],
    tomorrow_schedule: Optional[AirportSchedule],
) -> Dict[str, Any]:
    """Update baselines and queue only changes that can be stated safely."""

    if state["delivery_state"] == "uncertain":
        raise TransportNotificationError(
            "previous transport notification delivery is uncertain"
        )

    today = now.date()
    new_urban = []
    urban_state = dict(state["urban"])
    line_payload = pinned_payload.get("lines", {})
    if not isinstance(line_payload, dict):
        raise TransportNotificationError(
            "pinned transport line state is invalid"
        )

    for key in LINE_NUMBERS:
        current = line_payload.get(key)
        if not isinstance(current, dict):
            continue
        pdf_sha = current.get("pdf_sha256")
        image_sha = current.get("image_sha256")
        if not _is_sha256(pdf_sha) or not _is_sha256(image_sha):
            continue

        previous = urban_state.get(key)
        if (
            isinstance(previous, dict)
            and previous.get("image_sha256") != image_sha
        ):
            new_urban.append(key)
        urban_state[key] = {
            "pdf_sha256": pdf_sha,
            "image_sha256": image_sha,
        }

    airport_event = _airport_diff(
        state.get("airport_next"),
        airport_schedule,
        today,
    )

    current_fare = _fare_snapshot(airport_schedule)
    previous_fare = state.get("fare")
    fare_event = None
    if (
        current_fare is not None
        and isinstance(previous_fare, dict)
        and previous_fare.get("cents") != current_fare["cents"]
    ):
        fare_event = {
            "old_cents": previous_fare["cents"],
            "new_cents": current_fare["cents"],
            "effective_date": current_fare["effective_date"],
        }

    airport_next = None
    if (
        tomorrow_schedule is not None
        and tomorrow_schedule.service_date == today + timedelta(days=1)
    ):
        airport_next = _airport_baseline(tomorrow_schedule)

    updated = dict(state)
    updated["urban"] = urban_state
    if current_fare is not None:
        updated["fare"] = current_fare
    updated["airport_next"] = airport_next
    updated["pending"] = _merge_pending(
        state.get("pending"),
        today,
        new_urban,
        airport_event,
        fare_event,
    )
    return _validate_state(updated)


def _format_amount(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d} €"


def _format_date(value: date) -> str:
    return f"{value.day} {MONTHS_RU[value.month - 1]}"


def _join_times(values: List[str]) -> str:
    rendered = [f"<b>{html.escape(value)}</b>" for value in values]
    if len(rendered) <= 1:
        return "".join(rendered)
    if len(rendered) == 2:
        return f"{rendered[0]} и {rendered[1]}"
    return ", ".join(rendered[:-1]) + f" и {rendered[-1]}"


def _flight_change_sentences(event: Dict[str, Any]) -> List[str]:
    lines = []
    added_to = list(event.get("added_to", []))
    removed_to = list(event.get("removed_to", []))
    added_from = list(event.get("added_from", []))
    removed_from = list(event.get("removed_from", []))

    if added_to:
        if len(added_to) == 1:
            lines.append(
                "Добавлен рейс из Гуардамара в аэропорт в "
                f"{_join_times(added_to)}."
            )
        else:
            lines.append(
                "Добавлены рейсы из Гуардамара в аэропорт в "
                f"{_join_times(added_to)}."
            )
    if removed_to:
        noun = "Рейса" if len(removed_to) == 1 else "Рейсов"
        lines.append(
            f"{noun} из Гуардамара в аэропорт в {_join_times(removed_to)} "
            "больше нет."
        )
    if added_from:
        if len(added_from) == 1:
            lines.append(
                "Добавлен рейс из аэропорта в Гуардамар в "
                f"{_join_times(added_from)}."
            )
        else:
            lines.append(
                "Добавлены рейсы из аэропорта в Гуардамар в "
                f"{_join_times(added_from)}."
            )
    if removed_from:
        noun = "Рейса" if len(removed_from) == 1 else "Рейсов"
        lines.append(
            f"{noun} из аэропорта в Гуардамар в {_join_times(removed_from)} "
            "больше нет."
        )
    return lines


def build_message(
    pending: Dict[str, Any],
    transport_link: str,
    today: date,
) -> str:
    """Render one calm editorial notification for all queued changes."""

    blocks = ["🚌 <b>Транспорт · изменения</b>"]

    urban_lines = [
        key for key in pending.get("urban_lines", []) if key in LINE_NUMBERS
    ]
    if len(urban_lines) == 1:
        number = LINE_NUMBERS[urban_lines[0]]
        blocks.append(
            "Муниципалитет опубликовал новое расписание "
            f"<b>автобуса №{number}</b>.\n\n"
            "Если пользуетесь этой линией, перед следующей поездкой "
            "стоит свериться с новым расписанием."
        )
    elif len(urban_lines) > 1:
        numbers = " и ".join(
            f"№{LINE_NUMBERS[key]}" for key in urban_lines
        )
        blocks.append(
            "Муниципалитет опубликовал новые расписания "
            f"<b>автобусов {numbers}</b>.\n\n"
            "Если пользуетесь этими линиями, перед следующей поездкой "
            "стоит свериться с новыми расписаниями."
        )

    airport = pending.get("airport")
    if isinstance(airport, dict):
        sentences = _flight_change_sentences(airport)
        if sentences:
            blocks.append(
                "Обновилось расписание автобуса между Гуардамаром и "
                "аэропортом Alicante-Elche.\n\n"
                + "\n".join(sentences)
            )

    fare = pending.get("fare")
    if isinstance(fare, dict):
        old_amount = _format_amount(int(fare["old_cents"]))
        new_amount = _format_amount(int(fare["new_cents"]))
        effective_date = date.fromisoformat(fare["effective_date"])
        if effective_date > today:
            price_line = (
                f"С <b>{_format_date(effective_date)}</b> обычный билет "
                f"будет стоить <b>{new_amount}</b> вместо {old_amount}."
            )
        else:
            price_line = (
                f"Обычный билет теперь стоит <b>{new_amount}</b> "
                f"вместо {old_amount}."
            )
        blocks.append(
            "Изменилась стоимость проезда на автобусе между Гуардамаром и "
            "аэропортом Alicante-Elche.\n\n"
            + price_line
        )

    has_schedule = bool(urban_lines) or isinstance(airport, dict)
    has_fare = isinstance(fare, dict)
    if len(blocks) == 1:
        raise TransportNotificationError(
            "pending transport notification is empty"
        )
    if has_schedule and has_fare:
        closing = "Актуальные расписания и тарифы уже размещены"
    elif has_schedule:
        schedule_count = len(urban_lines) + (
            1 if isinstance(airport, dict) else 0
        )
        closing = (
            "Актуальное расписание уже размещено"
            if schedule_count == 1
            else "Актуальные расписания уже размещены"
        )
    else:
        closing = "Актуальная информация уже размещена"

    link = html.escape(transport_link, quote=True)
    blocks.append(
        f'{closing} в разделе <a href="{link}"><b>«Транспорт»</b></a>.'
    )
    message = with_footer("\n\n".join(blocks))
    if len(message) > 4096 or message.count(FOOTER) != 1:
        raise TransportNotificationError(
            "transport notification is not Telegram-safe"
        )
    return message


async def collect() -> None:
    state_path = _notification_state_path()
    state = load_state(state_path)
    if state["delivery_state"] == "uncertain":
        raise TransportNotificationError(
            "previous transport notification delivery is uncertain"
        )

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise TransportNotificationError("TELEGRAM_CHAT_ID is required")

    pinned_path = _pinned_state_path()
    pinned_payload = PinnedGuideState(pinned_path).read_payload(chat_id)
    airport_state = AirportScheduleState(
        pinned_path.with_name("airport_schedule.json")
    )
    try:
        airport_schedule = airport_state.read()
    except Exception as exc:
        raise TransportNotificationError(
            "accepted airport schedule state is invalid"
        ) from exc

    now = datetime.now(GUARDAMAR_TIMEZONE)
    tomorrow_schedule = None
    try:
        result = await asyncio.to_thread(
            fetch_schedule, now.date() + timedelta(days=1)
        )
        tomorrow_schedule = result.schedule
    except AirportScheduleError as exc:
        logging.warning(
            "Tomorrow airport timetable unavailable; exact airport change "
            "detection will skip the next day rather than guess: %s",
            exc,
        )

    updated = collect_changes(
        now,
        pinned_payload,
        airport_schedule,
        state,
        tomorrow_schedule,
    )
    save_state(state_path, updated)
    if updated["pending"] is None:
        logging.info("No public transport changes collected")
    else:
        logging.info("Transport changes collected for 12:30 publication")


async def publish() -> None:
    state_path = _notification_state_path()
    state = load_state(state_path)
    if state["delivery_state"] == "uncertain":
        raise TransportNotificationError(
            "transport notification delivery is uncertain; "
            "inspect Telegram before retrying"
        )

    pending = state.get("pending")
    if pending is None:
        logging.info("No pending transport notification")
        return

    today = datetime.now(GUARDAMAR_TIMEZONE).date()
    if pending.get("created_date") != today.isoformat():
        raise TransportNotificationError(
            "pending transport notification is stale; "
            "refusing automatic publication"
        )

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise TransportNotificationError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required"
        )

    pinned_payload = PinnedGuideState(
        _pinned_state_path()
    ).read_payload(chat_id)
    transport_id = pinned_payload["messages"].get("transport")
    if not isinstance(transport_id, int) or transport_id <= 0:
        raise TransportNotificationError(
            "transport guide message is unavailable"
        )
    transport_link = telegram_message_link(chat_id, transport_id)
    message = build_message(pending, transport_link, today)

    state["delivery_state"] = "uncertain"
    save_state(state_path, state)
    try:
        message_id = await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
            max_attempts=3,
            retry_only_rate_limits=True,
        )
    except TelegramError as exc:
        if exc.server_status == 429:
            state["delivery_state"] = "idle"
            save_state(state_path, state)
        else:
            logging.exception(
                "Transport notification delivery is uncertain; "
                "automatic resend disabled"
            )
        raise

    state["pending"] = None
    state["delivery_state"] = "idle"
    state["last_message_id"] = message_id
    save_state(state_path, state)
    logging.info(
        "Transport notification published as message %d", message_id
    )


async def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect", "publish"))
    args = parser.parse_args()
    if args.command == "collect":
        await collect()
    else:
        await publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
