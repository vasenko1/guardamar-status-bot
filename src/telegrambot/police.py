"""Fetch explicit traffic restrictions from Policía Local Guardamar."""

import asyncio
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .models import TrafficNotice
from .gemini import GeminiError, translate_traffic_notice

TRAFFIC_URL = "https://policiaguardamar.com/cortecallefiestas.html"
ALLOWED_HOSTS = {"policiaguardamar.com", "www.policiaguardamar.com"}
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
REQUEST_TIMEOUT_SECONDS = 10
PAGE_LIMIT_BYTES = 200_000
RUSSIAN_MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

_NOTICE_PATTERN = re.compile(
    r"acceder\s+al\s+centro\s+de\s+salud\s+y\s+terminal\s+de\s+"
    r"autobuses\s+debe\s+acceder\s+desde\s+la\s+c/?\s*san\s+"
    r"francisco.{0,300}?resto\s+de\s+accesos\s+estaran\s+cerrados\s+"
    r"al\s+trafico.{0,200}?periodo\s+de\s+fiestas.{0,200}?desde\s+el\s+"
    r"(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+julio",
    re.IGNORECASE | re.DOTALL,
)


class PoliceTrafficError(RuntimeError):
    """Raised when the official traffic page cannot be used safely."""


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _active_period_prefix(
    start_day: int,
    end_day: int,
    month: int,
    current_day: int,
) -> str:
    month_name = RUSSIAN_MONTHS[month]
    if current_day > start_day:
        return f"До {end_day} {month_name}"
    return f"{start_day}–{end_day} {month_name}"


def _read_page() -> bytes:
    request = urllib.request.Request(
        TRAFFIC_URL,
        headers={
            "Accept": "text/html",
            "User-Agent": "GuardamarMorningDigest/0.5",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                raise PoliceTrafficError(
                    "Policía Local returned an unexpected redirect"
                )
            payload = response.read(PAGE_LIMIT_BYTES + 1)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise PoliceTrafficError(
            "Policía Local traffic request failed"
        ) from exc
    if len(payload) > PAGE_LIMIT_BYTES:
        raise PoliceTrafficError(
            "Policía Local traffic response was too large"
        )
    return payload


def normalize_traffic_page(
    payload: bytes,
    now: datetime,
) -> Tuple[TrafficNotice, ...]:
    """Return the explicit festival access notice only while active."""

    parser = _TextParser()
    decoded = payload.decode("utf-8", "replace")
    if "\ufffd" in decoded:
        decoded = payload.decode("iso-8859-1", "replace")
    parser.feed(decoded)
    page_text = " ".join(" ".join(parser.parts).split())
    normalized_text = unicodedata.normalize("NFKD", page_text)
    normalized_text = "".join(
        character
        for character in normalized_text
        if not unicodedata.combining(character)
    )
    match = _NOTICE_PATTERN.search(normalized_text)
    if match is None:
        return ()

    start_day, end_day = (int(value) for value in match.groups())
    if not (1 <= start_day <= end_day <= 31):
        return ()
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if local_day.month != 7 or not start_day <= local_day.day <= end_day:
        return ()

    return (
        TrafficNotice(
            text=(
                f"{_active_period_prefix(start_day, end_day, 7, local_day.day)}"
                ": проезд к поликлинике и "
                "автовокзалу — только через C/ San Francisco."
            ),
        ),
    )


def _plain_text(payload: bytes) -> str:
    decoded = payload.decode("utf-8", "replace")
    if "\ufffd" in decoded:
        decoded = payload.decode("iso-8859-1", "replace")
    parser = _TextParser()
    parser.feed(decoded)
    return " ".join(" ".join(parser.parts).split())


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return " ".join(
        "".join(
            character
            for character in decomposed
            if not unicodedata.combining(character)
        ).casefold().split()
    )


def validate_ai_notice(
    candidate: Dict[str, Any],
    source_text: str,
    now: datetime,
) -> Tuple[TrafficNotice, ...]:
    """Accept Gemini output only when source facts are mechanically proven."""

    if candidate.get("publish") is not True:
        return ()
    evidence = candidate.get("evidence_es")
    message = candidate.get("message_ru")
    streets = candidate.get("streets")
    date_fields = (
        candidate.get("start_day"),
        candidate.get("start_month"),
        candidate.get("end_day"),
        candidate.get("end_month"),
    )
    if (
        not isinstance(evidence, str)
        or not isinstance(message, str)
        or not isinstance(streets, list)
        or not streets
        or not all(
            isinstance(street, str) and 1 <= len(street) <= 80
            for street in streets
        )
        or not all(isinstance(value, int) for value in date_fields)
        or not 1 <= len(message) <= 180
        or len(evidence) > 1_500
    ):
        return ()

    normalized_source = _normalized(source_text)
    normalized_evidence = _normalized(evidence)
    if not normalized_evidence or normalized_evidence not in normalized_source:
        return ()
    if not any(
        marker in normalized_evidence
        for marker in ("corte", "cerrad", "restric", "trafico")
    ):
        return ()
    if any(
        _normalized(street) not in normalized_evidence
        or street.casefold() not in message.casefold()
        for street in streets
    ):
        return ()

    start_day, start_month, end_day, end_month = date_fields
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    try:
        start = local_day.replace(month=start_month, day=start_day)
        end = local_day.replace(month=end_month, day=end_day)
    except ValueError:
        return ()
    if end < start or not start <= local_day <= end:
        return ()
    if str(start_day) not in evidence or str(end_day) not in evidence:
        return ()
    message = " ".join(message.split())
    if local_day > start:
        message = re.sub(
            r"^\d{1,2}\s*[–-]\s*\d{1,2}\s+[^:]{2,16}:",
            f"До {end.day} {RUSSIAN_MONTHS[end.month]}:",
            message,
            count=1,
        )
    return (TrafficNotice(text=message),)


async def fetch_traffic_notices(
    now: datetime,
    gemini_api_key: Optional[str] = None,
) -> Tuple[TrafficNotice, ...]:
    """Fetch today's explicit official traffic restriction."""

    payload = await asyncio.to_thread(_read_page)
    known_notice = normalize_traffic_page(payload, now)
    if known_notice:
        return known_notice
    source_text = _plain_text(payload)
    if _NOTICE_PATTERN.search(_normalized(source_text)):
        return ()
    if not gemini_api_key:
        return ()
    try:
        candidate = await translate_traffic_notice(
            gemini_api_key,
            source_text,
            now.astimezone(GUARDAMAR_TIMEZONE).date(),
        )
    except GeminiError as exc:
        raise PoliceTrafficError("Gemini traffic translation failed") from exc
    return validate_ai_notice(candidate, source_text, now)
