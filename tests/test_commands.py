import unittest
from unittest.mock import AsyncMock, patch

from telegrambot.aemet import AemetError
from telegrambot.commands import (
    _produce_preview,
    parse_allowed_user_ids,
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


class PreviewRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_aemet_once(self):
        produce = AsyncMock(
            side_effect=[AemetError("temporary"), "digest"]
        )
        with patch(
            "telegrambot.commands.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            result = await _produce_preview(produce)

        self.assertEqual(result, "digest")
        self.assertEqual(produce.await_count, 2)
        sleep.assert_awaited_once()

    async def test_does_not_retry_other_failures(self):
        produce = AsyncMock(side_effect=RuntimeError("broken"))

        with self.assertRaises(RuntimeError):
            await _produce_preview(produce)

        self.assertEqual(produce.await_count, 1)


if __name__ == "__main__":
    unittest.main()
