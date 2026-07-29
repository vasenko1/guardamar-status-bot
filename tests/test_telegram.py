import json
import socket
import unittest
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        return b'{"ok": true, "result": {"message_id": 1}}'


class TelegramDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_updates_requests_only_messages(self):
        response = _SuccessfulResponse()
        response.read = lambda limit: (
            b'{"ok":true,"result":[{"update_id":10}]}'
        )
        with patch(
            "telegrambot.telegram.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            updates = _get_updates("secret-token", 8, 30)

        request = urlopen.call_args.args[0]
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
        with patch(
            "telegrambot.telegram.urllib.request.urlopen",
            side_effect=socket.timeout(),
        ):
            with self.assertRaises(TelegramError):
                _get_updates("secret-token", None, 30)

    async def test_send_message_posts_utf8_json_to_configured_destination(self):
        with patch(
            "telegrambot.telegram.urllib.request.urlopen",
            return_value=_SuccessfulResponse(),
        ) as urlopen:
            _post_message(
                "secret-token",
                "@destination",
                "Buenos días",
                True,
            )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "chat_id": "@destination",
                "text": "Buenos días",
                "disable_notification": True,
            },
        )
        self.assertTrue(request.full_url.endswith("/sendMessage"))

    async def test_delete_message_uses_known_message_identifier(self):
        with patch(
            "telegrambot.telegram.urllib.request.urlopen",
            return_value=_SuccessfulResponse(),
        ) as urlopen:
            _delete_message("secret-token", "@destination", 42)

        request = urlopen.call_args.args[0]
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"chat_id": "@destination", "message_id": 42},
        )
        self.assertTrue(request.full_url.endswith("/deleteMessage"))

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
