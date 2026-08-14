"""Minimal Telegram Bot API client with bounded protocol-aware recovery."""

import asyncio
import json
import secrets
import urllib.parse
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ._transport import BoundedFetchError, fetch_bounded

API_HOST = "api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 15
RESPONSE_LIMIT_BYTES = 1_000_000
MAX_SEND_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 10
LONG_POLL_TIMEOUT_SECONDS = 30
USER_AGENT = "GuardamarMorningDigest/0.13"


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
    api_description = ""
    if isinstance(payload, dict):
        raw_description = payload.get("description")
        if isinstance(raw_description, str):
            api_description = raw_description.casefold()
        parameters = payload.get("parameters")
        if isinstance(parameters, dict):
            raw_retry_after = parameters.get("retry_after")
            if isinstance(raw_retry_after, int) and raw_retry_after >= 0:
                retry_after = raw_retry_after
    retryable = status == 429 or 500 <= status <= 599
    code = f"HTTP-{status}"
    description = f"Telegram API вернул HTTP {status}"
    if status == 400 and "message is not modified" in api_description:
        code = "MESSAGE-NOT-MODIFIED"
        description = "сообщение Telegram уже содержит актуальный текст"
    elif status == 400 and (
        "message to edit not found" in api_description
        or "message to pin not found" in api_description
        or "message not found" in api_description
    ):
        code = "MESSAGE-NOT-FOUND"
        description = "сообщение Telegram не найдено"
    return TelegramError(
        f"Telegram API returned HTTP {status}",
        retryable=retryable,
        retry_after=retry_after,
        code=code,
        status=status,
        description=description,
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


def _multipart_body(
    fields: Dict[str, str], file_field: str, path: Path
) -> tuple[bytes, str]:
    """Build one bounded multipart request without another dependency."""

    boundary = f"GuardamarBot{secrets.token_hex(16)}"
    chunks: List[bytes] = []
    for name, value in fields.items():
        chunks.extend((
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            ).encode("ascii"),
            value.encode("utf-8"),
            b"\r\n",
        ))
    filename = path.name.replace('"', "").replace("\r", "").replace("\n", "")
    chunks.extend((
        f"--{boundary}\r\n".encode("ascii"),
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\n'
        ).encode("utf-8"),
        b"Content-Type: image/png\r\n\r\n",
        path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _call_api_multipart(
    bot_token: str,
    method: str,
    fields: Dict[str, str],
    file_field: str,
    path: Path,
) -> Dict[str, Any]:
    body, content_type = _multipart_body(fields, file_field, path)
    try:
        payload, _, _ = fetch_bounded(
            _api_url(bot_token, method),
            is_allowed_url=_is_telegram_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "Content-Type": content_type,
                "User-Agent": USER_AGENT,
            },
            method="POST",
            data=body,
            read_error_body=True,
        )
    except BoundedFetchError as exc:
        if exc.status is not None:
            try:
                decoded = _decode_response(exc.payload or b"")
            except TelegramError:
                decoded = {}
            raise _response_error(decoded, exc.status) from None
        retryable, description = _TRANSPORT_FAILURES.get(
            exc.code, (True, None)
        )
        raise TelegramError(
            "Telegram multipart request failed",
            retryable=retryable,
            code=exc.code,
            description=description,
        ) from None
    decoded = _decode_response(payload)
    if decoded.get("ok") is not True:
        raise _response_error(decoded, 200)
    return decoded


def _photo_result(decoded: Dict[str, Any]) -> tuple[int, str]:
    result = decoded.get("result")
    message_id = result.get("message_id") if isinstance(result, dict) else None
    photos = result.get("photo") if isinstance(result, dict) else None
    file_id = None
    if isinstance(photos, list):
        for photo in photos:
            if isinstance(photo, dict) and isinstance(photo.get("file_id"), str):
                file_id = photo["file_id"]
    if not isinstance(message_id, int) or not file_id:
        raise TelegramError(
            "Telegram returned no photo identifiers",
            retryable=False,
            code="INVALID-STRUCTURE",
            description="Telegram не вернул идентификаторы фотографии",
        )
    return message_id, file_id


