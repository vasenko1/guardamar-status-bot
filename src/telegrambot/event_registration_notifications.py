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
    plan_event_access_record,
    prune_records,
    temporally_consistent,
    validate_state,
)
from .telegram import TelegramError, is_ambiguous_send_failure, send_message


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
        if value.get("version") == 1:
            raise EventAccessStateError(
                "event-access state v1 requires migrate-state"
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
                return "created_v2"
            if raw.get("version") == STATE_VERSION:
                validate_state(raw)
                return "already_v2"
            if raw.get("version") != 1:
                raise EventAccessStateError(
                    "event-access state version cannot be migrated"
                )

            migrated = migrate_v1_state(raw)
            backup = self.backup_path
            if backup.exists():
                try:
                    existing = json.loads(
                        backup.read_text(encoding="utf-8")
                    )
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ) as exc:
                    raise EventAccessStateError(
                        "event-access v1 backup is unreadable"
                    ) from exc
                if existing != raw:
                    raise EventAccessStateError(
                        "event-access v1 backup collision"
                    )
            else:
                backup.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary = tempfile.mkstemp(
                    prefix=f".{backup.name}.",
                    dir=str(backup.parent),
                )
                try:
                    with os.fdopen(
                        descriptor, "w", encoding="utf-8"
                    ) as output:
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
            self._write(migrated)
            return "migrated_v1_to_v2"

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


def _root_heading(kind: str) -> str:
    headings = {
        "active": "📝 <b>Открыта регистрация</b>",
        "opening-tomorrow": "📝 <b>Завтра открывается регистрация</b>",
        "opening-today": "📝 <b>Сегодня открывается регистрация</b>",
        "one-day-tomorrow": "📝 <b>Регистрация только завтра</b>",
        "option-added": "➕ <b>Добавлен вариант регистрации</b>",
    }
    return headings.get(kind, "📝 <b>Обновление регистрации</b>")


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
        _root_heading(first.kind),
        "",
        "<b>" + html.escape(record.title) + "</b>",
        _event_date_line(record),
    ]
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
    option = _option(record, notice.option_id)
    if notice.kind == "open":
        heading = "📝 <b>Регистрация открыта</b>"
    elif notice.kind == "reopened":
        heading = "📝 <b>Регистрация снова открыта</b>"
    elif notice.kind == "full":
        return ("⛔ <b>Мест больше нет</b>",)
    elif notice.kind == "closed":
        return ("📝 <b>Регистрация закрыта</b>",)
    elif notice.kind == "deadline-known":
        deadline = _deadline_text(record, notice.option_id)
        return (
            "⏳ <b>Появился срок регистрации</b>",
            "Записаться можно до " + html.escape(deadline or "указанного срока"),
        )
    elif notice.kind == "deadline-changed":
        deadline = _deadline_text(record, notice.option_id)
        return (
            "⏳ <b>Срок регистрации изменён</b>",
            "Теперь до " + html.escape(deadline or "указанного срока"),
        )
    elif notice.kind == "closing-tomorrow":
        heading = "⏳ <b>Завтра заканчивается регистрация</b>"
    elif notice.kind == "closing-today":
        heading = "⏳ <b>Сегодня заканчивается регистрация</b>"
    elif notice.kind == "opening-tomorrow":
        return ("📝 <b>Завтра открывается регистрация</b>",)
    elif notice.kind == "opening-today":
        return ("📝 <b>Сегодня открывается регистрация</b>",)
    elif notice.kind == "one-day-tomorrow":
        return ("📝 <b>Регистрация только завтра</b>",)
    elif notice.kind == "action-changed":
        heading = "📝 <b>Изменился способ регистрации</b>"
    elif notice.kind == "option-added":
        heading = "➕ <b>Добавлен новый вариант регистрации</b>"
    else:
        heading = "📝 <b>Обновление регистрации</b>"

    lines = [heading]
    action = _action_line(record, notice.option_id)
    if action is not None:
        lines.append(action)
    if notice.kind in {"closing-tomorrow", "closing-today"}:
        deadline = _deadline_text(record, notice.option_id)
        if deadline is not None:
            lines.append("⏳ до " + html.escape(deadline))
    if option.label and len(record.options) > 1:
        lines.insert(1, "⏰ " + html.escape(option.label))
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


async def run_registration_notifications(
    now: datetime,
    state: RegistrationNotificationState,
    publish: Callable[[str, Optional[int]], Awaitable[int]],
    *,
    source_state_path: Path = DEFAULT_SOURCE_STATE_PATH,
) -> str:
    if not convega_snapshot_is_access_fresh(now, source_state_path):
        return "stale_source"

    records = await load_convega_access_records(source_state_path)
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
    if not convega_snapshot_is_access_fresh(now, source_state_path):
        return ("No access-fresh CONVEGA snapshot",)
    records = await load_convega_access_records(source_state_path)
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

    try:
        result = await run_registration_notifications(
            now,
            state,
            publish,
            source_state_path=source_path,
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
