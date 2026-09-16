"""Run sports notifications from already accepted guide state."""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .pinned import DEFAULT_PINNED_STATE_PATH, PinnedGuideState
from .sports_notifications import (
    SportsNotificationError,
    TIMEZONE,
    sync_sports_notifications,
)
from .sporttia import valid_sporttia_snapshot
from .telegram import TelegramError

DEFAULT_GUIDE_STATE_PATH = "state/guide.json"


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SportsNotificationError(f"{name} is required")
    return value


def _accepted_catalog(path: Path):
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SportsNotificationError("guide state is unreadable") from exc
    if not isinstance(payload, dict):
        raise SportsNotificationError("guide state is invalid")
    catalog = payload.get("sporttia_catalog")
    if catalog is not None and not valid_sporttia_snapshot(catalog):
        raise SportsNotificationError("guide Sporttia snapshot is invalid")
    return catalog


async def run(now: datetime) -> str:
    """Read accepted source/message state and perform no source network I/O."""

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
    catalog = _accepted_catalog(guide_path)
    messages = PinnedGuideState(pinned_path).read(chat_id)
    return await sync_sports_notifications(
        bot_token,
        chat_id,
        catalog,
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
    except (SportsNotificationError, TelegramError, ValueError) as exc:
        logging.warning("Sports notification sync deferred: %s", exc)
        raise SystemExit(2) from exc
    logging.info("Sports notification sync complete: %s", result)


if __name__ == "__main__":
    main()
