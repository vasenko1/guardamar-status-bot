import asyncio
import json
import unittest
from datetime import date
from unittest.mock import patch

from telegrambot.gemini import (
    AGENDA_EXTRACTION_SCHEMA,
    TRAFFIC_NOTICE_SCHEMA,
    GeminiError,
    _extract_agenda_events,
    _extract_agenda_text_events,
    _read_fiesta_programme_poster,
    _request_json,
    _verify_agenda_poster_events,
    _compose_traffic_notice,
    compose_traffic_notice,
    translate_event_titles,
)


class GeminiRequestTests(unittest.TestCase):
    def test_uses_openrouter_once_after_gemini_failure(self):
        expected = {"publish": False, "measures": []}
        with patch(
            "telegrambot.gemini._request_gemini_json",
            side_effect=GeminiError(
                "unavailable",
                code="HTTP-503",
                description="Gemini вернул HTTP 503",
            ),
        ), patch.dict(
            "telegrambot.gemini.os.environ",
            {"OPENROUTER_API_KEY": "reserve-key"},
            clear=False,
        ), patch(
            "telegrambot.gemini.request_openrouter_json",
            return_value=expected,
        ) as fallback:
            result = _request_json(
                "gemini-key",
                [{"text": "test"}],
                None,
                100,
            )

        self.assertEqual(result, expected)
        fallback.assert_called_once_with(
            "reserve-key",
            [{"text": "test"}],
            None,
            100,
        )

    def test_preserves_gemini_error_without_fallback_key(self):
        primary = GeminiError("unavailable", code="HTTP-503")
        with patch(
            "telegrambot.gemini._request_gemini_json",
            side_effect=primary,
        ), patch.dict(
            "telegrambot.gemini.os.environ",
            {},
            clear=True,
        ):
            with self.assertRaises(GeminiError) as raised:
                _request_json(
                    "gemini-key",
                    [{"text": "test"}],
                    None,
                    100,
                )

        self.assertIs(raised.exception, primary)

    def test_reports_both_provider_failures(self):
        from telegrambot.openrouter import OpenRouterError

        with patch(
            "telegrambot.gemini._request_gemini_json",
            side_effect=GeminiError(
                "unavailable",
                code="HTTP-503",
                description="Gemini вернул HTTP 503",
            ),
        ), patch.dict(
            "telegrambot.gemini.os.environ",
            {"OPENROUTER_API_KEY": "reserve-key"},
            clear=False,
        ), patch(
            "telegrambot.gemini.request_openrouter_json",
            side_effect=OpenRouterError(
                "timeout",
                code="TIMEOUT",
                description="OpenRouter не ответил до тайм-аута",
            ),
        ):
            with self.assertRaises(GeminiError) as raised:
                _request_json(
                    "gemini-key",
                    [{"text": "test"}],
                    None,
                    100,
                )

        self.assertEqual(
            raised.exception.diagnostic_code,
            "FALLBACK-TIMEOUT",
        )
        self.assertIn("Gemini вернул HTTP 503", raised.exception.safe_description)
        self.assertIn("OpenRouter", raised.exception.safe_description)

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

    def test_agenda_text_recovery_prompt_keeps_expected_dates_across_months(self):
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"month": "octubre", "events": []},
        ) as request_json:
            _extract_agenda_text_events(
                "secret-key",
                (
                    "26 de septiembre: Bingo Benéfico. "
                    "3 de octubre: XI Trofeo de Petanca."
                ),
                (
                    date(2026, 9, 26),
                    date(2026, 10, 3),
                ),
            )

        prompt = request_json.call_args.args[1][0]["text"]
        self.assertIn("EXPECTED_DATES", prompt)
        self.assertIn("2026-09-26", prompt)
        self.assertIn("2026-10-03", prompt)
        self.assertIn("may span several months", prompt)
        self.assertIn("must not limit", prompt)
        self.assertIn("nearest preceding explicit date heading", prompt)

    def test_fiesta_programme_prompt_keeps_two_column_same_day_acts_separate(self):
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"month": "2026-09", "events": []},
        ) as request_json:
            _read_fiesta_programme_poster(
                "secret-key",
                b"image",
                "image/jpeg",
                independent=True,
            )

        prompt = request_json.call_args.args[1][0]["text"]
        self.assertIn("two-column poster", prompt)
        self.assertIn("span two calendar months", prompt)
        self.assertIn("separate times", prompt)
        self.assertIn("transfer, Mass, presentation", prompt)
        self.assertIn("from scratch", prompt)

    def test_poster_verification_is_a_blind_second_reading(self):
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"month": "2026-08", "events": []},
        ) as request_json:
            _verify_agenda_poster_events(
                "secret-key",
                b"image",
                "image/jpeg",
            )

        prompt = request_json.call_args.args[1][0]["text"]
        self.assertIn("from scratch", prompt)
        self.assertNotIn("CANDIDATES", prompt)
        self.assertNotIn("supplied candidate", prompt)

    def test_traffic_notice_uses_fixed_schema_and_source_facts(self):
        facts = {
            "mode": "new_present",
            "category": "roadClosed",
            "street": "Avenida del Mediterráneo",
            "details_es": ["Cerrado"],
        }
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"body_ru": "В Гуардамаре перекрыт проезд."},
        ) as request_json:
            _compose_traffic_notice("secret-key", facts)

        self.assertIs(request_json.call_args.args[2], TRAFFIC_NOTICE_SCHEMA)
        prompt = request_json.call_args.args[1][0]["text"]
        self.assertIn("Avenida del Mediterráneo", prompt)
        self.assertIn('"Cerrado"', prompt)
        self.assertIn("Never invent a reason", prompt)

    def test_traffic_notice_rejects_missing_fact_commentary(self):
        with patch(
            "telegrambot.gemini._compose_traffic_notice",
            return_value={"body_ru": "Время открытия не указано."},
        ):
            with self.assertRaises(GeminiError):
                asyncio.run(compose_traffic_notice("key", {"mode": "new_present"}))

    def test_agenda_pdf_is_an_accepted_document_format(self):
        with patch(
            "telegrambot.gemini._request_json",
            return_value={"month": "2026-08", "events": []},
        ):
            result = _extract_agenda_events(
                "secret-key", b"%PDF", "application/pdf"
            )

        self.assertEqual(result["month"], "2026-08")



if __name__ == "__main__":
    unittest.main()