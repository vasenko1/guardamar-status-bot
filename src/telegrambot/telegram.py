"""Minimal Telegram Bot API client with bounded protocol-aware recovery."""

import asyncio
import json
import urllib.parse
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ._transport import BoundedFetchError, fetch_bounded

API_HOST = "api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 1_000_000
MAX_SEND_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 10
LONG_POLL_TIMEOUT_SECONDS = 30
USER_AGENT = "GuardamarMorningDigest/0.12"


class TelegramError(RuntimeError):
    """An operator-safe Telegram error that never contains the bot token."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        retry_after: Optional[int] = None,
        code: str = "INVALID",
        status: Optional[int] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.diagnostic_code = code
        self.server_status = status
        self.safe_description = description


def _is_telegram_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == API_HOST


def _decode_response(payload: bytes) -> Dict[str, Any]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelegramError(
            "Telegram returned invalid JSON",
            retryable=True,
            code="INVALID-JSON",
            description="сервер вернул некорректный JSON",
        ) from exc
    if not isinstance(decoded, dict):
        raise TelegramError(
            "Telegram returned an invalid response structure",
            retryable=True,
            code="INVALID-STRUCTURE",
            description="структура ответа Telegram некорректна",
        )
    return decoded


def _response_error(payload: Any, status: int) -> TelegramError:
    retry_after = None
    if isinstance(payload, dict):
        parameters = payload.get("parameters")
        if isinstance(parameters, dict):
            raw_retry_after = parameters.get("retry_after")
            if isinstance(raw_retry_after, int) and raw_retry_after >= 0:
                retry_after = raw_retry_after
    retryable = status == 429 or 500 <= status <= 599
    return TelegramError(
        f"Telegram API returned HTTP {status}",
        retryable=retryable,
        retry_after=retry_after,
        code=f"HTTP-{status}",
        status=status,
        description=f"Telegram API вернул HTTP {status}",
    )


def _api_url(bot_token: str, method: str) -> str:
    if (
        not bot_token
        or any(character in bot_token for character in "/?#")
        or not method.isascii()
        or not method.isalnum()
    ):
        raise TelegramError(
            "Telegram configuration is invalid",
            retryable=False,
            code="CONFIG",
            description="токен или метод Telegram имеет некорректный формат",
        )
    return f"https://{API_HOST}/bot{bot_token}/{method}"


_TRANSPORT_FAILURES = {
    "REDIRECT": (
        False,
        "получен недопустимый адрес ответа Telegram",
    ),
    "CONTENT-TYPE": (
        True,
        "Telegram вернул ответ не в формате JSON",
    ),
    "TIMEOUT": (
        True,
        "Telegram не ответил до истечения тайм-аута",
    ),
    "NETWORK": (
        True,
        "не удалось установить соединение с Telegram",
    ),
    "TOO-LARGE": (
        True,
        "ответ Telegram превысил допустимый размер",
    ),
}


def _call_api(
    bot_token: str,
    method: str,
    body: Dict[str, Any],
    timeout: int,
) -> Dict[str, Any]:
    try:
        payload, _, _ = fetch_bounded(
            _api_url(bot_token, method),
            is_allowed_url=_is_telegram_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=timeout,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": USER_AGENT,
            },
            method="POST",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            read_error_body=True,
        )
    except BoundedFetchError as exc:
        if exc.status is not None:
            # The bounded error body may carry Telegram's retry_after.
            try:
                decoded = _decode_response(exc.payload or b"")
            except TelegramError:
                decoded = {}
            raise _response_error(decoded, exc.status) from None
        retryable, description = _TRANSPORT_FAILURES.get(
            exc.code, (True, None)
        )
        raise TelegramError(
            "Telegram request failed",
            retryable=retryable,
            code=exc.code,
            description=description,
        ) from None
    decoded = _decode_response(payload)
    if decoded.get("ok") is not True:
        raise _response_error(decoded, 200)
    return decoded


def _post_message(
    bot_token: str,
    chat_id: str,
    text: str,
    disable_notification: bool = False,
    reply_to_message_id: Optional[int] = None,
) -> int:
    if not 1 <= len(text) <= 4096:
        raise TelegramError(
            "Telegram message length is invalid",
            retryable=False,
            code="MESSAGE-LENGTH",
            description="длина сообщения выходит за пределы Telegram",
        )
    body: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_notification": disable_notification,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if reply_to_message_id is not None:
        body["reply_parameters"] = {
            "message_id": reply_to_message_id,
            "allow_sending_without_reply": False,
        }
    decoded = _call_api(
        bot_token,
        "sendMessage",
        body,
        REQUEST_TIMEOUT_SECONDS,
    )
    result = decoded.get("result")
    message_id = result.get("message_id") if isinstance(result, dict) else None
    if not isinstance(message_id, int):
        raise TelegramError(
            "Telegram returned no message identifier",
            retryable=True,
            code="NO-MESSAGE-ID",
            description="Telegram не вернул идентификатор сообщения",
        )
    return message_id


def _delete_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
) -> None:
    _call_api(
        bot_token,
        "deleteMessage",
        {"chat_id": chat_id, "message_id": message_id},
        REQUEST_TIMEOUT_SECONDS,
    )


def _edit_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
    text: str,
) -> None:
    if not 1 <= len(text) <= 4096:
        raise TelegramError(
            "Telegram message length is invalid",
            retryable=False,
            code="MESSAGE-LENGTH",
            description="длина сообщения выходит за пределы Telegram",
        )
    _call_api(
        bot_token,
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        },
        REQUEST_TIMEOUT_SECONDS,
    )


def _get_updates(
    bot_token: str,
    offset: Optional[int],
    timeout: int,
) -> List[Dict[str, Any]]:
    body: Dict[str, Any] = {
        "timeout": timeout,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        body["offset"] = offset
    decoded = _call_api(
        bot_token,
        "getUpdates",
        body,
        timeout + 5,
    )
    result = decoded.get("result")
    if not isinstance(result, list) or not all(
        isinstance(item, dict) for item in result
    ):
        raise TelegramError(
            "Telegram returned invalid updates",
            retryable=True,
            code="INVALID-UPDATES",
            description="Telegram вернул некорректный список обновлений",
        )
    return result


async def get_updates(
    bot_token: str,
    offset: Optional[int],
    timeout: int = LONG_POLL_TIMEOUT_SECONDS,
) -> List[Dict[str, Any]]:
    """Receive only Telegram message updates through one bounded long poll."""

    return await asyncio.to_thread(
        _get_updates,
        bot_token,
        offset,
        timeout,
    )


async def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    disable_notification: bool = False,
    reply_to_message_id: Optional[int] = None,
    max_attempts: int = MAX_SEND_ATTEMPTS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Send one message, retrying only transient failures."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    for attempt in range(1, max_attempts + 1):
        try:
            arguments = (bot_token, chat_id, text, disable_notification)
            if reply_to_message_id is not None:
                arguments += (reply_to_message_id,)
            return await asyncio.to_thread(_post_message, *arguments)
        except TelegramError as exc:
            if not exc.retryable or attempt == max_attempts:
                raise
            backoff = 2 ** (attempt - 1)
            requested_delay = exc.retry_after or 0
            delay = min(
                max(backoff, requested_delay),
                MAX_RETRY_DELAY_SECONDS,
            )
            await sleep(delay)
    raise AssertionError("unreachable")


async def send_poll(
    bot_token: str,
    chat_id: str,
    question: str,
    options: List[str],
) -> int:
    """Send one anonymous native poll; the operator retries manually."""

    question = question.strip()
    cleaned = [option.strip() for option in options]
    if not 1 <= len(question) <= 300:
        raise TelegramError(
            "Poll question length is invalid",
            retryable=False,
            code="CONFIG",
            description="вопрос опроса должен занимать от 1 до 300 символов",
        )
    if not 2 <= len(cleaned) <= 10 or any(
        not 1 <= len(option) <= 100 for option in cleaned
    ):
        raise TelegramError(
            "Poll options are invalid",
            retryable=False,
            code="CONFIG",
            description=(
                "нужно от 2 до 10 вариантов длиной от 1 до 100 символов"
            ),
        )

    def post() -> int:
        decoded = _call_api(
            bot_token,
            "sendPoll",
            {
                "chat_id": chat_id,
                "question": question,
                "options": cleaned,
                "is_anonymous": True,
            },
            REQUEST_TIMEOUT_SECONDS,
        )
        result = decoded.get("result")
        message_id = (
            result.get("message_id") if isinstance(result, dict) else None
        )
        if not isinstance(message_id, int):
            raise TelegramError(
                "Telegram poll response had no message ID",
                retryable=False,
                code="INVALID-STRUCTURE",
                description="структура ответа Telegram некорректна",
            )
        return message_id

    return await asyncio.to_thread(post)


async def delete_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
) -> None:
    """Delete one known message; caller decides whether to retry later."""

    await asyncio.to_thread(
        _delete_message, bot_token, chat_id, message_id
    )


async def edit_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
    text: str,
) -> None:
    """Replace one known bot-authored message."""

    await asyncio.to_thread(
        _edit_message, bot_token, chat_id, message_id, text
    )
