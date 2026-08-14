import json
import io
import socket
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from telegrambot.telegram import (
    TelegramError,
    _get_updates,
    _post_message,
    _delete_message,
    _edit_message,
    _pin_chat_message,
    _post_photo,
    _edit_photo_media,
    _response_error,
    send_message,
    send_poll,
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
    async def test_photo_upload_is_multipart_and_returns_identifiers(self):
        response = _SuccessfulResponse(
            b'{"ok":true,"result":{"message_id":77,"photo":['
            b'{"file_id":"small"},{"file_id":"largest"}]}}',
            url="https://api.telegram.org/botsecret-token/sendPhoto",
        )
        opener = _Opener(response)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.png"
            path.write_bytes(b"PNG schedule")
            with patch(
                "telegrambot.telegram.urllib.request.build_opener",
                return_value=opener,
            ):
                result = _post_photo(
                    "secret-token", "@destination", path,
                    "Расписание", True,
                )

        self.assertEqual(result, (77, "largest"))
        self.assertTrue(opener.request.full_url.endswith("/sendPhoto"))
        content_type = opener.request.headers["Content-type"]
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="photo"', opener.request.data)
        self.assertIn("Расписание".encode(), opener.request.data)

    async def test_photo_media_edit_uploads_caption_atomically(self):
        response = _SuccessfulResponse(
            b'{"ok":true,"result":{"message_id":42,"photo":['
            b'{"file_id":"updated"}]}}',
            url="https://api.telegram.org/botsecret-token/editMessageMedia",
        )
        opener = _Opener(response)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.png"
            path.write_bytes(b"PNG schedule")
            with patch(
                "telegrambot.telegram.urllib.request.build_opener",
                return_value=opener,
            ):
                file_id = _edit_photo_media(
                    "secret-token", "@destination", 42, path,
                    "Новая подпись",
                )

        self.assertEqual(file_id, "updated")
        self.assertTrue(opener.request.full_url.endswith("/editMessageMedia"))
        self.assertIn(b"attach://photo", opener.request.data)

    async def test_edit_conflicts_are_classified_without_broad_http_400(self):
        unchanged = _response_error(
            {"description": "Bad Request: message is not modified"}, 400
        )
        missing = _response_error(
            {"description": "Bad Request: message to edit not found"}, 400
        )
        missing_pin = _response_error(
            {"description": "Bad Request: message to pin not found"}, 400
        )
        malformed = _response_error(
            {"description": "Bad Request: can't parse entities"}, 400
        )

        self.assertEqual(
            unchanged.diagnostic_code, "MESSAGE-NOT-MODIFIED"
        )
        self.assertEqual(missing.diagnostic_code, "MESSAGE-NOT-FOUND")
        self.assertEqual(missing_pin.diagnostic_code, "MESSAGE-NOT-FOUND")
        self.assertEqual(malformed.diagnostic_code, "HTTP-400")

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

    async def test_send_poll_posts_anonymous_native_poll(self):
        opener = _Opener(_SuccessfulResponse(
            payload=b'{"ok": true, "result": {"message_id": 77}}',
            url="https://api.telegram.org/botsecret-token/sendPoll",
        ))
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            message_id = await send_poll(
                "secret-token",
                "@destination",
                "Что добавить в дайджест?",
                ["Аптеки", "УФ-индекс", "Ничего"],
            )

        self.assertEqual(message_id, 77)
        request = opener.request
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "chat_id": "@destination",
                "question": "Что добавить в дайджест?",
                "options": ["Аптеки", "УФ-индекс", "Ничего"],
                "is_anonymous": True,
            },
        )
        self.assertTrue(request.full_url.endswith("/sendPoll"))

    async def test_send_poll_rejects_invalid_shapes_without_network(self):
        cases = (
            ("", ["a", "b"]),
            ("q" * 301, ["a", "b"]),
            ("вопрос", ["одинокий вариант"]),
            ("вопрос", ["a"] * 11),
            ("вопрос", ["a", "x" * 101]),
        )
        for question, options in cases:
            with self.subTest(question=question[:10], count=len(options)):
                with self.assertRaises(TelegramError) as raised:
                    await send_poll(
                        "secret-token", "@destination", question, options
                    )
                self.assertEqual(
                    raised.exception.diagnostic_code, "CONFIG"
                )

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

    async def test_edit_message_replaces_text_without_link_preview(self):
        opener = _Opener(
            _SuccessfulResponse(
                b'{"ok":true,"result":{"message_id":42}}',
                url=(
                    "https://api.telegram.org/"
                    "botsecret-token/editMessageText"
                ),
            )
        )
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            _edit_message(
                "secret-token", "@destination", 42, "Новый текст"
            )

        request = opener.request
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "chat_id": "@destination",
                "message_id": 42,
                "text": "Новый текст",
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )
        self.assertTrue(request.full_url.endswith("/editMessageText"))

    async def test_pin_message_suppresses_service_notification(self):
        opener = _Opener(
            _SuccessfulResponse(
                b'{"ok":true,"result":true}',
                url=(
                    "https://api.telegram.org/"
                    "botsecret-token/pinChatMessage"
                ),
            )
        )
        with patch(
            "telegrambot.telegram.urllib.request.build_opener",
            return_value=opener,
        ):
            _pin_chat_message("secret-token", "@destination", 42)

        self.assertEqual(
            json.loads(opener.request.data.decode("utf-8")),
            {
                "chat_id": "@destination",
                "message_id": 42,
                "disable_notification": True,
            },
        )
        request = opener.request
        self.assertIsNotNone(request)
        self.assertTrue(request.full_url.endswith("/pinChatMessage"))

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
