import json
import unittest
from email.message import Message
from unittest.mock import patch

from telegrambot.openrouter import OpenRouterError, request_json


class _Response:
    def __init__(self, result=None, content_type="application/json"):
        self.result = result or {"ok": True}
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def geturl(self):
        return "https://openrouter.ai/api/v1/chat/completions"

    def read(self, limit):
        return json.dumps({
            "choices": [{
                "message": {"content": json.dumps(self.result)}
            }]
        }).encode()


class _Opener:
    def __init__(self, response):
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return self.response


class OpenRouterTests(unittest.TestCase):
    def test_request_pins_model_schema_and_provider_capability(self):
        opener = _Opener(_Response())
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        with patch(
            "telegrambot.openrouter.urllib.request.build_opener",
            return_value=opener,
        ):
            result = request_json(
                "openrouter-key",
                [{"text": "Return JSON"}],
                schema,
                100,
            )

        body = json.loads(opener.request.data.decode())
        self.assertEqual(body["model"], "openai/gpt-4.1-mini")
        self.assertTrue(body["provider"]["require_parameters"])
        self.assertTrue(
            body["response_format"]["json_schema"]["strict"]
        )
        self.assertEqual(
            body["response_format"]["json_schema"]["schema"],
            schema,
        )
        self.assertEqual(
            opener.request.headers["Authorization"],
            "Bearer openrouter-key",
        )
        self.assertEqual(result, {"ok": True})

    def test_request_converts_image_and_pdf_parts(self):
        opener = _Opener(_Response())
        with patch(
            "telegrambot.openrouter.urllib.request.build_opener",
            return_value=opener,
        ):
            request_json(
                "key",
                [
                    {"text": "Read media"},
                    {"inlineData": {
                        "mimeType": "image/jpeg",
                        "data": "aW1hZ2U=",
                    }},
                    {"inlineData": {
                        "mimeType": "application/pdf",
                        "data": "JVBERg==",
                    }},
                ],
                None,
                100,
            )

        content = json.loads(opener.request.data.decode())["messages"][0][
            "content"
        ]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(
            content[1]["image_url"]["url"],
            "data:image/jpeg;base64,aW1hZ2U=",
        )
        self.assertEqual(content[2]["type"], "file")
        self.assertEqual(
            content[2]["file"]["file_data"],
            "data:application/pdf;base64,JVBERg==",
        )

    def test_invalid_key_fails_before_network(self):
        with self.assertRaises(OpenRouterError) as raised:
            request_json("", [{"text": "test"}], None, 10)

        self.assertEqual(raised.exception.diagnostic_code, "CONFIG")


if __name__ == "__main__":
    unittest.main()
