"""Run one Morning Digest publication, preview, or state inspection."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .aemet import AemetError
from .commands import listen_for_preview, parse_allowed_user_ids
from .delivery import attempt_delivery
from .morning import produce_message
from .state import PublicationState, StateError
from .telegram import TelegramError, send_message

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_STATE_PATH = "state/delivery.json"
DEFAULT_MUNICIPAL_AGENDA_STATE_PATH = "state/municipal_agenda.json"


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


async def _produce_message(api_key: str, now: datetime) -> str:
    return await produce_message(
        api_key,
        now,
        os.environ.get("GEMINI_API_KEY", "").strip(),
        Path(
            os.environ.get(
                "MUNICIPAL_AGENDA_STATE_PATH",
                DEFAULT_MUNICIPAL_AGENDA_STATE_PATH,
            )
        ),
    )


def _delivery_runner(
    api_key: str,
    bot_token: str,
    chat_id: str,
    state: PublicationState,
) -> Callable[[datetime], Awaitable[str]]:
    async def run(now: datetime) -> str:
        return await attempt_delivery(
            now=now,
            state=state,
            produce_message=lambda: _produce_message(api_key, now),
            deliver_message=lambda message: send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=True,
            ),
        )

    return run


async def _run_command(command: str) -> int:
    api_key = _required_environment("AEMET_API_KEY")
    if command == "preview":
        print(
            await _produce_message(
                api_key, datetime.now(GUARDAMAR_TIMEZONE)
            )
        )
        return 0

    bot_token = _required_environment("TELEGRAM_BOT_TOKEN")
    if command == "listen":
        allowed_user_ids = parse_allowed_user_ids(
            _required_environment("TELEGRAM_ALLOWED_USER_IDS")
        )
        await listen_for_preview(
            bot_token,
            allowed_user_ids,
            lambda now: _produce_message(api_key, now),
        )
        return 0

    chat_id = _required_environment("TELEGRAM_CHAT_ID")
    state_path = Path(
        os.environ.get("MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH)
    )
    state = PublicationState(state_path)
    run_once = _delivery_runner(api_key, bot_token, chat_id, state)

    result = await run_once(datetime.now(GUARDAMAR_TIMEZONE))
    return 0 if result in {"success", "duplicate"} else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Guardamar Morning Digest"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "preview", "status", "listen"),
        default="run",
    )
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if arguments.command == "status":
        state_path = Path(
            os.environ.get(
                "MORNING_DIGEST_STATE_PATH", DEFAULT_STATE_PATH
            )
        )
        try:
            successful_date = PublicationState(
                state_path
            ).last_successful_date()
        except StateError as exc:
            print(f"State error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            successful_date.isoformat()
            if successful_date
            else "No successful publication recorded"
        )
        return

    try:
        exit_code = asyncio.run(_run_command(arguments.command))
    except (AemetError, TelegramError, StateError, ValueError) as exc:
        print(f"Morning Digest failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        return
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
