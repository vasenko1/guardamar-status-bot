import json
import unittest
from unittest.mock import patch

from telegrambot.groq import (
    MAX_OUTPUT_TOKENS,
    GroqError,
    request_json,
)


class GroqTests(unittest.TestCase):
    def test_request_pins_model_schema_reasoning_and_output_ceiling(self):
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        response = json.dumps({
            "choices": [{
                "message": {"content": json.dumps({"ok": True})}
            }]
        }).encode("utf-8")
        with patch(
            "telegrambot.groq.fetch_bounded",
            return_value=(response, "https://api.groq.com/openai/v1/chat/completions", "application/json"),
        ) as fetch:
            result = request_json(
                "groq-key",
                [{"text": "Return JSON"}],
                schema,
                8_000,
            )

        kwargs = fetch.call_args.kwargs
        body = json.loads(kwargs["data"].decode("utf-8"))
        self.assertEqual(body["model"], "openai/gpt-oss-120b")
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_completion_tokens"], MAX_OUTPUT_TOKENS)
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(
            body["response_format"]["json_schema"]["schema"],
            schema,
        )
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer groq-key",
        )
        self.assertEqual(result, {"ok": True})

    def test_rejects_media_parts_before_network(self):
        with patch("telegrambot.groq.fetch_bounded") as fetch:
            with self.assertRaises(GroqError) as raised:
                request_json(
                    "key",
                    [{"inlineData": {"mimeType": "image/jpeg", "data": "abc"}}],
                    {"type": "object"},
                    100,
                )

        self.assertEqual(raised.exception.diagnostic_code, "INPUT")
        fetch.assert_not_called()

    def test_requires_strict_schema(self):
        with self.assertRaises(GroqError) as raised:
            request_json("key", [{"text": "test"}], None, 100)

        self.assertEqual(raised.exception.diagnostic_code, "INPUT")

    def test_invalid_key_fails_before_network(self):
        with self.assertRaises(GroqError) as raised:
            request_json("", [{"text": "test"}], {"type": "object"}, 10)

        self.assertEqual(raised.exception.diagnostic_code, "CONFIG")


if __name__ == "__main__":
    unittest.main()
