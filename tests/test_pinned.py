import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from telegrambot.branding import FOOTER
from telegrambot.pinned import (
    CAMERAS,
    LEAF_MESSAGES,
    PinnedGuideState,
    build_root,
    build_transport_index,
    preview_messages,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.state import StateError
from telegrambot.telegram import TelegramError


class PinnedContentTests(unittest.TestCase):
    def test_every_message_is_telegram_safe_and_has_footer(self):
        for message in preview_messages():
            with self.subTest(message=message[:40]):
                self.assertLessEqual(len(message), 4096)
                self.assertEqual(message.count(FOOTER), 1)
                self.assertNotIn("—", message)
                self.assertNotIn("Проверено:", message)
                self.assertNotIn("Официальное расписание", message)

    def test_preview_contains_all_leaves_camera_index_and_root(self):
        messages = preview_messages()
        self.assertEqual(len(messages), len(LEAF_MESSAGES) + 3)
        self.assertIn(CAMERAS, messages)
        self.assertIn("Транспорт из Гуардамара", messages[-2])
        self.assertIn("Полезное о Гуардамаре", messages[-1])

    def test_internal_links_support_public_and_private_supergroups(self):
        self.assertEqual(
            telegram_message_link("@guardamar", 42),
            "https://t.me/guardamar/42",
        )
        self.assertEqual(
            telegram_message_link("-100123456", 42),
            "https://t.me/c/123456/42",
        )
        for invalid in ("123", "-123", ""):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    telegram_message_link(invalid, 42)

    def test_index_and_root_use_supplied_links(self):
        links = {
            key: f"https://t.me/c/1/{number}"
            for number, key in enumerate(LEAF_MESSAGES, start=1)
        }
        index = build_transport_index(links)
        root = build_root(
            "https://t.me/c/1/20", "https://t.me/c/1/21"
        )
        for link in links.values():
            self.assertIn(link, index)
        self.assertIn("https://t.me/c/1/20", root)
        self.assertIn("https://t.me/c/1/21", root)


class PinnedStateTests(unittest.TestCase):
    def test_round_trip_and_wrong_chat_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write("-100123", {"root": 3})
            self.assertEqual(state.read("-100123"), {"root": 3})
            with self.assertRaises(StateError):
                state.read("-100456")

    def test_rejects_corrupt_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pinned.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(StateError):
                PinnedGuideState(path).read("-100123")


class PinnedPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_group_id_is_rejected_before_any_send(self):
        with tempfile.TemporaryDirectory() as directory:
            send = AsyncMock()
            with self.assertRaises(ValueError):
                await publish_pinned_guide(
                    "-123",
                    PinnedGuideState(Path(directory) / "pinned.json"),
                    send,
                    AsyncMock(),
                    AsyncMock(),
                )
            send.assert_not_awaited()

    async def test_first_run_sends_links_and_pins_root(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            sent = []

            async def send(message):
                sent.append(message)
                return len(sent)

            edit = AsyncMock()
            pin = AsyncMock()
            result = await publish_pinned_guide(
                "-100123", state, send, edit, pin
            )

            self.assertEqual(len(sent), len(LEAF_MESSAGES) + 3)
            self.assertEqual(result["root"], len(sent))
            pin.assert_awaited_once_with(result["root"])
            edit.assert_not_awaited()
            self.assertIn(
                f"https://t.me/c/123/{result['line_1']}",
                sent[-2],
            )
            self.assertIn(
                f"https://t.me/c/123/{result['transport']}",
                sent[-1],
            )

    async def test_second_run_edits_without_duplicate_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            state.write(
                "-100123",
                {key: number for number, key in enumerate(keys, start=1)},
            )
            send = AsyncMock()
            edit = AsyncMock()
            pin = AsyncMock()

            result = await publish_pinned_guide(
                "-100123", state, send, edit, pin
            )

            send.assert_not_awaited()
            self.assertEqual(edit.await_count, len(keys))
            pin.assert_awaited_once_with(result["root"])

    async def test_missing_message_is_recreated_and_links_follow_it(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            state.write(
                "-100123",
                {key: number for number, key in enumerate(keys, start=1)},
            )

            async def edit(message_id, message):
                if message_id == 1:
                    raise TelegramError(
                        "missing", retryable=False, status=400
                    )

            send = AsyncMock(return_value=99)
            pin = AsyncMock()
            result = await publish_pinned_guide(
                "-100123", state, send, edit, pin
            )

            send.assert_awaited_once()
            self.assertEqual(result["line_1"], 99)
            saved = json.loads(state.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["messages"]["line_1"], 99)


if __name__ == "__main__":
    unittest.main()
