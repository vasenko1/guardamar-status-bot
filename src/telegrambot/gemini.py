"""Small Gemini client for structured municipal-notice translation."""

import asyncio
import base64
import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

MODEL = "gemini-3.5-flash-lite"
ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent"
)
REQUEST_TIMEOUT_SECONDS = 45
RESPONSE_LIMIT_BYTES = 100_000
MAX_SOURCE_CHARACTERS = 12_000
API_HOST = "generativelanguage.googleapis.com"
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
AGENDA_MEDIA_MIME_TYPES = IMAGE_MIME_TYPES | {"application/pdf"}

TRAFFIC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "publish": {"type": "boolean"},
        "measures": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "road_closed",
                            "access_restricted",
                            "parking_prohibited",
                            "lane_occupied",
                            "direction_changed",
                            "speed_or_manoeuvre_restricted",
                            "transit_changed",
                            "avoid_area",
                        ],
                    },
                    "evidence_es": {"type": "string"},
                    "message_ru": {"type": "string"},
                    "location": {"type": "string"},
                    "streets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                    },
                    "start_day": {"type": ["integer", "null"]},
                    "start_month": {"type": ["integer", "null"]},
                    "end_day": {"type": ["integer", "null"]},
                    "end_month": {"type": ["integer", "null"]},
                    "daily_hours": {"type": ["string", "null"]},
                    "affected": {"type": ["string", "null"]},
                    "exceptions": {"type": ["string", "null"]},
                    "alternative": {"type": ["string", "null"]},
                    "destinations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 6,
                    },
                },
                "required": [
                    "action",
                    "evidence_es",
                    "message_ru",
                    "location",
                    "streets",
                    "start_day",
                    "start_month",
                    "end_day",
                    "end_month",
                    "daily_hours",
                    "affected",
                    "exceptions",
                    "alternative",
                    "destinations",
                ],
            },
        },
    },
    "required": ["publish", "measures"],
}
EVENT_TRANSLATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "titles_ru": {
            "type": "array",
            "maxItems": 80,
            "items": {"type": "string"},
        }
    },
    "required": ["titles_ru"],
}
MARKET_STATUS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cancelled": {"type": "boolean"},
        "evidence_es": {"type": "string"},
        "event_date": {"type": ["string", "null"]},
    },
    "required": ["cancelled", "evidence_es", "event_date"],
}
AGENDA_EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "month": {"type": "string"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title_es": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": ["string", "null"]},
                    "start_time": {"type": ["string", "null"]},
                    "end_time": {"type": ["string", "null"]},
                    "place": {"type": ["string", "null"]},
                    "category": {
                        "type": "string",
                        "enum": [
                            "event",
                            "exhibition",
                            "workshop",
                            "municipal_service",
                            "opening_hours",
                        ],
                    },
                },
                "required": [
                    "title_es",
                    "start_date",
                    "end_date",
                    "start_time",
                    "end_time",
                    "place",
                    "category",
                ],
            },
        },
    },
    "required": ["month", "events"],
}


class GeminiError(RuntimeError):
    """An operator-safe Gemini protocol or validation failure."""

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


def _is_gemini_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == API_HOST


