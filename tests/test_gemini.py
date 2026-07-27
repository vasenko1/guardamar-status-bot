import json
import unittest
from datetime import date
from unittest.mock import patch

from telegrambot.gemini import _request_translation


class _GeminiResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        result = {
            "publish": False,
            "evidence_es": "",
            "message_ru": "",
            "streets": [],
            "start_day": None,
            "start_month": None,
            "end_day": None,
            "end_month": None,
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


class GeminiRequestTests(unittest.TestCase):
    def test_requests_pinned_model_and_structured_json(self):
        with patch(
            "telegrambot.gemini.urllib.request.urlopen",
            return_value=_GeminiResponse(),
        ) as urlopen:
            result = _request_translation(
                "secret-key",
                "Página oficial",
                date(2026, 7, 27),
            )

        request = urlopen.call_args.args[0]
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
