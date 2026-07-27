"""Minimal Telegram Bot API delivery with bounded retries."""

import asyncio
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Dict, List, Optional

REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 1_000_000
MAX_SEND_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 10
LONG_POLL_TIMEOUT_SECONDS = 30


class TelegramError(RuntimeError):
    """A safe Telegram delivery error that never contains the bot token."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def _response_error(payload: Any, status: int) -> TelegramError:
    description = "Telegram rejected the message"
    retry_after = None
    if isinstance(payload, dict):
        raw_description = payload.get("description")
        if isinstance(raw_description, str) and raw_description:
            description = raw_description
        parameters = payload.get("parameters")
        if isinstance(parameters, dict):
            raw_retry_after = parameters.get("retry_after")
            if isinstance(raw_retry_after, int) and raw_retry_after >= 0:
                retry_after = raw_retry_after

    retryable = status == 429 or status >= 500
    return TelegramError(
        description,
        retryable=retryable,
        retry_after=retry_after,
    )


def _decode_response(payload: bytes) -> Dict[str, Any]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelegramError(
            "Telegram returned an invalid response", retryable=True
        ) from exc
    if not isinstance(decoded, dict):
        raise TelegramError(
            "Telegram returned an invalid response", retryable=True
        )
    return decoded


def _post_message(
    bot_token: str,
    chat_id: str,
    text: str,
    disable_notification: bool = False,
) -> None:
    if not 1 <= len(text) <= 4096:
        raise TelegramError(
            "Telegram message length is invalid", retryable=False
        )

    body = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": disable_notification,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GuardamarMorningDigest/0.2",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            payload = response.read(RESPONSE_LIMIT_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        payload = exc.read(RESPONSE_LIMIT_BYTES + 1)
        if len(payload) > RESPONSE_LIMIT_BYTES:
            raise TelegramError(
                "Telegram error response was too large", retryable=True
            ) from None
        try:
            decoded = _decode_response(payload)
        except TelegramError:
            decoded = {}
        raise _response_error(decoded, exc.code) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TelegramError(
            "Telegram request failed", retryable=True
        ) from None

    if len(payload) > RESPONSE_LIMIT_BYTES:
        raise TelegramError(
            "Telegram response was too large", retryable=True
        )
    decoded = _decode_response(payload)
    if status != 200 or decoded.get("ok") is not True:
        error_code = decoded.get("error_code")
        error_status = error_code if isinstance(error_code, int) else status
        raise _response_error(decoded, error_status)


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
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GuardamarMorningDigest/0.5",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout + 5,
        ) as response:
            payload = response.read(RESPONSE_LIMIT_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        payload = exc.read(RESPONSE_LIMIT_BYTES + 1)
        try:
            decoded = _decode_response(payload)
        except TelegramError:
            decoded = {}
        raise _response_error(decoded, exc.code) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        raise TelegramError(
            "Telegram update request failed",
            retryable=True,
        ) from None

    if len(payload) > RESPONSE_LIMIT_BYTES:
        raise TelegramError(
            "Telegram update response was too large",
            retryable=True,
        )
    decoded = _decode_response(payload)
    if status != 200 or decoded.get("ok") is not True:
        raise _response_error(decoded, status)
    result = decoded.get("result")
    if not isinstance(result, list) or not all(
        isinstance(item, dict) for item in result
    ):
        raise TelegramError(
            "Telegram returned invalid updates",
            retryable=True,
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
    max_attempts: int = MAX_SEND_ATTEMPTS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Send one message, retrying only transient failures."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")

    for attempt in range(1, max_attempts + 1):
        try:
            await asyncio.to_thread(
                _post_message,
                bot_token,
                chat_id,
                text,
                disable_notification,
            )
            return
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
