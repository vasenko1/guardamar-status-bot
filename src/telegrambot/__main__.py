"""Run one Morning Digest publication, preview, or state inspection."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .aemet import AemetError
from .commands import listen_for_preview, parse_allowed_user_ids
from .delivery import publish_morning, publish_update
from .digest import build_fallback_update
from .mayor import latest_beach_notice
from .morning import _safebeach_is_in_season, produce_message
from .safebeach import (
    SafeBeachError,
    fetch_beach_status,
    is_complete_current_status,
)
from .state import PublicationState, StateError
from .telegram import TelegramError, delete_message, send_message

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
    now = datetime.now(GUARDAMAR_TIMEZONE)
    if command in {"run", "morning"}:
        result = await publish_morning(
            now,
            state,
            lambda: produce_message(
                api_key,
                now,
                os.environ.get("GEMINI_API_KEY", "").strip(),
                Path(
                    os.environ.get(
                        "MUNICIPAL_AGENDA_STATE_PATH",
                        DEFAULT_MUNICIPAL_AGENDA_STATE_PATH,
                    )
                ),
                collect_beach=False,
            ),
            lambda message: send_message(
                bot_token,
                chat_id,
                message,
                disable_notification=False,
            ),
        )
        return 0 if result in {"success", "duplicate"} else 1

    if not _safebeach_is_in_season(now):
        logging.info("SKIP: SafeBeach update phase is out of season")
        return 0

    async def find_notice(since: datetime):
        return await latest_beach_notice(now, since)

    async def produce_update(status, notice):
        try:
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
                collect_beach=False,
                beach_status=status,
                beach_notice=notice,
                aemet_daily_attempts=3,
                aemet_retry_seconds=120,
            )
        except AemetError:
            morning_message = existing.get("morning_message")
            if not isinstance(morning_message, str) or not morning_message:
                raise
            logging.warning(
                "AEMET update failed after two retries; "
                "using the published morning message"
            )
            return build_fallback_update(
                morning_message,
                status,
                notice,
            )

    async def deliver_update(message: str) -> int:
        return await send_message(
            bot_token,
            chat_id,
            message,
            disable_notification=False,
        )

    async def delete_old(message_id: int) -> None:
        await delete_message(bot_token, chat_id, message_id)

    existing = state.morning_record(now.date())
    if existing is None:
        logging.info("SKIP: no morning message exists for %s", now.date())
        return 0
    if isinstance(existing.get("update_message_id"), int):
        result = await publish_update(
            now,
            state,
            None,
            False,
            find_notice,
            produce_update,
            deliver_update,
            delete_old,
        )
        return 0 if result == "duplicate" else 1

    beach = None
    try:
        candidate = await fetch_beach_status()
        if is_complete_current_status(candidate, now):
            beach = candidate
    except SafeBeachError as exc:
        logging.warning("SafeBeach update check failed: %s", exc)
    final_attempt = (now.hour, now.minute) >= (10, 40)
    result = await publish_update(
        now,
        state,
        beach,
        final_attempt,
        find_notice,
        produce_update,
        deliver_update,
        delete_old,
    )
    return 0 if result in {
        "success",
        "duplicate",
        "waiting",
        "no_update",
        "no_morning",
    } else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Guardamar Morning Digest"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "morning", "update", "preview", "status", "listen"),
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
