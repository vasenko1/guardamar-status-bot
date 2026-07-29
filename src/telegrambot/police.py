"""Fetch explicit traffic restrictions from Policía Local Guardamar."""

import asyncio
import hashlib
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .models import TrafficMeasure, TrafficNotice
from .gemini import GeminiError, translate_traffic_notice

TRAFFIC_URL = "https://policiaguardamar.com/cortecallefiestas.html"
FESTIVAL_PDF_URL = (
    "https://policiaguardamar.com/pdf/cortecalle_fiestas13.pdf"
)
FESTIVAL_PDF_SHA256 = (
    "267a199ec1bb83abfc47f618bd208496733a252659476d434ab30082a35ce38e"
)
ALLOWED_HOSTS = {"policiaguardamar.com", "www.policiaguardamar.com"}
GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")
REQUEST_TIMEOUT_SECONDS = 10
PAGE_LIMIT_BYTES = 200_000
PDF_LIMIT_BYTES = 100_000
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
_FESTIVAL_PDF_PATTERN = re.compile(
    r"(?:https?://(?:www\.)?policiaguardamar\.com/)?"
    r"pdf/cortecalle_fiestas13\.pdf",
    re.IGNORECASE,
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


def _read_festival_pdf() -> bytes:
    request = urllib.request.Request(
        FESTIVAL_PDF_URL,
        headers={"User-Agent": "GuardamarMorningDigest/0.10"},
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                raise PoliceTrafficError(
                    "Policía Local PDF returned an unexpected redirect"
                )
            payload = response.read(PDF_LIMIT_BYTES + 1)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise PoliceTrafficError(
            "Policía Local traffic document request failed"
        ) from exc
    if len(payload) > PDF_LIMIT_BYTES:
        raise PoliceTrafficError(
            "Policía Local traffic document was too large"
        )
    return payload


def _festival_notice(
    now: datetime,
    document_digest: str,
) -> Tuple[TrafficNotice, ...]:
    """Render only the active measure from the reviewed official PDF."""

    if document_digest != FESTIVAL_PDF_SHA256:
        return ()
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    if local_day.month != 7 or not 22 <= local_day.day <= 29:
        return ()
    start = date(local_day.year, 7, 22)
    end = date(local_day.year, 7, 29)
    measure = TrafficMeasure(
        action="road_closed",
        location="Molivent",
        valid_from=start,
        valid_until=end,
        daily_hours=None,
        affected="all_traffic",
        exceptions="light_vehicles_until_23:30",
        alternative="La Redonda; San Francisco for light vehicles until 23:30",
        destinations=("Centro de Salud", "Terminal de Autobuses"),
    )
    return (
        TrafficNotice(
            text=(
                f"{_active_period_prefix(22, 29, 7, local_day.day)} "
                "перекрыта улица Molivent. К поликлинике и автовокзалу — "
                "через La Redonda; легковым авто также через San Francisco "
                "до 23:30."
            ),
            measures=(measure,),
            source_url=FESTIVAL_PDF_URL,
        ),
    )


def normalize_traffic_page(
    payload: bytes,
    now: datetime,
    document_digest: Optional[str] = None,
) -> Tuple[TrafficNotice, ...]:
    """Return a reviewed known notice; unknown pages use the AI fallback."""

    decoded = payload.decode("utf-8", "replace")
    if _FESTIVAL_PDF_PATTERN.search(decoded):
        if document_digest is None:
            return ()
        return _festival_notice(now, document_digest)
    parser = _TextParser()
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

    # The old HTML summary omits Molivent and reverses the routing detail
    # contained in the reviewed PDF. Never publish it by itself.
    return ()


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
    measures = candidate.get("measures")
    if not isinstance(measures, list) or not 1 <= len(measures) <= 4:
        return ()

    normalized_source = _normalized(source_text)
    local_day = now.astimezone(GUARDAMAR_TIMEZONE).date()
    notices = []
    allowed_actions = {
        "road_closed",
        "access_restricted",
        "parking_prohibited",
        "lane_occupied",
        "direction_changed",
        "speed_or_manoeuvre_restricted",
        "transit_changed",
        "avoid_area",
    }
    for item in measures:
        if not isinstance(item, dict):
            return ()
        evidence = item.get("evidence_es")
        message = item.get("message_ru")
        streets = item.get("streets")
        action = item.get("action")
        location = item.get("location")
        destinations = item.get("destinations")
        optional_fields = (
            item.get("daily_hours"),
            item.get("affected"),
            item.get("exceptions"),
            item.get("alternative"),
        )
        date_fields = (
            item.get("start_day"),
            item.get("start_month"),
            item.get("end_day"),
            item.get("end_month"),
        )
        if (
            action not in allowed_actions
            or not isinstance(evidence, str)
            or not isinstance(message, str)
            or not isinstance(location, str)
            or not 1 <= len(location) <= 120
            or not isinstance(streets, list)
            or not streets
            or not all(
                isinstance(street, str) and 1 <= len(street) <= 80
                for street in streets
            )
            or not isinstance(destinations, list)
            or not all(
                isinstance(value, str) and 1 <= len(value) <= 100
                for value in destinations
            )
            or not all(
                value is None
                or isinstance(value, str) and len(value) <= 160
                for value in optional_fields
            )
            or not all(isinstance(value, int) for value in date_fields)
            or not 1 <= len(message) <= 180
            or len(evidence) > 1_500
        ):
            return ()
        normalized_evidence = _normalized(evidence)
        if (
            not normalized_evidence
            or normalized_evidence not in normalized_source
            or not any(
                marker in normalized_evidence
                for marker in (
                    "corte",
                    "cerrad",
                    "restric",
                    "trafico",
                    "estacion",
                    "desvio",
                    "carril",
                    "parada",
                )
            )
        ):
            return ()
        if any(
            _normalized(street) not in normalized_evidence
            or street.casefold() not in message.casefold()
            for street in streets
        ):
            return ()
        start_day, start_month, end_day, end_month = date_fields
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
        measure = TrafficMeasure(
            action=action,
            location=location,
            valid_from=start,
            valid_until=end,
            daily_hours=item.get("daily_hours"),
            affected=item.get("affected"),
            exceptions=item.get("exceptions"),
            alternative=item.get("alternative"),
            destinations=tuple(destinations),
        )
        notices.append(
            TrafficNotice(
                text=message,
                measures=(measure,),
                source_url=TRAFFIC_URL,
            )
        )
    return tuple(notices[:2])


async def fetch_traffic_notices(
    now: datetime,
    gemini_api_key: Optional[str] = None,
) -> Tuple[TrafficNotice, ...]:
    """Fetch today's explicit official traffic restriction."""

    payload = await asyncio.to_thread(_read_page)
    decoded = payload.decode("utf-8", "replace")
    document_digest = None
    if _FESTIVAL_PDF_PATTERN.search(decoded):
        document = await asyncio.to_thread(_read_festival_pdf)
        document_digest = hashlib.sha256(document).hexdigest()
    known_notice = normalize_traffic_page(payload, now, document_digest)
    if known_notice:
        return known_notice
    if _FESTIVAL_PDF_PATTERN.search(decoded):
        return ()
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
