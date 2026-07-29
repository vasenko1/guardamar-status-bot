"""Small Gemini client for structured municipal-notice translation."""

import asyncio
import base64
import json
import urllib.error
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
            "maxItems": 2,
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


class GeminiError(RuntimeError):
    """Raised when Gemini cannot return a trustworthy structured response."""


def _request_json(
    api_key: str,
    parts: List[Dict[str, Any]],
    schema: Optional[Dict[str, Any]],
    max_output_tokens: int,
) -> Dict[str, Any]:
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
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GuardamarMorningDigest/0.7",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = response.read(RESPONSE_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(2_000).decode("utf-8", "replace")
            parsed = json.loads(detail)
            reason = str(parsed.get("error", {}).get("message", ""))[:300]
        except (AttributeError, json.JSONDecodeError):
            reason = ""
        suffix = f": {reason}" if reason else ""
        raise GeminiError(f"Gemini request failed{suffix}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GeminiError("Gemini request failed") from exc
    if len(payload) > RESPONSE_LIMIT_BYTES:
        raise GeminiError("Gemini response was too large")
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
        raise GeminiError("Gemini returned an invalid response") from exc
    if not isinstance(result, dict):
        raise GeminiError("Gemini returned an invalid result")
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
    prompt = (
        "Read this official monthly municipal agenda poster for Guardamar del "
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
        None,
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


def _translate_event_titles(
    api_key: str,
    titles: Sequence[str],
) -> Dict[str, Any]:
    prompt = (
        "Translate these official Spanish event titles concisely into Russian. "
        "Preserve proper names. Return exactly one title for each input in the "
        "same order, without dates, places, bullets, explanations, or invented "
        "details:\n" + json.dumps(list(titles), ensure_ascii=False)
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
    """Translate at most two selected titles without persisting the result."""

    if not 1 <= len(titles) <= 2:
        raise ValueError("one or two event titles are required")
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
            isinstance(title, str) and 1 <= len(title.strip()) <= 80
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
