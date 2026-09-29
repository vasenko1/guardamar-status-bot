import unittest
from unittest.mock import patch

from telegrambot.telegram import (
    TelegramError,
    _post_rich_message,
    _response_error,
    send_rich_message,
)


class ProductAwardRichTelegramTests(unittest.IsolatedAsyncioTestCase):
    def test_post_rich_message_uses_expected_payload(self):
        with patch(
            "telegrambot.telegram._call_api",
            return_value={"ok": True, "result": {"message_id": 91}},
        ) as call:
            message_id = _post_rich_message(
                "dummy",
                "chat",
                (
                    '<img src="https://cdn.example/product.jpg"/>'
                    '<p>🏆 <b>Заголовок</b></p>'
                    '<blockquote expandable>Методика</blockquote>'
                ),
                True,
            )

        self.assertEqual(message_id, 91)
        method = call.call_args.args[1]
        body = call.call_args.args[2]
        self.assertEqual(method, "sendRichMessage")
        self.assertEqual(body["chat_id"], "chat")
        self.assertTrue(body["disable_notification"])
        self.assertIn("<p>🏆", body["rich_message"]["html"])
        self.assertTrue(body["rich_message"]["skip_entity_detection"])

    def test_remote_media_fetch_error_has_specific_diagnostic(self):
        error = _response_error(
            {"description": "Bad Request: failed to get HTTP URL content"},
            400,
        )

        self.assertEqual(error.diagnostic_code, "REMOTE-MEDIA")
        self.assertFalse(error.retryable)
        self.assertEqual(error.server_status, 400)

    async def test_send_rich_message_does_not_retry_ambiguous_failure(self):
        transient = TelegramError(
            "timeout",
            retryable=True,
            code="TIMEOUT",
        )
        with patch(
            "telegrambot.telegram._post_rich_message",
            side_effect=transient,
        ) as post:
            with self.assertRaises(TelegramError):
                await send_rich_message(
                    "dummy",
                    "chat",
                    "<p>message</p>",
                    retry_only_rate_limits=True,
                )

        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
