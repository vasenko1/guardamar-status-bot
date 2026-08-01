import asyncio
import json
import unittest
from datetime import date
from email.message import Message
from unittest.mock import patch

from telegrambot.gemini import (
    AGENDA_EXTRACTION_SCHEMA,
    _extract_agenda_events,
    _extract_agenda_text_events,
    _request_translation,
    translate_event_titles,
)


class _GeminiResponse:
    status = 200

    def __init__(self, content_type="application/json"):
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        result = {
            "publish": False,
            "measures": [],
        }
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": json.dumps(result)}
                            ]
                        }
                    }
                ]
            }
        ).encode()

    def geturl(self):
        return (
            "https://generativelanguage.googleapis.com/"
            "v1beta/models/gemini-3.5-flash-lite:generateContent"
        )


class _Opener:
    def __init__(self, response):
        self.response = response
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return self.response


class GeminiRequestTests(unittest.TestCase):
    def test_event_translation_accepts_full_valid_event_length(self):
        translated = "Д" * 100
        with patch(
            "telegrambot.gemini._translate_event_titles",
            return_value={"titles_ru": [translated]},
        ):
            result = asyncio.run(translate_event_titles("key", ["Título"]))

        self.assertEqual(result, [translated])

    def test_agenda_ocr_uses_fixed_response_schema(self):
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"month": "2026-08", "events": []},
        ) as request_json:
            _extract_agenda_events(
                "secret-key",
                b"image",
                "image/jpeg",
            )

        self.assertIs(
            request_json.call_args.args[2],
            AGENDA_EXTRACTION_SCHEMA,
        )

    def test_agenda_text_uses_schema_without_inline_media(self):
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"month": "2026-08", "events": []},
        ) as request_json:
            result = _extract_agenda_text_events(
                "secret-key",
                "AGENDA CULTURAL AGOSTO 2026. 6 de agosto concierto.",
            )

        self.assertEqual(result["month"], "2026-08")
        self.assertIs(
            request_json.call_args.args[2],
            AGENDA_EXTRACTION_SCHEMA,
        )
        self.assertNotIn("inlineData", str(request_json.call_args.args[1]))

    def test_agenda_pdf_is_an_accepted_document_format(self):
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"month": "2026-08", "events": []},
        ):
            result = _extract_agenda_events(
                "secret-key", b"%PDF", "application/pdf"
            )

        self.assertEqual(result["month"], "2026-08")

    def test_requests_pinned_model_and_structured_json(self):
        opener = _Opener(_GeminiResponse())
        with patch(
            "telegrambot.gemini.urllib.request.build_opener",
            return_value=opener,
        ):
            result = _request_translation(
                "secret-key",
                "Página oficial",
                date(2026, 7, 27),
            )

        request = opener.request
        body = json.loads(request.data.decode())
        self.assertIn("gemini-3.5-flash-lite", request.full_url)
        self.assertEqual(
            request.headers["X-goog-api-key"],
            "secret-key",
        )
        self.assertEqual(
            body["generationConfig"]["responseMimeType"],
            "application/json",
        )
        self.assertIn(
            "responseJsonSchema",
            body["generationConfig"],
        )
        self.assertFalse(result["publish"])


if __name__ == "__main__":
    unittest.main()
