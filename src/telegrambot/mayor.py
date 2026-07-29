"""Read fresh public text posts from the municipal mayor Telegram channel."""

import asyncio
import html
import re
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
    """Raised when fresh channel data cannot be checked safely."""


def _read_page() -> bytes:
    request = urllib.request.Request(
        CHANNEL_URL,
        headers={
            "Accept": "text/html",
            "User-Agent": "GuardamarMorningDigest/0.9",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                raise MayorChannelError("unexpected mayor channel redirect")
            payload = response.read(PAGE_LIMIT_BYTES + 1)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise MayorChannelError("mayor channel request failed") from exc
    if len(payload) > PAGE_LIMIT_BYTES:
        raise MayorChannelError("mayor channel response was too large")
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
    for block in _BLOCK_PATTERN.findall(payload):
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
            "Gemini key is required for market cancellation checks"
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
        raise MayorChannelError("market status extraction failed") from exc
    return validate_market_status(candidate, source_text, local_day)
