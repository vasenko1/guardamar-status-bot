"""Collect and publish user-facing transport change notifications."""

import argparse
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
from .state import PublicationState, StateError
from .telegram import TelegramError, send_message

STATE_VERSION = 1
TIMEZONE = ZoneInfo("Europe/Madrid")
LINE_NUMBERS = {"line_1": "1", "line_2": "2"}
MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


class TransportNotificationError(RuntimeError):
    """Fail-closed transport notification error."""


def _pinned_path() -> Path:
    return Path(
        os.environ.get("PINNED_GUIDE_STATE_PATH", DEFAULT_PINNED_STATE_PATH)
    )


def _state_path() -> Path:
    return Path(
        os.environ.get(
            "TRANSPORT_NOTIFICATION_STATE_PATH",
            str(_pinned_path().with_name("transport_notifications.json")),
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


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportNotificationError(
            "transport notification state is unreadable"
        ) from exc
    if (
        not isinstance(state, dict)
        or state.get("version") != STATE_VERSION
        or state.get("delivery_state") not in {"idle", "uncertain"}
        or not isinstance(state.get("urban"), dict)
        or state.get("pending") is not None
        and not isinstance(state.get("pending"), dict)
    ):
        raise TransportNotificationError(
            "transport notification state is invalid"
        )
    return state


def save_state(path: Path, state: Dict[str, Any]) -> None:
    if state.get("version") != STATE_VERSION:
        raise TransportNotificationError(
            "transport notification state is invalid"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
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


def _airport_snapshot(schedule: AirportSchedule) -> Dict[str, Any]:
    return {
        "service_date": schedule.service_date.isoformat(),
        "to_airport": list(schedule.to_airport),
        "from_airport": list(schedule.from_airport),
    }


def _decode_airport_snapshot(
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


def _airport_diff(
    baseline: Any,
    current: Optional[AirportSchedule],
    today: date,
) -> Optional[Dict[str, Any]]:
    if baseline is None or current is None or current.service_date != today:
        return None
    baseline_date, old_to, old_from = _decode_airport_snapshot(baseline)
    if baseline_date != today:
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


def _merge_pending(
    existing: Optional[Dict[str, Any]],
    today: date,
    urban_lines: List[str],
    airport_event: Optional[Dict[str, Any]],
    fare_event: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    # Missed 12:30 publication expires silently next morning. Stale notices are
    # less useful than a delayed surprise, and this keeps the subsystem self-healing.
    if (
        existing is not None
        and existing.get("created_date") != today.isoformat()
    ):
        existing = None
    if not urban_lines and airport_event is None and fare_event is None:
        return existing
    if existing is None:
        return {
            "created_date": today.isoformat(),
            "urban_lines": list(urban_lines),
            "airport": airport_event,
            "fare": fare_event,
        }
    return {
        "created_date": today.isoformat(),
        "urban_lines": list(
            dict.fromkeys([*existing.get("urban_lines", []), *urban_lines])
        ),
        "airport": airport_event or existing.get("airport"),
        "fare": fare_event or existing.get("fare"),
    }


def collect_changes(
    now: datetime,
    pinned_payload: Dict[str, Any],
    airport_schedule: Optional[AirportSchedule],
    state: Dict[str, Any],
    tomorrow_schedule: Optional[AirportSchedule],
) -> Dict[str, Any]:
    """Collect only changes supported by accepted source data."""

    if state["delivery_state"] == "uncertain":
        raise TransportNotificationError(
            "previous transport notification delivery is uncertain"
        )
    today = now.date()

    new_urban = []
    urban_state = dict(state.get("urban", {}))
    lines = pinned_payload.get("lines", {})
    if not isinstance(lines, dict):
        raise TransportNotificationError(
            "pinned transport line state is invalid"
        )
    for key in LINE_NUMBERS:
        current = lines.get(key)
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
        state.get("airport_next"), airport_schedule, today
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
        airport_next = _airport_snapshot(tomorrow_schedule)

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
    return updated


def _amount(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d} €"


def _date_label(value: date) -> str:
    return f"{value.day} {MONTHS_RU[value.month - 1]}"


def _times(values: List[str]) -> str:
    rendered = [f"<b>{html.escape(value)}</b>" for value in values]
    if len(rendered) < 2:
        return "".join(rendered)
    if len(rendered) == 2:
        return f"{rendered[0]} и {rendered[1]}"
    return ", ".join(rendered[:-1]) + f" и {rendered[-1]}"


def _airport_lines(event: Dict[str, Any]) -> List[str]:
    result = []
    added_to = list(event.get("added_to", []))
    removed_to = list(event.get("removed_to", []))
    added_from = list(event.get("added_from", []))
    removed_from = list(event.get("removed_from", []))

    if added_to:
        prefix = (
            "Добавлен рейс" if len(added_to) == 1 else "Добавлены рейсы"
        )
        result.append(
            f"{prefix} из Гуардамара в аэропорт в {_times(added_to)}."
        )
    if removed_to:
        prefix = "Рейса" if len(removed_to) == 1 else "Рейсов"
        result.append(
            f"{prefix} из Гуардамара в аэропорт в {_times(removed_to)} "
            "больше нет."
        )
    if added_from:
        prefix = (
            "Добавлен рейс" if len(added_from) == 1 else "Добавлены рейсы"
        )
        result.append(
            f"{prefix} из аэропорта в Гуардамар в {_times(added_from)}."
        )
    if removed_from:
        prefix = "Рейса" if len(removed_from) == 1 else "Рейсов"
        result.append(
            f"{prefix} из аэропорта в Гуардамар в {_times(removed_from)} "
            "больше нет."
        )
    return result


def build_message(
    pending: Dict[str, Any],
    transport_link: str,
    today: date,
) -> str:
    """Render the agreed calm editorial transport notification."""

    blocks = ["🚌 <b>Транспорт · изменения</b>"]

    urban = [
        key for key in pending.get("urban_lines", []) if key in LINE_NUMBERS
    ]
    if len(urban) == 1:
        blocks.append(
            "Муниципалитет опубликовал новое расписание "
            f"<b>автобуса №{LINE_NUMBERS[urban[0]]}</b>.\n\n"
            "Если пользуетесь этой линией, перед следующей поездкой "
            "стоит свериться с новым расписанием."
        )
    elif len(urban) > 1:
        numbers = " и ".join(
            f"№{LINE_NUMBERS[key]}" for key in urban
        )
        blocks.append(
            "Муниципалитет опубликовал новые расписания "
            f"<b>автобусов {numbers}</b>.\n\n"
            "Если пользуетесь этими линиями, перед следующей поездкой "
            "стоит свериться с новыми расписаниями."
        )

    airport = pending.get("airport")
    airport_lines = (
        _airport_lines(airport) if isinstance(airport, dict) else []
    )
    if airport_lines:
        blocks.append(
            "Обновилось расписание автобуса между Гуардамаром и "
            "аэропортом Alicante-Elche.\n\n"
            + "\n".join(airport_lines)
        )

    fare = pending.get("fare")
    if isinstance(fare, dict):
        effective = date.fromisoformat(fare["effective_date"])
        old = _amount(int(fare["old_cents"]))
        new = _amount(int(fare["new_cents"]))
        if effective > today:
            detail = (
                f"С <b>{_date_label(effective)}</b> обычный билет "
                f"будет стоить <b>{new}</b> вместо {old}."
            )
        else:
            detail = (
                f"Обычный билет теперь стоит <b>{new}</b> вместо {old}."
            )
        blocks.append(
            "Изменилась стоимость проезда на автобусе между Гуардамаром и "
            "аэропортом Alicante-Elche.\n\n"
            + detail
        )

    has_schedule = bool(urban) or bool(airport_lines)
    has_fare = isinstance(fare, dict)
    if len(blocks) == 1:
        raise TransportNotificationError(
            "pending transport notification is empty"
        )
    if has_schedule and has_fare:
        closing = "Актуальные расписания и тарифы уже размещены"
    elif has_schedule:
        schedule_count = len(urban) + (1 if airport_lines else 0)
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
    state_path = _state_path()
    state = load_state(state_path)
    if state["delivery_state"] == "uncertain":
        raise TransportNotificationError(
            "previous transport notification delivery is uncertain"
        )

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise TransportNotificationError("TELEGRAM_CHAT_ID is required")

    pinned_path = _pinned_path()
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

    now = datetime.now(TIMEZONE)
    tomorrow_schedule = None
    try:
        tomorrow_schedule = (
            await asyncio.to_thread(
                fetch_schedule, now.date() + timedelta(days=1)
            )
        ).schedule
    except AirportScheduleError as exc:
        logging.warning(
            "Tomorrow airport timetable unavailable; exact airport change "
            "detection will skip the next day rather than guess: %s",
            exc,
        )

    before = state.get("pending")
    updated = collect_changes(
        now,
        pinned_payload,
        airport_schedule,
        state,
        tomorrow_schedule,
    )
    if (
        before is not None
        and before.get("created_date") != now.date().isoformat()
    ):
        logging.warning(
            "Expired an unpublished transport notification from %s",
            before.get("created_date"),
        )
    save_state(state_path, updated)
    logging.info(
        "Transport notification collection complete: %s",
        "pending" if updated["pending"] is not None else "no changes",
    )


async def publish() -> None:
    state_path = _state_path()
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

    today = datetime.now(TIMEZONE).date()
    if pending.get("created_date") != today.isoformat():
        state["pending"] = None
        save_state(state_path, state)
        logging.warning(
            "Expired stale transport notification without sending"
        )
        return

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise TransportNotificationError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required"
        )

    pinned = PinnedGuideState(_pinned_path()).read_payload(chat_id)
    transport_id = pinned["messages"].get("transport")
    if not isinstance(transport_id, int) or transport_id <= 0:
        raise TransportNotificationError(
            "transport guide message is unavailable"
        )
    message = build_message(
        pending,
        telegram_message_link(chat_id, transport_id),
        today,
    )

    # sendMessage has no idempotency key. Persist uncertainty before sending:
    # a crash after Telegram accepts the message will not cause a duplicate.
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
        # HTTP 429 is an explicit rejection, so no message was accepted.
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
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect", "publish"))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        with PublicationState(_state_path()).exclusive_run():
            if args.command == "collect":
                await collect()
            else:
                await publish()
    except StateError as exc:
        raise TransportNotificationError(
            "another transport notification run is active"
        ) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
