"""Small Gemini client for structured municipal-notice translation."""

import asyncio
import base64
import json
import logging
import os
import urllib.parse
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from ._transport import BoundedFetchError, fetch_bounded
from .openrouter import OpenRouterError, request_json as request_openrouter_json

LOGGER = logging.getLogger(__name__)
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
                    "evidence_es": {"type": ["string", "null"]},
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
                    "evidence_es",
                    "category",
                ],
            },
        },
    },
    "required": ["month", "events"],
}


class GeminiError(RuntimeError):
    """An operator-safe structured-model protocol or validation failure."""

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


_TRANSPORT_DESCRIPTIONS = {
    "REDIRECT": "получен недопустимый адрес ответа Gemini",
    "CONTENT-TYPE": "Gemini вернул ответ не в формате JSON",
    "TIMEOUT": "Gemini не ответил до истечения тайм-аута",
    "NETWORK": "не удалось установить соединение с Gemini",
    "TOO-LARGE": "ответ Gemini превысил допустимый размер",
}


def _http_error(exc: BoundedFetchError) -> GeminiError:
    provider_status = ""
    payload = exc.payload
    try:
        if payload is not None and len(payload) <= 2_000:
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
        else f"HTTP-{exc.status}"
    )
    return GeminiError(
        f"Gemini returned HTTP {exc.status}",
        code=code,
        status=exc.status,
        description=(
            f"Gemini вернул HTTP {exc.status}"
            + (
                f" ({provider_status})"
                if provider_status
                else ""
            )
        ),
    )


def _request_gemini_json(
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
    try:
        payload, _, _ = fetch_bounded(
            ENDPOINT,
            is_allowed_url=_is_gemini_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "GuardamarMorningDigest/0.12",
                "x-goog-api-key": api_key,
            },
            method="POST",
            data=body,
            read_error_body=True,
        )
    except BoundedFetchError as exc:
        if exc.status is not None:
            raise _http_error(exc) from exc
        raise GeminiError(
            f"Gemini request failed: {exc.code}",
            code=exc.code,
            description=_TRANSPORT_DESCRIPTIONS.get(exc.code),
        ) from exc
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


def _request_json(
    api_key: str,
    parts: List[Dict[str, Any]],
    schema: Optional[Dict[str, Any]],
    max_output_tokens: int,
) -> Dict[str, Any]:
    try:
        return _request_gemini_json(
            api_key,
            parts,
            schema,
            max_output_tokens,
        )
    except GeminiError as primary_error:
        fallback_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not fallback_key:
            raise
        LOGGER.warning(
            "Gemini failed [%s]; using OpenRouter fallback",
            primary_error.diagnostic_code,
        )
        try:
            return request_openrouter_json(
                fallback_key,
                parts,
                schema,
                max_output_tokens,
            )
        except OpenRouterError as fallback_error:
            primary_description = (
                primary_error.safe_description or "Gemini вернул ошибку"
            )
            fallback_description = (
                fallback_error.safe_description
                or "OpenRouter вернул ошибку"
            )
            raise GeminiError(
                "Both structured LLM providers failed",
                code=f"FALLBACK-{fallback_error.diagnostic_code}",
                status=fallback_error.server_status,
                description=(
                    f"{primary_description}; резерв: {fallback_description}"
                ),
            ) from fallback_error


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
        "category. Set evidence_es to null because the source is an image. "
        "Use null for unknown optional values. category must be "
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
        "HH:MM times, and the poster month as YYYY-MM. Set evidence_es to null "
        "because the source is an image."
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
        "each repeated date into its own event record. Make title_es a concise, "
        "self-contained digest title of at most 120 characters. Preserve the "
        "explicit event kind and named act or work. When the same event row "
        "explicitly says that it is a tribute, benefit event, or for a named "
        "audience or cause, keep that short purpose in title_es. Never reduce "
        "'concierto benéfico ... tributo a Il Divo ... Trivox' to only "
        "'TRIVOX'. Preserve official dates, times and places; do not infer missing "
        "facts. Exhibition visiting hours printed with the exhibition are its "
        "start_time and end_time. Use ISO YYYY-MM-DD dates and HH:MM times. "
        "Classify routine facility schedules as opening_hours and routine "
        "administrative services as municipal_service. Return the fixed JSON "
        "schema and use null for unknown optional fields. evidence_es must be "
        "one exact contiguous quotation from OFFICIAL TEXT that contains the "
        "event identity and supports the enriched title.\n\nOFFICIAL TEXT:\n"
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
