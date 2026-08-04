import json
import io
import socket
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

from telegrambot.telegram import (
    TelegramError,
    _get_updates,
    _post_message,
    _delete_message,
    send_message,
)


class _SuccessfulResponse:
    status = 200

    def __init__(
        self,
        payload=b'{"ok": true, "result": {"message_id": 1}}',
        content_type="application/json",
        url="https://api.telegram.org/botsecret-token/sendMessage",
    ):
        self.payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        return self.payload[:limit]

    def geturl(self):
        return self.url


class _Opener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        if self.error is not None:
            raise self.error
        return self.response


class TelegramDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_updates_requests_only_messages(self):
        response = _SuccessfulResponse(
            b'{"ok":true,"result":[{"update_id":10}]}',
            url="https://api.telegram.org/botsecret-token/getUpdates",
        )
        opener = _Opener(response)
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            updates = _get_updates("secret-token", 8, 30)

        request = opener.request
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "timeout": 30,
                "allowed_updates": ["message"],
                "offset": 8,
            },
        )
        self.assertEqual(updates, [{"update_id": 10}])

    async def test_get_updates_converts_socket_timeout(self):
        opener = _Opener(error=socket.timeout())
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(TelegramError) as raised:
                _get_updates("secret-token", None, 30)
        self.assertEqual(raised.exception.diagnostic_code, "TIMEOUT")

    async def test_send_message_posts_utf8_json_to_configured_destination(self):
        opener = _Opener(_SuccessfulResponse())
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            _post_message(
                "secret-token",
                "@destination",
                "Buenos días",
                True,
            )

        request = opener.request
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "chat_id": "@destination",
                "text": "Buenos días",
                "disable_notification": True,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )
        self.assertTrue(request.full_url.endswith("/sendMessage"))

    async def test_delete_message_uses_known_message_identifier(self):
        opener = _Opener(
            _SuccessfulResponse(
                b'{"ok":true,"result":true}',
                url=(
                    "https://api.telegram.org/"
                    "botsecret-token/deleteMessage"
                ),
            )
        )
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            _delete_message("secret-token", "@destination", 42)

        request = opener.request
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"chat_id": "@destination", "message_id": 42},
        )
        self.assertTrue(request.full_url.endswith("/deleteMessage"))

    async def test_reply_uses_telegram_reply_parameters(self):
        opener = _Opener(_SuccessfulResponse())
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            _post_message(
                "secret-token", "@destination", "details", False, 42
            )
        body = json.loads(opener.request.data.decode("utf-8"))
        self.assertEqual(
            body["reply_parameters"],
            {"message_id": 42, "allow_sending_without_reply": False},
        )

    async def test_rejects_non_json_success_response(self):
        opener = _Opener(
            _SuccessfulResponse(content_type="text/html")
        )
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(TelegramError) as raised:
                _post_message("secret-token", "@destination", "digest")

        self.assertEqual(
            raised.exception.diagnostic_code,
            "CONTENT-TYPE",
        )

    async def test_rejects_response_from_another_host(self):
        opener = _Opener(
            _SuccessfulResponse(url="https://example.com/response")
        )
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(TelegramError) as raised:
                _post_message("secret-token", "@destination", "digest")

        self.assertEqual(raised.exception.diagnostic_code, "REDIRECT")

    async def test_http_status_controls_retry_classification(self):
        error = urllib.error.HTTPError(
            "https://api.telegram.org/botsecret-token/sendMessage",
            503,
            "Unavailable",
            {},
            io.BytesIO(b'{"ok":false,"error_code":400}'),
        )
        opener = _Opener(error=error)
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(TelegramError) as raised:
                _post_message("secret-token", "@destination", "digest")

        self.assertEqual(raised.exception.diagnostic_code, "HTTP-503")
        self.assertTrue(raised.exception.retryable)

    async def test_http_error_body_read_failure_is_diagnostic(self):
        class BrokenBody:
            def read(self, limit):
                raise OSError("connection reset")

            def close(self):
                pass

        error = urllib.error.HTTPError(
            "https://api.telegram.org/botsecret-token/sendMessage",
            503,
            "Unavailable",
            {},
            BrokenBody(),
        )
        opener = _Opener(error=error)
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(TelegramError) as raised:
                _post_message("secret-token", "@destination", "digest")

        self.assertEqual(raised.exception.diagnostic_code, "NETWORK")
        self.assertTrue(raised.exception.retryable)

    async def test_successful_send_has_no_retry(self):
        delays = []

        async def sleep(delay):
            delays.append(delay)

        with patch("telegrambot.telegram._post_message") as post:
            await send_message(
                "secret-token",
                "@destination",
                "digest",
                sleep=sleep,
            )

        post.assert_called_once_with(
            "secret-token",
            "@destination",
            "digest",
            False,
        )
        self.assertEqual(delays, [])

    async def test_transient_failures_have_bounded_retries(self):
        delays = []

        async def sleep(delay):
            delays.append(delay)

        transient = TelegramError(
            "temporary failure", retryable=True
        )
        with patch(
            "telegrambot.telegram._post_message",
            side_effect=(transient, transient, None),
        ) as post:
            await send_message(
                "secret-token",
                "@destination",
                "digest",
                sleep=sleep,
            )

        self.assertEqual(post.call_count, 3)
        self.assertEqual(delays, [1, 2])

    async def test_permanent_failure_is_not_retried(self):
        permanent = TelegramError(
            "chat not found", retryable=False
        )
        with patch(
            "telegrambot.telegram._post_message",
            side_effect=permanent,
        ) as post:
            with self.assertRaises(TelegramError):
                await send_message(
                    "secret-token",
                    "@destination",
                    "digest",
                )

        self.assertEqual(post.call_count, 1)

    async def test_server_retry_after_is_capped(self):
        delays = []

        async def sleep(delay):
            delays.append(delay)

        rate_limited = TelegramError(
            "rate limited", retryable=True, retry_after=60
        )
        with patch(
            "telegrambot.telegram._post_message",
            side_effect=(rate_limited, None),
        ):
            await send_message(
                "secret-token",
                "@destination",
                "digest",
                sleep=sleep,
            )

        self.assertEqual(delays, [10])

if __name__ == "__main__":
    unittest.main()
