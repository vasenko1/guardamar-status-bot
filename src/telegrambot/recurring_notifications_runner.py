"""Run recurring-activity notifications from accepted local guide state."""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .chess_school import valid_chess_school_snapshot
from .dinamizacion import valid_dinamizacion_snapshot
from .literary_group import valid_literary_group_snapshot
from .pinned import DEFAULT_PINNED_STATE_PATH, PinnedGuideState
from .recurring_notifications import (
    RecurringNotificationError,
    TIMEZONE,
    sync_recurring_notifications,
)
from .telegram import TelegramError

DEFAULT_GUIDE_STATE_PATH = "state/guide.json"


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RecurringNotificationError(f"{name} is required")
    return value


def _accepted_snapshots(path: Path) -> Mapping[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecurringNotificationError("guide state is unreadable") from exc
    if not isinstance(payload, dict):
        raise RecurringNotificationError("guide state is invalid")

    result = {}
    candidates = (
        ("chess", "chess_school_snapshot", valid_chess_school_snapshot),
        ("literary_group", "literary_group_snapshot", valid_literary_group_snapshot),
        ("dinamizacion", "dinamizacion_snapshot", valid_dinamizacion_snapshot),
    )
    for key, field, validator in candidates:
        value = payload.get(field)
        if value is None:
            continue
        if not validator(value):
            raise RecurringNotificationError(
                f"guide recurring snapshot is invalid: {key}"
            )
        result[key] = value
    return result


async def run(now: datetime) -> str:
    """Read accepted state and perform no source-network requests."""

    bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
    chat_id = _required_environment("TELEGRAM_CHAT_ID")
    guide_path = Path(
        os.environ.get("GUIDE_STATE_PATH", "").strip()
        or DEFAULT_GUIDE_STATE_PATH
    )
    pinned_path = Path(
        os.environ.get("PINNED_GUIDE_STATE_PATH", "").strip()
        or DEFAULT_PINNED_STATE_PATH
    )
    snapshots = _accepted_snapshots(guide_path)
    if not snapshots:
        return "no-sources"
    messages = PinnedGuideState(pinned_path).read(chat_id)
    return await sync_recurring_notifications(
        bot_token,
        chat_id,
        snapshots,
        messages,
        now,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        result = asyncio.run(run(datetime.now(TIMEZONE)))
    except (RecurringNotificationError, TelegramError, ValueError) as exc:
        logging.warning("Recurring notification sync deferred: %s", exc)
        raise SystemExit(2) from exc
    logging.info("Recurring notification sync complete: %s", result)


if __name__ == "__main__":
    main()
