"""Read fresh public text posts from the municipal mayor Telegram channel."""

import asyncio
import html
import re
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .gemini import GeminiError, extract_market_status
from .models import BeachNotice, Event

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
_FIESTAS_DATE_PATTERN = re.compile(
    r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|"
    r"s[aá]bado|domingo)\s+(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre)\s*,?\s*"
    r"(?:desde(?:\s+de)?\s+las|a\s+partir\s+de\s+las)\s+"
    r"(\d{1,2}):(\d{2})\s*h",
    re.IGNORECASE,
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        start=1,
    )
}


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


_TRANSPORT_DESCRIPTIONS = {
    "REDIRECT": "Telegram перенаправил запрос на другой сайт",
    "CONTENT-TYPE": "Telegram вернул ответ не в формате HTML",
    "TIMEOUT": (
        "сетевой тайм-аут при загрузке публичной страницы "
        "канала t.me (лимит сетевой операции — 10 с)"
    ),
    "NETWORK": "не удалось установить соединение с Telegram",
    "TOO-LARGE": "ответ Telegram превысил допустимый размер",
}


def _read_page() -> bytes:
    try:
        payload, _, _ = fetch_bounded(
            CHANNEL_URL,
            is_allowed_url=_is_channel_url,
            accepted_types=frozenset({"text/html"}),
            limit_bytes=PAGE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html",
                "Accept-Language": "es",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
        )
    except BoundedFetchError as exc:
        raise MayorChannelError(
            f"Mayor channel request failed: {exc.code}",
            code=exc.code,
            status=exc.status,
            description=(
                f"Telegram вернул HTTP {exc.status}"
                if exc.status is not None
                else _TRANSPORT_DESCRIPTIONS.get(exc.code)
            ),
        ) from exc
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


def _fiestas_de_barrio_events(
    text: str,
    local_day: date,
) -> Tuple[Event, ...]:
    """Extract only explicitly dated Fiestas de Barrio entries."""

    if re.search(
        r"\bfiesta(?:s)?\s+de\s+barrio\b",
        _normalized(text),
    ) is None:
        return ()
    matches = list(_FIESTAS_DATE_PATTERN.finditer(text))
    events = []
    for index, match in enumerate(matches):
        day, month_name, hour, minute = match.groups()
        try:
            event_day = date(
                local_day.year,
                _MONTHS[_normalized(month_name)],
                int(day),
            )
        except (KeyError, ValueError):
            continue
        if event_day != local_day:
            continue
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        segment = text[match.end():end]
        districts_match = re.search(
            r"\burbanizaciones?\s+(.+?)(?:\.\s*ubicaci[oó]n|"
            r"\s+ubicaci[oó]n|\.|$)",
            segment,
            re.IGNORECASE,
        )
        districts = (
            " ".join(districts_match.group(1).split())
            if districts_match is not None
            else ""
        )
        districts = re.sub(
            r"\s+y\s+([^,]+)$",
            r" и \1",
            districts,
            flags=re.IGNORECASE,
        )
        place_match = re.search(
            r"ubicaci[oó]n\s*:?\s*(.+?)(?:\.\s|#|$)",
            segment,
            re.IGNORECASE,
        )
        if place_match is None:
            place_match = re.search(
                r"\b(parque\s+C/\s*[^.]+|"
                r"urb\.\s*[^.]*?frente(?:\s+a)?(?:\s+la)?\s+piscina)"
                r"(?:\.|#|$)",
                segment,
                re.IGNORECASE,
            )
        place = (
            " ".join(place_match.group(1).split())
            if place_match is not None
            else None
        )
        events.append(
            Event(
                title=(
                    f"Праздник районов {districts}"
                    if districts
                    else "Праздник районов"
                ),
                starts_at=datetime(
                    event_day.year,
                    event_day.month,
                    event_day.day,
                    int(hour),
                    int(minute),
                    tzinfo=GUARDAMAR_TIMEZONE,
                ),
                place=place,
            )
        )
    return tuple(events)


async def fetch_today_mayor_events(now: datetime) -> Tuple[Event, ...]:
    """Return explicitly dated supported events from the official channel."""

    payload = await asyncio.to_thread(_read_page)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    events = [
        event
        for _, text in extract_recent_posts(payload, now)
        for event in _fiestas_de_barrio_events(text, local_day)
    ]
    events.sort(key=lambda event: event.starts_at or now)
    return tuple(events)


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
