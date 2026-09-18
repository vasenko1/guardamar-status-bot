"""Semantic notifications for source-backed recurring guide activities."""

import html
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

from .branding import with_footer
from .chess_school import valid_chess_school_snapshot
from .dinamizacion import valid_dinamizacion_snapshot
from .literary_group import valid_literary_group_snapshot
from .pinned import telegram_message_link
from .telegram import TelegramError, send_message

STATE_VERSION = 1
TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/recurring_notifications.json"

_KEYS = ("chess", "literary_group", "dinamizacion")
_META = {
    "chess": ("♟️", "Шахматы"),
    "literary_group": ("✍️", "Литературное творчество"),
    "dinamizacion": ("🤝", "Муниципальные занятия и мастерские"),
}
_GROUP_TITLES = {
    "mindful_movement": "Осознанное движение",
    "mobile": "Как пользоваться смартфоном",
    "recycled_art": "Творчество из переработанных материалов",
    "textile_painting": "Роспись по ткани",
    "senior_hiking": "Прогулки для старшего возраста",
    "senior_memory": "Тренировка памяти",
    "senior_computing": "Компьютерная грамотность",
    "emotions_school": "Школа эмоций",
}
_MONTHS = (
    "",
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


class RecurringNotificationError(RuntimeError):
    """Fail-closed recurring-activity notification error."""


def _state_path() -> Path:
    return Path(
        os.environ.get("RECURRING_NOTIFICATION_STATE_PATH", DEFAULT_STATE_PATH)
    )


def _empty_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "snapshots": {},
        "pending": None,
        "delivery_state": "idle",
        "last_message_id": None,
    }


def _valid_snapshot(key: str, value: Any) -> bool:
    if key == "chess":
        return valid_chess_school_snapshot(value)
    if key == "literary_group":
        return valid_literary_group_snapshot(value)
    if key == "dinamizacion":
        return valid_dinamizacion_snapshot(value)
    return False


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecurringNotificationError(
            "recurring notification state is unreadable"
        ) from exc
    if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
        raise RecurringNotificationError("recurring notification state is invalid")
    snapshots = value.get("snapshots")
    if not isinstance(snapshots, dict) or any(
        key not in _KEYS or not _valid_snapshot(key, snapshot)
        for key, snapshot in snapshots.items()
    ):
        raise RecurringNotificationError(
            "recurring notification baseline is invalid"
        )
    if value.get("delivery_state") not in {"idle", "uncertain"}:
        raise RecurringNotificationError(
            "recurring notification delivery state is invalid"
        )
    pending = value.get("pending")
    if pending is not None:
        if (
            not isinstance(pending, dict)
            or not isinstance(pending.get("created_date"), str)
            or not isinstance(pending.get("events"), list)
            or not pending["events"]
        ):
            raise RecurringNotificationError(
                "recurring notification pending state is invalid"
            )
        try:
            date.fromisoformat(pending["created_date"])
        except ValueError as exc:
            raise RecurringNotificationError(
                "recurring notification pending date is invalid"
            ) from exc
        for event in pending["events"]:
            if (
                not isinstance(event, dict)
                or event.get("key") not in _KEYS
                or not isinstance(event.get("type"), str)
            ):
                raise RecurringNotificationError(
                    "recurring notification event is invalid"
                )
    last_message_id = value.get("last_message_id")
    if last_message_id is not None and (
        not isinstance(last_message_id, int)
        or isinstance(last_message_id, bool)
        or last_message_id <= 0
    ):
        raise RecurringNotificationError(
            "recurring notification message id is invalid"
        )
    return value


