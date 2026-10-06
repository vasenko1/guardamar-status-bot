"""Crash-safe one-off event-access lifecycle.

The external module name is retained for production compatibility.  Source
adapters own evidence and stable identity; this wrapper owns state persistence,
explicit migration, rendering, Telegram delivery and operator recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import html
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterator, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from .branding import with_footer
from .convega import (
    ConvegaSourceError,
    convega_snapshot_is_access_fresh,
    load_convega_access_records,
)
from .event_access import (
    AccessNotice,
    EventAccessDecision,
    EventAccessRecord,
    EventAccessStateError,
    MAX_MESSAGE_LENGTH,
    STATE_VERSION,
    empty_state,
    migrate_v1_state,
    migrate_v2_state,
    plan_event_access_record,
    prune_records,
    temporally_consistent,
    validate_state,
)
from .telegram import (
    TelegramError,
    is_ambiguous_send_failure,
    send_message,
    send_photo_url,
)


LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

DEFAULT_SOURCE_STATE_PATH = Path("state/convega_events.json")
DEFAULT_STATE_PATH = Path("state/event_registration_notifications.json")

RegistrationStateError = EventAccessStateError


class RegistrationDeliveryUncertain(RuntimeError):
    """Telegram may already contain the reserved event-access publication."""


class RegistrationNotificationState:
    def __init__(self, path: Path = DEFAULT_STATE_PATH) -> None:
        self.path = path

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".v1-backup.json")

    @property
    def v2_backup_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".v2-backup.json")

    def _write_migration_backup(
        self,
        raw: Mapping[str, Any],
        backup: Path,
        label: str,
    ) -> None:
        if backup.exists():
            try:
                existing = json.loads(backup.read_text(encoding="utf-8"))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise EventAccessStateError(
                    f"event-access {label} backup is unreadable"
                ) from exc
            if existing != raw:
                raise EventAccessStateError(
                    f"event-access {label} backup collision"
                )
            return

        backup.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{backup.name}.",
            dir=str(backup.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(
                    raw,
                    output,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, backup)
            directory = os.open(str(backup.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def read_raw(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EventAccessStateError(
                "event-access state is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise EventAccessStateError(
                "event-access state must be a JSON object"
            )
        return value

    def read(self) -> Dict[str, Any]:
        value = self.read_raw()
        if value is None:
            return empty_state()
        if value.get("version") in {1, 2}:
            raise EventAccessStateError(
                "legacy event-access state requires migrate-state"
            )
        return validate_state(value)

    def _write(self, value: Mapping[str, Any]) -> None:
        checked = validate_state(dict(value))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(
                    checked,
                    output,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise EventAccessStateError(
                    "another event-access run is active"
                ) from exc
            yield

    def migrate(self) -> str:
        with self.exclusive_run():
            raw = self.read_raw()
            if raw is None:
                self._write(empty_state())
                return "created_v3"
            version = raw.get("version")
            if version == STATE_VERSION:
                validate_state(raw)
                return "already_v3"
            if version == 1:
                migrated = migrate_v1_state(raw)
                self._write_migration_backup(
                    raw,
                    self.backup_path,
                    "v1",
                )
                result = "migrated_v1_to_v3"
            elif version == 2:
                migrated = migrate_v2_state(raw)
                self._write_migration_backup(
                    raw,
                    self.v2_backup_path,
                    "v2",
                )
                result = "migrated_v2_to_v3"
            else:
                raise EventAccessStateError(
                    "event-access state version cannot be migrated"
                )
            self._write(migrated)
            return result

    def reserve(
        self,
        current: Mapping[str, Any],
        record_id: str,
        operation: str,
        message: str,
        candidate_record: Mapping[str, Any],
        now: datetime,
    ) -> None:
        if current.get("uncertain") is not None:
            raise EventAccessStateError(
                "event-access delivery is already uncertain"
            )
        value = {
            "version": STATE_VERSION,
            "records": {
                key: dict(item)
                for key, item in current["records"].items()
            },
            "uncertain": {
                "created_at": now.isoformat(),
                "record_id": record_id,
                "operation": operation,
                "message": message,
                "candidate_record": dict(candidate_record),
            },
        }
        self._write(value)

    def clear_uncertain(self) -> Dict[str, Any]:
        value = self.read()
        if value["uncertain"] is None:
            raise EventAccessStateError(
                "no uncertain event-access delivery"
            )
        value["uncertain"] = None
        self._write(value)
        return value

    def confirm_uncertain(
        self,
        root_message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        value = self.read()
        pending = value["uncertain"]
        if pending is None:
            raise EventAccessStateError(
                "no uncertain event-access delivery"
            )
        candidate = dict(pending["candidate_record"])
        if pending["operation"] == "root":
            if (
                not isinstance(root_message_id, int)
                or isinstance(root_message_id, bool)
                or root_message_id <= 0
            ):
                raise EventAccessStateError(
                    "root resolution requires a positive Telegram message ID"
                )
            candidate["root_message_id"] = root_message_id
            candidate["audience_known"] = True
        value["records"][pending["record_id"]] = candidate
        value["uncertain"] = None
        self._write(value)
        return value

    def write(self, value: Mapping[str, Any]) -> None:
        self._write(value)


def _format_date(value: date) -> str:
    months = (
        "",
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
    return f"{value.day} {months[value.month]}"


def _option(record: EventAccessRecord, option_id: str):
    for option in record.options:
        if option.option_id == option_id:
            return option
    raise ValueError("event-access notice references unknown option")


def _action_label(record: EventAccessRecord) -> str:
    if record.access_kind == "reservation":
        return "Забронировать"
    if record.access_kind == "ticket":
        return "Получить билет"
    return "Записаться"


def _action_line(record: EventAccessRecord, option_id: str) -> Optional[str]:
    option = _option(record, option_id)
    if option.status != "open":
        return None
    if option.action_url:
        return (
            "📝 <a href=\""
            + html.escape(option.action_url, quote=True)
            + "\">"
            + _action_label(record)
            + "</a>"
        )
    if option.action_text:
        return "📝 " + html.escape(option.action_text)
    return None


def _deadline_text(record: EventAccessRecord, option_id: str) -> Optional[str]:
    option = _option(record, option_id)
    if option.closes_on is None:
        return None
    result = _format_date(option.closes_on)
    if option.closes_time is not None:
        result += ", " + option.closes_time.strftime("%H:%M")
    if option.until_full:
        result += ", если места не закончатся раньше"
    return result


_ACCESS_COPY = {
    "registration": {
        "active": "📝 <b>Открыта регистрация</b>",
        "open": "📝 <b>Регистрация открыта</b>",
        "reopened": "📝 <b>Регистрация снова открыта</b>",
        "closed": "📝 <b>Регистрация закрыта</b>",
        "deadline-known": "⏳ <b>Появился срок регистрации</b>",
        "deadline-changed": "⏳ <b>Срок регистрации изменён</b>",
        "opening-tomorrow": "📝 <b>Завтра открывается регистрация</b>",
        "opening-today": "📝 <b>Сегодня открывается регистрация</b>",
        "one-day-tomorrow": "📝 <b>Регистрация только завтра</b>",
        "closing-tomorrow": "⏳ <b>Завтра заканчивается регистрация</b>",
        "closing-today": "⏳ <b>Сегодня заканчивается регистрация</b>",
        "action-changed": "📝 <b>Изменился способ регистрации</b>",
        "option-added": "➕ <b>Добавлен новый вариант регистрации</b>",
        "opening-prefix": "Регистрация",
        "deadline-open-prefix": "Записаться можно до ",
        "deadline-unknown-prefix": "Указан срок регистрации: до ",
        "full": "⛔ <b>Мест больше нет</b>",
    },
    "reservation": {
        "active": "📝 <b>Открыто бронирование</b>",
        "open": "📝 <b>Бронирование открыто</b>",
        "reopened": "📝 <b>Бронирование снова открыто</b>",
        "closed": "📝 <b>Бронирование закрыто</b>",
        "deadline-known": "⏳ <b>Появился срок бронирования</b>",
        "deadline-changed": "⏳ <b>Срок бронирования изменён</b>",
        "opening-tomorrow": "📝 <b>Завтра открывается бронирование</b>",
        "opening-today": "📝 <b>Сегодня открывается бронирование</b>",
        "one-day-tomorrow": "📝 <b>Бронирование только завтра</b>",
        "closing-tomorrow": "⏳ <b>Завтра заканчивается бронирование</b>",
        "closing-today": "⏳ <b>Сегодня заканчивается бронирование</b>",
        "action-changed": "📝 <b>Изменился способ бронирования</b>",
        "option-added": "➕ <b>Добавлен новый вариант бронирования</b>",
        "opening-prefix": "Бронирование",
        "deadline-open-prefix": "Забронировать можно до ",
        "deadline-unknown-prefix": "Указан срок бронирования: до ",
        "full": "⛔ <b>Мест больше нет</b>",
    },
    "ticket": {
        "active": "🎟 <b>Билеты доступны</b>",
        "open": "🎟 <b>Продажа билетов открыта</b>",
        "reopened": "🎟 <b>Продажа билетов снова открыта</b>",
        "closed": "🎟 <b>Продажа билетов закрыта</b>",
        "deadline-known": "⏳ <b>Появился срок продажи билетов</b>",
        "deadline-changed": "⏳ <b>Срок продажи билетов изменён</b>",
        "opening-tomorrow": "🎟 <b>Завтра открывается продажа билетов</b>",
        "opening-today": "🎟 <b>Сегодня открывается продажа билетов</b>",
        "one-day-tomorrow": "🎟 <b>Билеты продаются только завтра</b>",
        "closing-tomorrow": "⏳ <b>Завтра заканчивается продажа билетов</b>",
        "closing-today": "⏳ <b>Сегодня заканчивается продажа билетов</b>",
        "action-changed": "🎟 <b>Изменился способ получения билета</b>",
        "option-added": "➕ <b>Добавлен новый вариант билета</b>",
        "opening-prefix": "Продажа билетов",
        "deadline-open-prefix": "Получить билет можно до ",
        "deadline-unknown-prefix": "Указан срок продажи билетов: до ",
        "full": "⛔ <b>Билетов больше нет</b>",
    },
}


def _access_copy(record: EventAccessRecord, key: str) -> str:
    return _ACCESS_COPY[record.access_kind][key]


def _root_heading(record: EventAccessRecord, kind: str) -> str:
    if kind == "event-date-changed":
        return "📅 <b>Дата события изменилась</b>"
    if kind == "event-details-changed":
        return "ℹ️ <b>Изменились данные события</b>"
    if kind == "event-cancelled":
        return "⛔ <b>Событие отменено</b>"
    if kind == "event-postponed":
        return "⏸ <b>Событие перенесено</b>"
    if kind == "event-restored":
        return "✅ <b>Событие снова подтверждено</b>"
    return _access_copy(
        record,
        kind if kind in _ACCESS_COPY[record.access_kind] else "open",
    )


def _option_label_line(
    record: EventAccessRecord,
    option_id: str,
) -> Optional[str]:
    option = _option(record, option_id)
    if len(record.options) <= 1 or not option.label:
        return None
    return "▫️ <b>" + html.escape(option.label) + "</b>"


def _opening_text(record: EventAccessRecord, option_id: str) -> Optional[str]:
    option = _option(record, option_id)
    if option.opens_on is None:
        return None
    result = _format_date(option.opens_on)
    if option.opens_time is not None:
        result += ", " + option.opens_time.strftime("%H:%M")
    prefix = _access_copy(record, "opening-prefix")
    if option.closes_on == option.opens_on:
        return "📝 " + prefix + ": только " + result
    return "📝 " + prefix + ": с " + result


def _event_date_line(record: EventAccessRecord) -> str:
    if (
        record.event_end_date is not None
        and record.event_end_date != record.event_start_date
    ):
        return (
            "📅 "
            + _format_date(record.event_start_date)
            + " — "
            + _format_date(record.event_end_date)
        )
    return "📅 " + _format_date(record.event_start_date)


def render_root(
    record: EventAccessRecord,
    decision: EventAccessDecision,
) -> str:
    if not decision.notices:
        raise ValueError("root publication requires a notice")
    first = decision.notices[0]
    lines = [
        _root_heading(record, first.kind),
        "",
        "<b>" + html.escape(record.title) + "</b>",
        _event_date_line(record),
    ]
    if first.kind in {
        "opening-tomorrow",
        "opening-today",
        "one-day-tomorrow",
    }:
        opening = _opening_text(record, first.option_id)
        if opening is not None:
            lines.append(opening)
    if first.kind in {"deadline-known", "deadline-changed"}:
        deadline = _deadline_text(record, first.option_id)
        if deadline is not None:
            lines.append("⏳ до " + html.escape(deadline))
    if record.route:
        lines.append("🥾 Маршрут: " + html.escape(record.route))
    if record.details:
        lines.append(" • ".join(html.escape(item) for item in record.details))
    if record.schedule_note:
        lines.append("🕐 " + html.escape(record.schedule_note))
    if record.place:
        lines.append("📍 " + html.escape(record.place))

    for option in record.options:
        action = _action_line(record, option.option_id)
        if action is not None:
            lines.append("")
            label = _option_label_line(record, option.option_id)
            if label is not None:
                lines.append(label)
            lines.append(action)
            deadline = _deadline_text(record, option.option_id)
            if deadline is not None:
                lines.append("⏳ до " + html.escape(deadline))
            if option.until_full:
                lines.append("Места ограничены")

    lines.append("")
    lines.append(
        '<a href="'
        + html.escape(record.source_url, quote=True)
        + '">Подробнее</a>'
    )
    message = with_footer("\n".join(lines))
    if not 1 <= len(message) <= MAX_MESSAGE_LENGTH:
        raise ValueError("event-access root exceeds Telegram limit")
    return message


def _reply_block(
    record: EventAccessRecord,
    notice: AccessNotice,
) -> Tuple[str, ...]:
    if notice.kind == "event-date-changed":
        return (
            "📅 <b>Дата события изменилась</b>",
            _event_date_line(record),
        )
    if notice.kind == "event-details-changed":
        lines = [
            "ℹ️ <b>Изменились данные события</b>",
            "<b>" + html.escape(record.title) + "</b>",
        ]
        if record.route:
            lines.append("🥾 Маршрут: " + html.escape(record.route))
        if record.schedule_note:
            lines.append("🕐 " + html.escape(record.schedule_note))
        if record.place:
            lines.append("📍 " + html.escape(record.place))
        return tuple(lines)
    if notice.kind == "event-cancelled":
        return ("⛔ <b>Событие отменено</b>",)
    if notice.kind == "event-postponed":
        return ("⏸ <b>Событие перенесено</b>",)
    if notice.kind == "event-restored":
        return ("✅ <b>Событие снова подтверждено</b>",)

    if notice.option_id is None:
        raise ValueError("option notice requires option_id")
    option = _option(record, notice.option_id)

    if notice.kind in {"full", "closed"}:
        return (_access_copy(record, notice.kind),)
    if notice.kind == "deadline-known":
        deadline = _deadline_text(record, notice.option_id)
        prefix = _access_copy(
            record,
            (
                "deadline-open-prefix"
                if option.status == "open"
                else "deadline-unknown-prefix"
            ),
        )
        return (
            _access_copy(record, "deadline-known"),
            prefix + html.escape(deadline or "указанного срока"),
        )
    if notice.kind == "deadline-changed":
        deadline = _deadline_text(record, notice.option_id)
        return (
            _access_copy(record, "deadline-changed"),
            "Теперь до " + html.escape(deadline or "указанного срока"),
        )
    if notice.kind in {
        "opening-tomorrow",
        "opening-today",
        "one-day-tomorrow",
    }:
        opening = _opening_text(record, notice.option_id)
        return tuple(
            item for item in (
                _access_copy(record, notice.kind),
                opening,
            )
            if item is not None
        )

    heading = _access_copy(
        record,
        notice.kind if notice.kind in _ACCESS_COPY[record.access_kind] else "open",
    )
    lines = [heading]
    label = _option_label_line(record, notice.option_id)
    if label is not None:
        lines.append(label)
    action = _action_line(record, notice.option_id)
    if action is not None:
        lines.append(action)
    if notice.kind in {"open", "reopened", "closing-tomorrow", "closing-today"}:
        deadline = _deadline_text(record, notice.option_id)
        if deadline is not None:
            lines.append("⏳ до " + html.escape(deadline))
    return tuple(lines)


def render_reply(
    record: EventAccessRecord,
    decision: EventAccessDecision,
) -> str:
    if not decision.notices:
        raise ValueError("reply publication requires a notice")
    lines = []
    for notice in decision.notices:
        if lines:
            lines.append("")
        lines.extend(_reply_block(record, notice))
    message = with_footer("\n".join(lines))
    if not 1 <= len(message) <= MAX_MESSAGE_LENGTH:
        raise ValueError("event-access reply exceeds Telegram limit")
    return message


def render_decision(
    record: EventAccessRecord,
    decision: EventAccessDecision,
) -> str:
    if decision.operation == "root":
        return render_root(record, decision)
    if decision.operation == "reply":
        return render_reply(record, decision)
    raise ValueError("event-access decision has no publication")


def _status_summary(raw: Optional[Mapping[str, Any]]) -> str:
    if raw is None:
        return json.dumps({
            "version": None,
            "migration_required": False,
            "records": 0,
            "uncertain": False,
        }, ensure_ascii=False, sort_keys=True)

    version = raw.get("version")
    if version == 1:
        uncertain = raw.get("uncertain")
        return json.dumps({
            "version": 1,
            "migration_required": True,
            "baseline_records": len(raw.get("baseline", {})),
            "announced_records": len(raw.get("announced_record_ids", [])),
            "sent_triggers": len(raw.get("sent_triggers", [])),
            "uncertain": uncertain is not None,
        }, ensure_ascii=False, sort_keys=True)

    if version == 2:
        records = raw.get("records", {})
        uncertain = raw.get("uncertain")
        if not isinstance(records, dict):
            raise EventAccessStateError("event-access v2 records are invalid")
        return json.dumps({
            "version": 2,
            "migration_required": True,
            "records": len(records),
            "audience_known_records": sum(
                1
                for item in records.values()
                if isinstance(item, dict) and item.get("audience_known")
            ),
            "root_records": sum(
                1
                for item in records.values()
                if isinstance(item, dict)
                and item.get("root_message_id") is not None
            ),
            "sent_triggers": sum(
                len(item.get("sent_triggers", ()))
                for item in records.values()
                if isinstance(item, dict)
            ),
            "uncertain": uncertain is not None,
        }, ensure_ascii=False, sort_keys=True)

    value = validate_state(dict(raw))
    return json.dumps({
        "version": STATE_VERSION,
        "migration_required": False,
        "records": len(value["records"]),
        "audience_known_records": sum(
            1
            for item in value["records"].values()
            if item["audience_known"]
        ),
        "root_records": sum(
            1
            for item in value["records"].values()
            if item["root_message_id"] is not None
        ),
        "sent_triggers": sum(
            len(item["sent_triggers"])
            for item in value["records"].values()
        ),
        "uncertain": value["uncertain"] is not None,
        "uncertain_record_id": (
            value["uncertain"]["record_id"]
            if value["uncertain"] is not None
            else None
        ),
        "uncertain_operation": (
            value["uncertain"]["operation"]
            if value["uncertain"] is not None
            else None
        ),
    }, ensure_ascii=False, sort_keys=True)


async def _load_local_event_access_records(
    now: datetime,
    source_state_path: Path,
) -> Tuple[Tuple[EventAccessRecord, ...], int]:
    """Load accepted access records from fresh local snapshots only.

    Keep this explicit. Future accepted sources are added as bounded branches
    here rather than through a provider registry or source framework.
    """

    records = []
    fresh_sources = 0

    if convega_snapshot_is_access_fresh(now, source_state_path):
        fresh_sources += 1
        records.extend(await load_convega_access_records(source_state_path))

    record_ids = [record.record_id for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise EventAccessStateError(
            "duplicate event-access record_id across local sources"
        )

    return tuple(records), fresh_sources


async def run_registration_notifications(
    now: datetime,
    state: RegistrationNotificationState,
    publish: Callable[[str, Optional[int]], Awaitable[int]],
    *,
    source_state_path: Path = DEFAULT_SOURCE_STATE_PATH,
    publish_photo: Optional[
        Callable[[str, str], Awaitable[int]]
    ] = None,
) -> str:
    records, fresh_sources = await _load_local_event_access_records(
        now,
        source_state_path,
    )
    if fresh_sources == 0:
        return "stale_source"
    sent_any = False
    with state.exclusive_run():
        current = state.read()
        if current["uncertain"] is not None:
            return "uncertain"

        today = now.astimezone(GUARDAMAR_TIMEZONE).date()
        current["records"] = prune_records(current["records"], today)

        for record in records:
            event_day = record.event_end_date or record.event_start_date
            if event_day < today or not temporally_consistent(record, now):
                continue
            previous = current["records"].get(record.record_id)
            decision = plan_event_access_record(record, previous, now)

            if decision.operation is None:
                current["records"][record.record_id] = dict(
                    decision.candidate_record
                )
                continue

            message = render_decision(record, decision)
            state.reserve(
                current,
                record.record_id,
                decision.operation,
                message,
                decision.candidate_record,
                now,
            )
            try:
                use_photo = (
                    decision.operation == "root"
                    and record.image_url is not None
                    and publish_photo is not None
                    and len(message) <= 1024
                )
                if use_photo:
                    try:
                        message_id = await publish_photo(
                            record.image_url,
                            message,
                        )
                    except TelegramError as exc:
                        if exc.diagnostic_code not in {
                            "REMOTE-MEDIA",
                            "URL-POLICY",
                        }:
                            raise
                        message_id = await publish(message, None)
                else:
                    message_id = await publish(
                        message,
                        decision.reply_to_message_id,
                    )
            except TelegramError as exc:
                if is_ambiguous_send_failure(exc):
                    raise RegistrationDeliveryUncertain() from exc
                current = state.clear_uncertain()
                raise
            except Exception as exc:
                raise RegistrationDeliveryUncertain() from exc

            if decision.operation == "root":
                current = state.confirm_uncertain(message_id)
            else:
                current = state.confirm_uncertain()
            sent_any = True

        current["records"] = prune_records(current["records"], today)
        state.write(current)

    return "sent" if sent_any else "no_message"


async def _preview(
    now: datetime,
    state: RegistrationNotificationState,
    source_state_path: Path,
) -> Tuple[str, ...]:
    records, fresh_sources = await _load_local_event_access_records(
        now,
        source_state_path,
    )
    if fresh_sources == 0:
        return ("No access-fresh event source snapshot",)
    current = state.read()
    if current["uncertain"] is not None:
        return (
            "Event-access delivery is uncertain; automatic publication blocked",
        )
    messages = []
    simulated = {
        "version": STATE_VERSION,
        "records": {
            key: dict(value)
            for key, value in current["records"].items()
        },
        "uncertain": None,
    }
    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    simulated["records"] = prune_records(simulated["records"], today)
    for record in records:
        event_day = record.event_end_date or record.event_start_date
        if event_day < today or not temporally_consistent(record, now):
            continue
        previous = simulated["records"].get(record.record_id)
        decision = plan_event_access_record(record, previous, now)
        simulated["records"][record.record_id] = dict(
            decision.candidate_record
        )
        if decision.operation is not None:
            messages.append(render_decision(record, decision))
    return tuple(messages) or ("No event-access notification due",)


async def _run_cli(
    command: str,
    *,
    root_message_id: Optional[int] = None,
) -> int:
    now = datetime.now(GUARDAMAR_TIMEZONE)
    source_path = Path(os.environ.get(
        "CONVEGA_STATE_PATH", str(DEFAULT_SOURCE_STATE_PATH)
    ))
    state = RegistrationNotificationState(Path(os.environ.get(
        "EVENT_REGISTRATION_STATE_PATH", str(DEFAULT_STATE_PATH)
    )))

    if command == "status":
        print(_status_summary(state.read_raw()))
        return 0

    if command == "migrate-state":
        result = state.migrate()
        print(result)
        print(_status_summary(state.read_raw()))
        return 0

    if command == "resolve-sent":
        with state.exclusive_run():
            current = state.read()
            pending = current["uncertain"]
            if pending is None:
                raise EventAccessStateError(
                    "no uncertain event-access delivery"
                )
            if pending["operation"] == "root":
                current = state.confirm_uncertain(root_message_id)
            else:
                current = state.confirm_uncertain()
        print("uncertain event-access delivery committed as sent")
        print(_status_summary(current))
        return 0

    if command == "resolve-unsent":
        with state.exclusive_run():
            current = state.clear_uncertain()
        print("uncertain event-access delivery cleared for recomputation")
        print(_status_summary(current))
        return 0

    if command == "preview":
        for message in await _preview(now, state, source_path):
            print(message)
        return 0

    # Normal run must never auto-migrate legacy persistent state.
    state.read()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required"
        )

    async def publish(
        message: str,
        reply_to_message_id: Optional[int],
    ) -> int:
        return await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
            reply_to_message_id=reply_to_message_id,
            retry_only_rate_limits=True,
        )

    async def publish_photo(
        photo_url: str,
        caption: str,
    ) -> int:
        message_id, _ = await send_photo_url(
            bot_token,
            chat_id,
            photo_url,
            caption,
            disable_notification=False,
        )
        return message_id

    try:
        result = await run_registration_notifications(
            now,
            state,
            publish,
            source_state_path=source_path,
            publish_photo=publish_photo,
        )
    except RegistrationDeliveryUncertain:
        LOGGER.warning(
            "Event-access delivery uncertain; automatic resend disabled"
        )
        return 0
    LOGGER.info("Event-access run complete: %s", result)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-off event access lifecycle"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "run",
            "preview",
            "status",
            "migrate-state",
            "resolve-sent",
            "resolve-unsent",
        ),
        default="run",
    )
    parser.add_argument(
        "--message-id",
        type=int,
        default=None,
        help="verified Telegram root ID for resolve-sent",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        code = asyncio.run(_run_cli(
            args.command,
            root_message_id=args.message_id,
        ))
    except (
        ConvegaSourceError,
        EventAccessStateError,
        TelegramError,
        ValueError,
    ) as exc:
        print(f"Command failed: {exc}", file=os.sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