def _post_photo(
    bot_token: str,
    chat_id: str,
    path: Path,
    caption: str,
    disable_notification: bool,
) -> tuple[int, str]:
    if not path.is_file() or path.stat().st_size > 10_000_000:
        raise TelegramError(
            "Telegram photo is invalid",
            retryable=False,
            code="PHOTO",
            description="файл расписания отсутствует или слишком велик",
        )
    if not 1 <= len(caption) <= 1024:
        raise TelegramError(
            "Telegram caption length is invalid",
            retryable=False,
            code="MESSAGE-LENGTH",
            description="подпись фотографии слишком длинная",
        )
    decoded = _call_api_multipart(
        bot_token,
        "sendPhoto",
        {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "disable_notification": json.dumps(disable_notification),
        },
        "photo",
        path,
    )
    return _photo_result(decoded)


def _edit_photo_media(
    bot_token: str,
    chat_id: str,
    message_id: int,
    path: Path,
    caption: str,
) -> str:
    if not path.is_file() or path.stat().st_size > 10_000_000:
        raise TelegramError(
            "Telegram photo is invalid",
            retryable=False,
            code="PHOTO",
            description="файл расписания отсутствует или слишком велик",
        )
    if not 1 <= len(caption) <= 1024:
        raise TelegramError(
            "Telegram caption length is invalid",
            retryable=False,
            code="MESSAGE-LENGTH",
            description="подпись фотографии слишком длинная",
        )
    media = {
        "type": "photo",
        "media": "attach://photo",
        "caption": caption,
        "parse_mode": "HTML",
    }
    decoded = _call_api_multipart(
        bot_token,
        "editMessageMedia",
        {
            "chat_id": chat_id,
            "message_id": str(message_id),
            "media": json.dumps(media, ensure_ascii=False),
        },
        "photo",
        path,
    )
    returned_id, file_id = _photo_result(decoded)
    if returned_id != message_id:
        raise TelegramError(
            "Telegram changed the edited message identifier",
            retryable=False,
            code="INVALID-STRUCTURE",
            description="Telegram вернул неожиданный идентификатор сообщения",
        )
    return file_id


def _edit_photo_caption(
    bot_token: str,
    chat_id: str,
    message_id: int,
    caption: str,
) -> None:
    if not 1 <= len(caption) <= 1024:
        raise TelegramError(
            "Telegram caption length is invalid",
            retryable=False,
            code="MESSAGE-LENGTH",
            description="подпись фотографии слишком длинная",
        )
    _call_api(
        bot_token,
        "editMessageCaption",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "parse_mode": "HTML",
        },
        REQUEST_TIMEOUT_SECONDS,
    )


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


def _pin_chat_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
    disable_notification: bool = True,
) -> None:
    if message_id <= 0:
        raise TelegramError(
            "Telegram message identifier is invalid",
            retryable=False,
            code="MESSAGE-ID",
            description="идентификатор сообщения Telegram некорректен",
        )
    _call_api(
        bot_token,
        "pinChatMessage",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
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


async def pin_chat_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
    *,
    disable_notification: bool = True,
) -> None:
    """Pin one known message without retrying a state-changing request."""

    await asyncio.to_thread(
        _pin_chat_message,
        bot_token,
        chat_id,
        message_id,
        disable_notification,
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


async def send_photo(
    bot_token: str,
    chat_id: str,
    path: Path,
    caption: str,
    *,
    disable_notification: bool = True,
) -> tuple[int, str]:
    """Send one photo exactly once so an uncertain response cannot duplicate it."""

    return await asyncio.to_thread(
        _post_photo,
        bot_token,
        chat_id,
        path,
        caption,
        disable_notification,
    )


async def edit_photo_media(
    bot_token: str,
    chat_id: str,
    message_id: int,
    path: Path,
    caption: str,
) -> str:
    """Replace one bot-authored photo and caption, returning its file ID."""

    return await asyncio.to_thread(
        _edit_photo_media,
        bot_token,
        chat_id,
        message_id,
        path,
        caption,
    )


async def edit_photo_caption(
    bot_token: str,
    chat_id: str,
    message_id: int,
    caption: str,
) -> None:
    """Replace only the caption of one known photo message."""

    await asyncio.to_thread(
        _edit_photo_caption,
        bot_token,
        chat_id,
        message_id,
        caption,
    )