def save_state(path: Path, value: Mapping[str, Any]) -> None:
    if value.get("version") != STATE_VERSION:
        raise RecurringNotificationError("recurring notification state is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
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


def _event(key: str, event_type: str, **fields: Any) -> dict:
    value = {"key": key, "type": event_type}
    value.update(fields)
    return value


def _chess_diff(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[dict]:
    events = []
    old_schedule = (
        previous["days"], previous["start_time"], previous["end_time"]
    )
    new_schedule = (
        current["days"], current["start_time"], current["end_time"]
    )
    if old_schedule != new_schedule:
        events.append(_event(
            "chess",
            "schedule",
            start_time=current["start_time"],
            end_time=current["end_time"],
        ))
    old_levels = (previous["level_from"], previous["level_to"])
    new_levels = (current["level_from"], current["level_to"])
    if old_levels != new_levels:
        events.append(_event(
            "chess",
            "levels",
            level_from=current["level_from"],
            level_to=current["level_to"],
        ))
    return events


def _literary_diff(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> list[dict]:
    old = (previous["day"], previous["start_time"], previous["end_time"])
    new = (current["day"], current["start_time"], current["end_time"])
    if old == new:
        return []
    return [_event(
        "literary_group",
        "schedule",
        start_time=current["start_time"],
        end_time=current["end_time"],
    )]


def _group_map(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {group["key"]: group for group in snapshot["groups"]}


def _dinamizacion_diff(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> list[dict]:
    if (
        previous["campaign_url"] != current["campaign_url"]
        or previous["season"] != current["season"]
    ):
        return [_event(
            "dinamizacion",
            "new_program",
            season=current["season"],
        )]

    events = []
    if (
        previous["registration_start"] != current["registration_start"]
        or previous["registration_end"] != current["registration_end"]
    ):
        events.append(_event(
            "dinamizacion",
            "registration_window",
            start=current["registration_start"],
            end=current["registration_end"],
        ))
    if previous["registration_until_full"] != current["registration_until_full"]:
        events.append(_event(
            "dinamizacion",
            "until_full",
            value=bool(current["registration_until_full"]),
        ))
    if previous["resident_priority"] != current["resident_priority"]:
        events.append(_event(
            "dinamizacion",
            "resident_priority",
            value=bool(current["resident_priority"]),
        ))

    old_groups = _group_map(previous)
    for group in current["groups"]:
        key = group["key"]
        old = old_groups.get(key)
        if old is None:
            events.append(_event(
                "dinamizacion",
                "new_group",
                group=key,
                schedules=list(group["schedules"]),
                start_date=group.get("start_date"),
                end_date=group.get("end_date"),
            ))
            continue
        if old["schedules"] != group["schedules"]:
            events.append(_event(
                "dinamizacion",
                "group_schedule",
                group=key,
                schedules=list(group["schedules"]),
            ))
        if (
            old.get("start_date") != group.get("start_date")
            or old.get("end_date") != group.get("end_date")
        ):
            events.append(_event(
                "dinamizacion",
                "group_dates",
                group=key,
                start_date=group.get("start_date"),
                end_date=group.get("end_date"),
            ))
    # Missing rows alone are deliberately ignored: disappearance is not proof
    # of cancellation.
    return events


def semantic_diff(
    key: str,
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> list[dict]:
    if key == "chess":
        return _chess_diff(previous, current)
    if key == "literary_group":
        return _literary_diff(previous, current)
    if key == "dinamizacion":
        return _dinamizacion_diff(previous, current)
    raise RecurringNotificationError("unknown recurring notification key")


def collect_changes(
    current: Mapping[str, Mapping[str, Any]],
    state: Dict[str, Any],
    local_day: date,
) -> Dict[str, Any]:
    """Advance silent baselines and queue at most one batched change message."""

    if state.get("delivery_state") == "uncertain":
        raise RecurringNotificationError(
            "previous recurring notification delivery is uncertain"
        )
    updated = dict(state)
    baselines = dict(state.get("snapshots", {}))
    pending = state.get("pending")
    if pending is not None and pending.get("created_date") != local_day.isoformat():
        updated["pending"] = None
        pending = None
    if pending is not None:
        return updated

    events = []
    for key in _KEYS:
        snapshot = current.get(key)
        if snapshot is None:
            continue
        if not _valid_snapshot(key, snapshot):
            raise RecurringNotificationError(
                f"accepted recurring snapshot is invalid: {key}"
            )
        previous = baselines.get(key)
        if previous is not None:
            events.extend(semantic_diff(key, previous, snapshot))
        baselines[key] = snapshot

    updated["snapshots"] = baselines
    if events:
        updated["pending"] = {
            "created_date": local_day.isoformat(),
            "events": events,
        }
    return updated


def _date_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {_MONTHS[parsed.month]}"


def _card_link(
    chat_id: str,
    messages: Mapping[str, int],
    key: str,
    snapshots: Mapping[str, Mapping[str, Any]],
) -> str:
    message_id = messages.get(key)
    if isinstance(message_id, int) and message_id > 0:
        return telegram_message_link(chat_id, message_id)
    snapshot = snapshots[key]
    if key == "dinamizacion":
        return str(snapshot["campaign_url"])
    return str(snapshot["source_url"])


def _group_dates(event: Mapping[str, Any]) -> str:
    start = _date_label(event.get("start_date"))
    end = _date_label(event.get("end_date"))
    if start and end:
        return f"{start} — {end}"
    if start:
        return f"с {start}"
    return ""


def _event_line(event: Mapping[str, Any]) -> str:
    key = event["key"]
    event_type = event["type"]
    if key == "chess":
        if event_type == "schedule":
            return (
                "• Новое расписание: Вт/Чт · "
                f"{html.escape(str(event['start_time']))}–"
                f"{html.escape(str(event['end_time']))}"
            )
        if event_type == "levels":
            return (
                "• Изменились уровни групп: "
                f"{html.escape(str(event['level_from']))}–"
                f"{html.escape(str(event['level_to']))}"
            )
    if key == "literary_group" and event_type == "schedule":
        return (
            "• Новое расписание: каждый вторник · "
            f"{html.escape(str(event['start_time']))}–"
            f"{html.escape(str(event['end_time']))}"
        )
    if key == "dinamizacion":
        if event_type == "new_program":
            return f"• Опубликована программа {html.escape(str(event['season']))}"
        if event_type == "registration_window":
            return (
                "• Изменились даты основной записи: "
                f"{_date_label(event['start'])} — {_date_label(event['end'])}"
            )
        if event_type == "until_full":
            return (
                "• После основного срока запись может продолжаться до заполнения мест"
                if event["value"]
                else "• Убрано условие записи до заполнения мест"
            )
        if event_type == "resident_priority":
            return (
                "• Указан приоритет жителей Guardamar"
                if event["value"]
                else "• Изменено условие приоритета жителей Guardamar"
            )
        group = _GROUP_TITLES.get(str(event.get("group")), str(event.get("group")))
        if event_type == "new_group":
            schedules = "; ".join(event["schedules"])
            dates = _group_dates(event)
            suffix = f" · {dates}" if dates else ""
            return (
                f"• Новая группа: <b>{html.escape(group)}</b> — "
                f"{html.escape(schedules)}{suffix}"
            )
        if event_type == "group_schedule":
            schedules = "; ".join(event["schedules"])
            return (
                f"• <b>{html.escape(group)}</b>: новое расписание — "
                f"{html.escape(schedules)}"
            )
        if event_type == "group_dates":
            dates = _group_dates(event)
            return (
                f"• <b>{html.escape(group)}</b>: изменились даты"
                + (f" — {dates}" if dates else "")
            )
    raise RecurringNotificationError("unknown recurring notification event")


def build_message(
    pending: Mapping[str, Any],
    chat_id: str,
    messages: Mapping[str, int],
    snapshots: Mapping[str, Mapping[str, Any]],
) -> str:
    grouped: Dict[str, list[Mapping[str, Any]]] = {}
    for event in pending["events"]:
        grouped.setdefault(event["key"], []).append(event)

    lines = ["📚 <b>Занятия и секции · изменения</b>"]
    for key in _KEYS:
        events = grouped.get(key)
        if not events:
            continue
        emoji, label = _META[key]
        link = html.escape(
            _card_link(chat_id, messages, key, snapshots),
            quote=True,
        )
        lines.extend([
            "",
            f'{emoji} <a href="{link}"><b>{html.escape(label)}</b></a>',
        ])
        lines.extend(_event_line(event) for event in events)
    message = with_footer("\n".join(lines))
    if len(message) > 4096:
        raise RecurringNotificationError(
            "recurring notification message exceeds Telegram limit"
        )
    return message


async def sync_recurring_notifications(
    bot_token: str,
    chat_id: str,
    snapshots: Mapping[str, Mapping[str, Any]],
    messages: Mapping[str, int],
    now: datetime,
) -> str:
    """Persist baseline before any irreversible Telegram send."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("notification time must be timezone-aware")
    local_day = now.astimezone(TIMEZONE).date()
    path = _state_path()
    state = load_state(path)
    updated = collect_changes(snapshots, state, local_day)
    save_state(path, updated)

    pending = updated.get("pending")
    if pending is None:
        return "baseline" if not state.get("snapshots") else "no-changes"

    message = build_message(pending, chat_id, messages, updated["snapshots"])
    sending = dict(updated)
    sending["delivery_state"] = "uncertain"
    save_state(path, sending)
    try:
        message_id = await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
            retry_only_rate_limits=True,
        )
    except TelegramError as exc:
        if exc.status == 429:
            retryable = dict(sending)
            retryable["delivery_state"] = "idle"
            save_state(path, retryable)
        raise

    completed = dict(sending)
    completed["delivery_state"] = "idle"
    completed["pending"] = None
    completed["last_message_id"] = message_id
    save_state(path, completed)
    return "published"
