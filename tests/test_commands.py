import unittest
from unittest.mock import AsyncMock, patch

from telegrambot.aemet import AemetError
from telegrambot.commands import (
    _produce_preview,
    parse_allowed_user_ids,
    preview_failure_message,
    preview_destination,
)


def update(
    *,
    user_id=123,
    chat_id=123,
    chat_type="private",
    text="/preview",
    sent_at=1_000,
):
    return {
        "update_id": 50,
        "message": {
            "date": sent_at,
            "text": text,
            "from": {"id": user_id},
            "chat": {"id": chat_id, "type": chat_type},
        },
    }


class PreviewCommandTests(unittest.TestCase):
    def test_accepts_fresh_private_command_from_allowlist(self):
        self.assertEqual(
            preview_destination(update(), {123}, 1_030),
            "123",
        )

    def test_accepts_botfather_command_suffix(self):
        self.assertEqual(
            preview_destination(
                update(text="/preview@guardamar_status_bot"),
                {123},
                1_030,
            ),
            "123",
        )

    def test_rejects_group_unauthorized_stale_and_other_commands(self):
        self.assertIsNone(
            preview_destination(
                update(chat_type="group"),
                {123},
                1_030,
            )
        )
        self.assertIsNone(
            preview_destination(update(user_id=999), {123}, 1_030)
        )
        self.assertIsNone(
            preview_destination(update(sent_at=800), {123}, 1_030)
        )
        self.assertIsNone(
            preview_destination(
                update(text="/status"),
                {123},
                1_030,
            )
        )

    def test_parses_strict_allowlist(self):
        self.assertEqual(parse_allowed_user_ids("123, 456"), {123, 456})
        for invalid in ("", "123,", "abc", "0"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_allowed_user_ids(invalid)

    def test_preview_failure_explains_aemet_problem_in_russian(self):
        message = preview_failure_message(
            AemetError("The daily Guardamar forecast is unavailable")
        )

        self.assertEqual(
            message,
            "Не удалось сформировать предпросмотр.\n"
            "Причина: AEMET OpenData не предоставил дневной прогноз "
            "для Гуардамара после 3 попыток.",
        )

    def test_preview_failure_does_not_expose_arbitrary_exception_text(self):
        message = preview_failure_message(
            RuntimeError("secret-token-and-private-url")
        )

        self.assertIn("внутренняя ошибка (RuntimeError)", message)
        self.assertNotIn("secret-token", message)


class PreviewRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_does_not_add_an_outer_aemet_retry(self):
        produce = AsyncMock(side_effect=AemetError("temporary"))

        with self.assertRaises(AemetError):
            await _produce_preview(produce)

        self.assertEqual(produce.await_count, 1)

    async def test_does_not_retry_other_failures(self):
        produce = AsyncMock(side_effect=RuntimeError("broken"))

        with self.assertRaises(RuntimeError):
            await _produce_preview(produce)

        self.assertEqual(produce.await_count, 1)


if __name__ == "__main__":
    unittest.main()
