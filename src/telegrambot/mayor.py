"""Read fresh public text posts from the municipal mayor Telegram channel."""

import asyncio
import html
import http.client
import re
import socket
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .gemini import GeminiError, extract_market_status
from .models import BeachNotice

CHANNEL_URL = "https://t.me/s/AlcaldeGuardamar"
ALLOWED_HOST = "t.me"
REQUEST_TIMEOUT_SECONDS = 10
PAGE_LIMIT_BYTES = 250_000
MAX_POST_AGE_DAYS = 7
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
_BLOCK_PATTERN = re.compile(
    rb'<div class="tgme_widget_message_wrap.*?'
    rb'(?=<div class="tgme_widget_message_wrap|\Z)',
    re.DOTALL,
)
_TEXT_PATTERN = re.compile(
    rb'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',
    re.DOTALL,
)
_DATE_PATTERN = re.compile(rb'<time datetime="([^"]+)"')


class MayorChannelError(RuntimeError):
    """An operator-safe Mayor channel failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID",
        status: Optional[int] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.server_status = status
        self.safe_description = description


def _is_channel_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == ALLOWED_HOST


class _MayorRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if not _is_channel_url(new_url):
            raise MayorChannelError(
                "Mayor channel redirected outside Telegram",
                code="REDIRECT",
                description="Telegram перенаправил запрос на другой сайт",
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _read_page() -> bytes:
    request = urllib.request.Request(
        CHANNEL_URL,
        headers={
            "Accept": "text/html",
            "Accept-Language": "es",
            "User-Agent": "GuardamarMorningDigest/0.12",
        },
    )
    opener = urllib.request.build_opener(_MayorRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            if not _is_channel_url(response.geturl()):
                raise MayorChannelError(
                    "Unexpected Mayor channel response URL",
                    code="REDIRECT",
                    description="получен недопустимый адрес ответа Telegram",
                )
            if response.headers.get_content_type() != "text/html":
                raise MayorChannelError(
                    "Mayor channel returned non-HTML content",
                    code="CONTENT-TYPE",
                    description="Telegram вернул ответ не в формате HTML",
                )
            payload = response.read(PAGE_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise MayorChannelError(
            f"Mayor channel HTTP status {exc.code}",
            code=f"HTTP-{exc.code}",
            status=exc.code,
            description=f"Telegram вернул HTTP {exc.code}",
        ) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, (TimeoutError, socket.timeout))
        )
        raise MayorChannelError(
            "Mayor channel request timed out"
            if timed_out
            else "Mayor channel network request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
            description=(
                "Telegram не ответил до истечения тайм-аута"
                if timed_out
                else "не удалось установить соединение с Telegram"
            ),
        ) from exc
    if len(payload) > PAGE_LIMIT_BYTES:
        raise MayorChannelError(
            "Mayor channel response was too large",
            code="TOO-LARGE",
            description="ответ Telegram превысил допустимый размер",
        )
    return payload


def extract_recent_posts(
    payload: bytes,
    now: datetime,
) -> Tuple[Tuple[datetime, str], ...]:
    """Extract bounded recent text posts with trustworthy Telegram timestamps."""

    cutoff = now.astimezone(GUARDAMAR_TIMEZONE) - timedelta(
        days=MAX_POST_AGE_DAYS
    )
    posts: List[Tuple[datetime, str]] = []
    blocks = _BLOCK_PATTERN.findall(payload)
    if not blocks:
        raise MayorChannelError(
            "Mayor channel contained no message blocks",
            code="INVALID-STRUCTURE",
            description="страница Telegram не содержит сообщений канала",
        )
    structured_blocks = 0
    for block in blocks:
        text_match = _TEXT_PATTERN.search(block)
        date_match = _DATE_PATTERN.search(block)
        if text_match is None or date_match is None:
            continue
        try:
            published_at = datetime.fromisoformat(
                date_match.group(1).decode("ascii")
            ).astimezone(GUARDAMAR_TIMEZONE)
        except (UnicodeDecodeError, ValueError):
            continue
        structured_blocks += 1
        if not cutoff <= published_at <= now.astimezone(
            GUARDAMAR_TIMEZONE
        ) + timedelta(minutes=5):
            continue
        raw_text = re.sub(rb"<[^>]+>", b" ", text_match.group(1))
        text = " ".join(
            html.unescape(raw_text.decode("utf-8", "replace")).split()
        )
        if text:
            posts.append((published_at, text))
    if structured_blocks == 0:
        raise MayorChannelError(
            "Mayor channel messages had no valid timestamps",
            code="INVALID-STRUCTURE",
            description="структура сообщений Telegram изменилась",
        )
    return tuple(posts)


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    ).casefold()


def _beach_notice(
    published_at: datetime,
    text: str,
) -> Optional[BeachNotice]:
    normalized = _normalized(text)
    beach_context = any(
        marker in normalized
        for marker in ("playa", "bano", "bandera")
    )
    prohibited = any(
        marker in normalized
        for marker in ("prohibido el bano", "bandera roja")
    )
    allowed = any(
        marker in normalized
        for marker in ("permitido el bano", "bandera amarilla")
    )
    if not beach_context or not (prohibited or allowed):
        return None

    if prohibited:
        message = "Купание запрещено."
        causes = (
            ("corrient", "течения"),
            ("oleaje", "волны"),
            ("contamin", "загрязнение воды"),
            ("dragon azul", "обнаружен синий дракон"),
        )
        details = [
            russian
            for marker, russian in causes
            if marker in normalized
        ]
        if details:
            message = (
                "Купание запрещено: " + ", ".join(details) + "."
            )
    else:
        message = "Купание разрешено с осторожностью."
    return BeachNotice(
        text=message,
        bathing_prohibited=prohibited,
        published_at=published_at,
    )


async def latest_beach_notice(
    now: datetime,
    since: datetime,
) -> Optional[BeachNotice]:
    """Return the newest explicit official bathing-status transition."""

    payload = await asyncio.to_thread(_read_page)
    posts = extract_recent_posts(payload, now)
    notices = [
        notice
        for published_at, text in posts
        if published_at > since.astimezone(GUARDAMAR_TIMEZONE)
        for notice in (_beach_notice(published_at, text),)
        if notice is not None
    ]
    return max(
        notices,
        key=lambda notice: notice.published_at,
        default=None,
    )


def validate_market_status(
    candidate: Dict[str, Any],
    source_text: str,
    local_day,
) -> bool:
    """Accept cancellation only when exact source evidence proves it."""

    if candidate.get("cancelled") is not True:
        return False
    evidence = candidate.get("evidence_es")
    event_date = candidate.get("event_date")
    if (
        not isinstance(evidence, str)
        or not 1 <= len(evidence) <= 1_000
        or event_date != local_day.isoformat()
        or evidence not in source_text
    ):
        return False
    normalized = _normalized(evidence)
    return (
        "mercad" in normalized
        and any(
            marker in normalized
            for marker in (
                "suspend",
                "cancel",
                "no se celebr",
                "aplaz",
                "traslad",
            )
        )
    )


async def market_is_cancelled(
    now: datetime,
    gemini_api_key: str,
) -> bool:
    """Check a scheduled market cancellation from fresh channel text only."""

    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if not gemini_api_key:
        raise MayorChannelError(
            "Gemini key is required for market cancellation checks",
            code="CONFIG",
            description="не настроен ключ Gemini для проверки рынка",
        )
    payload = await asyncio.to_thread(_read_page)
    posts = extract_recent_posts(payload, now)
    relevant = [
        f"{published.isoformat()} {text}"
        for published, text in posts
        if "mercad" in _normalized(text)
    ]
    if not relevant:
        return False
    source_text = "\n".join(relevant)
    try:
        candidate = await extract_market_status(
            gemini_api_key,
            source_text,
            local_day,
        )
    except GeminiError as exc:
        raise MayorChannelError(
            "Market status extraction failed",
            code=exc.diagnostic_code,
            status=exc.server_status,
            description=exc.safe_description,
        ) from exc
    return validate_market_status(candidate, source_text, local_day)
