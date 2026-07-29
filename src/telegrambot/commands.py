"""Minimal private operator command listener."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional, Set
from zoneinfo import ZoneInfo

from .aemet import AemetError
from .telegram import TelegramError, get_updates, send_message

LOGGER = logging.getLogger(__name__)
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
MAX_COMMAND_AGE_SECONDS = 120
RETRY_DELAY_SECONDS = 5
PREVIEW_AEMET_RETRY_SECONDS = 3
PREVIEW_FAILURE_PREFIX = "Не удалось сформировать предпросмотр."


def parse_allowed_user_ids(value: str) -> Set[int]:
    """Parse a comma-separated allowlist without accepting empty entries."""

    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS is invalid")
    try:
        result = {int(part) for part in parts}
    except ValueError as exc:
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS is invalid") from exc
    if any(user_id <= 0 for user_id in result):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS is invalid")
    return result


def preview_destination(
    update: Dict[str, Any],
    allowed_user_ids: Set[int],
    now_timestamp: int,
) -> Optional[str]:
    """Return the private chat ID for one fresh authorized /preview."""

    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender = message.get("from")
    chat = message.get("chat")
    text = message.get("text")
    sent_at = message.get("date")
    if (
        not isinstance(sender, dict)
        or not isinstance(chat, dict)
        or not isinstance(text, str)
        or not isinstance(sent_at, int)
        or sender.get("id") not in allowed_user_ids
        or chat.get("type") != "private"
        or now_timestamp - sent_at > MAX_COMMAND_AGE_SECONDS
        or sent_at > now_timestamp + 30
    ):
        return None
    command = text.strip().split(maxsplit=1)[0].casefold()
    if command.split("@", 1)[0] != "/preview":
        return None
    chat_id = chat.get("id")
    return str(chat_id) if isinstance(chat_id, int) else None


async def _produce_preview(
    produce: Callable[[datetime], Awaitable[str]],
) -> str:
    """Retry only the required AEMET source once for an interactive preview."""

    try:
        return await produce(datetime.now(GUARDAMAR_TIMEZONE))
    except AemetError:
        LOGGER.warning("AEMET preview failed; retrying once")
        await asyncio.sleep(PREVIEW_AEMET_RETRY_SECONDS)
        return await produce(datetime.now(GUARDAMAR_TIMEZONE))


def preview_failure_message(exc: Exception) -> str:
    """Return a concise operator-safe reason without raw transport details."""

    if isinstance(exc, AemetError):
        reason = str(exc)
        translations = {
            "The daily Guardamar forecast is unavailable": (
                "дневной прогноз для Гуардамара недоступен"
            ),
            "AEMET request failed": "запрос к AEMET не выполнен",
            "AEMET did not provide a product download": (
                "AEMET не предоставил данные прогноза"
            ),
        }
        detail = translations.get(reason, "AEMET вернул некорректные данные")
        return f"{PREVIEW_FAILURE_PREFIX}\nПричина: {detail}."
    return (
        f"{PREVIEW_FAILURE_PREFIX}\n"
        f"Причина: внутренняя ошибка ({type(exc).__name__})."
    )


async def listen_for_preview(
    bot_token: str,
    allowed_user_ids: Set[int],
    produce: Callable[[datetime], Awaitable[str]],
) -> None:
    """Serve only fresh allowlisted private /preview commands."""

    offset: Optional[int] = None
    LOGGER.info("Preview command listener started")
    while True:
        try:
            updates = await get_updates(bot_token, offset)
        except TelegramError as exc:
            LOGGER.warning("Telegram command polling failed: %s", exc)
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            continue

        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = max(offset or 0, update_id + 1)
            chat_id = preview_destination(
                update,
                allowed_user_ids,
                int(time.time()),
            )
            if chat_id is None:
                continue
            try:
                message = await _produce_preview(produce)
                await send_message(
                    bot_token,
                    chat_id,
                    message,
                    disable_notification=True,
                )
                LOGGER.info("Preview sent to an authorized private chat")
            except Exception as exc:
                LOGGER.error("Preview command failed: %s", exc)
                try:
                    await send_message(
                        bot_token,
                        chat_id,
                        preview_failure_message(exc),
                        disable_notification=True,
                    )
                except TelegramError:
                    LOGGER.error("Preview failure reply could not be sent")