class _GeminiRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if not _is_gemini_url(new_url):
            raise GeminiError(
                "Gemini redirected outside its API host",
                code="REDIRECT",
                description="Gemini перенаправил запрос на другой сайт",
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _http_error(exc: urllib.error.HTTPError) -> GeminiError:
    provider_status = ""
    try:
        payload = exc.read(2_001)
        if len(payload) <= 2_000:
            decoded = json.loads(payload.decode("utf-8"))
            raw_status = decoded.get("error", {}).get("status")
            if (
                isinstance(raw_status, str)
                and raw_status.replace("_", "").isalnum()
                and len(raw_status) <= 50
            ):
                provider_status = raw_status
    except (
        AttributeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        pass
    code = (
        f"API-{provider_status}"
        if provider_status
        else f"HTTP-{exc.code}"
    )
    return GeminiError(
        f"Gemini returned HTTP {exc.code}",
        code=code,
        status=exc.code,
        description=(
            f"Gemini вернул HTTP {exc.code}"
            + (
                f" ({provider_status})"
                if provider_status
                else ""
            )
        ),
    )


def _request_json(
    api_key: str,
    parts: List[Dict[str, Any]],
    schema: Optional[Dict[str, Any]],
    max_output_tokens: int,
) -> Dict[str, Any]:
    if not api_key or any(character in api_key for character in "\r\n"):
        raise GeminiError(
            "Gemini configuration is invalid",
            code="CONFIG",
            description="ключ Gemini отсутствует или имеет неверный формат",
        )
    generation_config: Dict[str, Any] = {
        "responseMimeType": "application/json",
        "maxOutputTokens": max_output_tokens,
    }
    if schema is not None:
        generation_config["responseJsonSchema"] = schema
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GuardamarMorningDigest/0.12",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_GeminiRedirectHandler())
    try:
        with opener.open(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            if not _is_gemini_url(response.geturl()):
                raise GeminiError(
                    "Gemini returned an unexpected response URL",
                    code="REDIRECT",
                    description="получен недопустимый адрес ответа Gemini",
                )
            if response.headers.get_content_type() != "application/json":
                raise GeminiError(
                    "Gemini returned an unexpected content type",
                    code="CONTENT-TYPE",
                    description="Gemini вернул ответ не в формате JSON",
                )
            payload = response.read(RESPONSE_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
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
        raise GeminiError(
            "Gemini request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
            description=(
                "Gemini не ответил до истечения тайм-аута"
                if timed_out
                else "не удалось установить соединение с Gemini"
            ),
        ) from exc
    if len(payload) > RESPONSE_LIMIT_BYTES:
        raise GeminiError(
            "Gemini response was too large",
            code="TOO-LARGE",
            description="ответ Gemini превысил допустимый размер",
        )
    try:
        response_data = json.loads(payload.decode("utf-8"))
        candidates = response_data["candidates"]
        text = candidates[0]["content"]["parts"][0]["text"]
        result = json.loads(text)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise GeminiError(
            "Gemini returned an invalid response",
            code="INVALID-RESPONSE",
            description="Gemini вернул некорректный JSON-ответ",
        ) from exc
    if not isinstance(result, dict):
        raise GeminiError(
            "Gemini returned an invalid result",
            code="INVALID-STRUCTURE",
            description="структура результата Gemini некорректна",
        )
    return result


def _request_translation(
    api_key: str,
    source_text: str,
    local_day: date,
) -> Dict[str, Any]:
    prompt = (
        "Extract every independently active mobility measure from this "
        "official Policía Local Guardamar page. A notice may combine closures, "
        "access restrictions, parking bans, occupied lanes, direction or "
        "manoeuvre changes, public-transport changes, and avoid-area advice. "
        "Never infer missing facts. Split different date/time periods into "
        "different measures. Include only measures active on CURRENT_DATE. "
        "For each measure, evidence_es must be one exact contiguous quotation "
        "from SOURCE that contains its restriction, location, dates, hours, "
        "affected users, exceptions and alternative route when those details "
        "are claimed. Copy street names unchanged into streets, location and "
        "message_ru. Keep each Russian message factual and at most 180 "
        "characters. Set publish=false and return an empty measures array when "
        "nothing can be extracted safely.\n\n"
        f"CURRENT_DATE: {local_day.isoformat()}\n"
        f"SOURCE:\n{source_text[:MAX_SOURCE_CHARACTERS]}"
    )
    return _request_json(
        api_key,
        [{"text": prompt}],
        TRAFFIC_SCHEMA,
        500,
    )


async def translate_traffic_notice(
    api_key: str,
    source_text: str,
    local_day: date,
) -> Dict[str, Any]:
    """Return Gemini's structured candidate for deterministic validation."""

    return await asyncio.to_thread(
        _request_translation,
        api_key,
        source_text,
        local_day,
    )


def _extract_agenda_events(
    api_key: str,
    image: bytes,
    mime_type: str,
) -> Dict[str, Any]:
    if mime_type not in AGENDA_MEDIA_MIME_TYPES:
        raise GeminiError(
            "Unsupported municipal poster image type",
            code="CONTENT-TYPE",
            description="формат муниципальной программы не поддерживается",
        )
    prompt = (
        "Read this official monthly municipal agenda document for Guardamar del "
        "Segura. Return every explicitly dated activity, exhibition, workshop, "
        "concert, tour, festival act, or neighbourhood event. Expand repeated "
        "dates into separate records. Make title_es a concise user-facing "
        "title that preserves every explicit activity type and medium, such "
        "as exposición de pintura, exposición de pintura y escultura, ruta "
        "nocturna, concert, workshop, or guided tour. Apply a visible section "
        "heading such as EXPOSICIÓN DE PINTURA to every activity directly "
        "under that heading. Preserve proper names in the source language. "
        "Transcribe every visible time digit exactly; never estimate or "
        "normalize a hard-to-read digit, and use null when it is not legible. "
        "Use ISO YYYY-MM-DD dates and HH:MM 24-hour time. Preserve an explicit "
        "time range as start_time and end_time. Treat opening hours printed "
        "inside a specific exhibition card as that exhibition's daily time "
        "range, not as a separate opening_hours record. "
        "For exhibitions use "
        "the first and last date. Classify routine facility schedules as "
        "opening_hours and waste/mobile administrative services as "
        "municipal_service. Do not invent unreadable fields. Return one JSON "
        "object with month as YYYY-MM and events as an array. Every event must "
        "contain title_es, start_date, end_date, start_time, end_time, place, and "
        "category. Use null for unknown optional values. category must be "
        "event, exhibition, workshop, municipal_service, or opening_hours."
    )
    return _request_json(
        api_key,
        [
            {"text": prompt},
            {
                "inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(image).decode("ascii"),
                }
            },
        ],
        AGENDA_EXTRACTION_SCHEMA,
        8_000,
    )


async def extract_agenda_events(
    api_key: str,
    image: bytes,
    mime_type: str,
) -> Dict[str, Any]:
    """Extract structured source-language facts from one official poster."""

    return await asyncio.to_thread(
        _extract_agenda_events,
        api_key,
        image,
        mime_type,
    )


def _verify_agenda_poster_events(
    api_key: str,
    image: bytes,
    mime_type: str,
) -> Dict[str, Any]:
    if mime_type not in IMAGE_MIME_TYPES:
        raise GeminiError(
            "Poster verification requires an image",
            code="CONTENT-TYPE",
            description="проверка MUPI требует изображение",
        )
    prompt = (
        "Independently read this official Guardamar monthly MUPI poster from "
        "scratch. You have not seen another extraction. Return every explicitly "
        "dated public activity, exhibition, workshop, concert, tour, festival "
        "act, or neighbourhood event. Expand repeated dates into separate "
        "records. Preserve every explicit activity type, date, time range and "
        "place. Transcribe visible digits exactly and use null for an absent or "
        "illegible time or place; never infer one from a facility schedule. "
        "Treat hours printed inside a specific exhibition card as that "
        "exhibition's hours. Exclude routine facility opening hours and "
        "municipal services using their schema categories. Use ISO dates, "
        "HH:MM times, and the poster month as YYYY-MM."
    )
    return _request_json(
        api_key,
        [
            {"text": prompt},
            {"inlineData": {
                "mimeType": mime_type,
                "data": base64.b64encode(image).decode("ascii"),
            }},
        ],
        AGENDA_EXTRACTION_SCHEMA,
        8_000,
    )


async def verify_agenda_poster_events(
    api_key: str,
    image: bytes,
    mime_type: str,
) -> Dict[str, Any]:
    """Extract a second MUPI reading without first-pass anchoring."""

    return await asyncio.to_thread(
        _verify_agenda_poster_events,
        api_key,
        image,
        mime_type,
    )


def _extract_agenda_text_events(
    api_key: str,
    source_text: str,
) -> Dict[str, Any]:
    source_text = " ".join(source_text.split())
    if not 1 <= len(source_text) <= MAX_SOURCE_CHARACTERS:
        raise GeminiError(
            "Municipal agenda text has an invalid size",
            code="SOURCE-SIZE",
            description="текст официальной программы имеет неверный размер",
        )
    prompt = (
        "Convert this official Spanish municipal cultural programme for "
        "Guardamar del Segura into structured event facts. Return every "
        "explicitly dated activity, exhibition, workshop, concert, tour, "
        "festival act, neighbourhood event, and repeated series date. Expand "
        "each repeated date into its own event record. Preserve official "
        "titles, activity types, dates, times and places; do not infer missing "
        "facts. Exhibition visiting hours printed with the exhibition are its "
        "start_time and end_time. Use ISO YYYY-MM-DD dates and HH:MM times. "
        "Classify routine facility schedules as opening_hours and routine "
        "administrative services as municipal_service. Return the fixed JSON "
        "schema and use null for unknown optional fields.\n\nOFFICIAL TEXT:\n"
        + source_text
    )
    return _request_json(
        api_key,
        [{"text": prompt}],
        AGENDA_EXTRACTION_SCHEMA,
        8_000,
    )


async def extract_agenda_text_events(
    api_key: str,
    source_text: str,
) -> Dict[str, Any]:
    """Structure bounded official agenda text without image recognition."""

    return await asyncio.to_thread(
        _extract_agenda_text_events,
        api_key,
        source_text,
    )


def _translate_event_titles(
    api_key: str,
    titles: Sequence[str],
) -> Dict[str, Any]:
    prompt = (
        "Translate these official Spanish event titles concisely into Russian. "
        "Use normal Russian sentence case even when the source is uppercase. "
        "Preserve proper names and title punctuation exactly: a comma must not "
        "be replaced by a dash or colon. Return exactly one title for each "
        "input in the same order, without dates, places, bullets, explanations, "
        "or invented details:\n" + json.dumps(list(titles), ensure_ascii=False)
    )
    return _request_json(
        api_key,
        [{"text": prompt}],
        EVENT_TRANSLATION_SCHEMA,
        300,
    )


async def translate_event_titles(
    api_key: str,
    titles: Sequence[str],
) -> List[str]:
    """Translate one bounded set of selected titles without persisting it."""

    if not 1 <= len(titles) <= 80:
        raise ValueError("between one and 80 event titles are required")
    result = await asyncio.to_thread(
        _translate_event_titles,
        api_key,
        titles,
    )
    translated = result.get("titles_ru")
    if (
        not isinstance(translated, list)
        or len(translated) != len(titles)
        or not all(
            isinstance(title, str) and 1 <= len(title.strip()) <= 120
            for title in translated
        )
    ):
        raise GeminiError("Gemini returned invalid event translations")
    return [title.strip() for title in translated]


def _request_market_status(
    api_key: str,
    source_text: str,
    local_day: date,
) -> Dict[str, Any]:
    prompt = (
        "Check official municipal Telegram posts for an explicit cancellation "
        "or move of Guardamar's regular Wednesday market on TARGET_DATE. "
        "Do not treat unrelated markets, past dates, weather warnings, or mere "
        "schedule descriptions as cancellation. evidence_es must be one exact "
        "contiguous quotation from SOURCE. Set cancelled=false with empty "
        "evidence_es and null event_date unless the statement and exact date "
        "are explicit.\n\n"
        f"TARGET_DATE: {local_day.isoformat()}\n"
        f"SOURCE:\n{source_text[:MAX_SOURCE_CHARACTERS]}"
    )
    return _request_json(
        api_key,
        [{"text": prompt}],
        MARKET_STATUS_SCHEMA,
        300,
    )


async def extract_market_status(
    api_key: str,
    source_text: str,
    local_day: date,
) -> Dict[str, Any]:
    """Return a structured market cancellation candidate."""

    return await asyncio.to_thread(
        _request_market_status,
        api_key,
        source_text,
        local_day,
    )
