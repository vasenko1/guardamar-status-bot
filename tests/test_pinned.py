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
    build_cameras,
    build_leaf_message,
    build_root,
    build_transport_index,
    preview_messages,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.state import StateError
from telegrambot.telegram import TelegramError


class PinnedContentTests(unittest.TestCase):
    def test_only_final_guide_messages_have_footer(self):
        messages = preview_messages()
        for message in messages[:-2]:
            with self.subTest(message=message[:40]):
                self.assertLessEqual(len(message), 4096)
                self.assertEqual(message.count(FOOTER), 1)
                self.assertNotIn("—", message)
                self.assertNotIn("Проверено:", message)
                self.assertNotIn("Официальное расписание", message)
        for message in messages[-2:]:
            with self.subTest(message=message[:40]):
                self.assertLessEqual(len(message), 4096)
                self.assertNotIn(FOOTER, message)

    def test_preview_contains_all_leaves_camera_index_and_root(self):
        messages = preview_messages()
        self.assertEqual(len(messages), len(LEAF_MESSAGES) + 3)
        self.assertIn(build_cameras(), messages)
        self.assertIn("Транспорт из Гуардамара", messages[-2])
        self.assertIn("Полезное о Гуардамаре", messages[-1])

    def test_root_is_a_compact_static_navigator_without_footer(self):
        root = build_root(
            "https://t.me/c/1/20", "https://t.me/c/1/21"
        )

        self.assertEqual(
            root,
            '📌 <b>Полезное о Гуардамаре</b>\n\n'
            '📹 <a href="https://t.me/c/1/20"><b>Онлайн-камеры</b></a>\n\n'
            '🚌 <a href="https://t.me/c/1/21"><b>Транспорт в Гуардамаре</b></a>',
        )
        self.assertNotIn(FOOTER, root)

    def test_transport_navigator_has_navigation_but_no_footer(self):
        index = build_transport_index(
            root_link="https://t.me/c/1/22"
        )

        self.assertIn("К главному закрепу", index)
        self.assertIn("https://t.me/c/1/22", index)
        self.assertNotIn(FOOTER, index)

    def test_hospital_message_has_year_round_timetable_and_live_source(self):
        hospital = build_leaf_message("hospital")
        self.assertIn("Линия 6", hospital)
        self.assertIn("07:30 · 09:00 · 11:00", hospital)
        self.assertIn("08:00 · 09:30 · 13:30 · 17:00", hospital)
        self.assertIn("Суббота, воскресенье и праздники", hospital)
        self.assertIn("www.gva.es", hospital)
        self.assertNotIn("regular.autobusing.com", hospital)

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
        index = build_transport_index(links, "https://t.me/c/1/22")
        root = build_root(
            "https://t.me/c/1/20", "https://t.me/c/1/21"
        )
        for link in links.values():
            self.assertIn(link, index)
        self.assertIn("https://t.me/c/1/20", root)
        self.assertIn("https://t.me/c/1/21", root)
        self.assertIn("https://t.me/c/1/22", index)

    def test_detail_and_camera_messages_have_visible_return_navigation(self):
        leaf = build_leaf_message("airport", "https://t.me/c/1/20")
        cameras = build_cameras("https://t.me/c/1/21")

        self.assertIn("К списку транспорта", leaf)
        self.assertIn("https://t.me/c/1/20", leaf)
        self.assertIn("К главному закрепу", cameras)
        self.assertIn("https://t.me/c/1/21", cameras)


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
    async def test_explicitly_managed_leaf_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            messages = {
                key: number for number, key in enumerate(keys, start=1)
            }
            state.write("-100123", messages)
            edit = AsyncMock()

            await publish_pinned_guide(
                "-100123",
                state,
                AsyncMock(),
                edit,
                AsyncMock(),
                skip_keys=("airport",),
            )

            edited_ids = {call.args[0] for call in edit.await_args_list}
            self.assertNotIn(messages["airport"], edited_ids)

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
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, pin
            )

            self.assertEqual(len(sent), len(LEAF_MESSAGES) + 3)
            self.assertEqual(result["root"], len(sent))
            pin.assert_awaited_once_with(result["root"])
            self.assertEqual(edit.await_count, len(LEAF_MESSAGES) + 3)
            self.assertIn(
                f"https://t.me/c/123/{result['line_1']}",
                edit.call_args_list[-2].args[1],
            )
            self.assertIn(
                f"https://t.me/c/123/{result['transport']}",
                edit.call_args_list[0].args[1],
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

    async def test_unchanged_telegram_messages_do_not_create_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            state.write(
                "-100123",
                {key: number for number, key in enumerate(keys, start=1)},
            )
            unchanged = TelegramError(
                "unchanged",
                retryable=False,
                code="MESSAGE-NOT-MODIFIED",
                status=400,
            )
            send = AsyncMock()
            pin = AsyncMock()

            result = await publish_pinned_guide(
                "-100123",
                state,
                send,
                AsyncMock(side_effect=unchanged),
                pin,
            )

            send.assert_not_awaited()
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
                        "missing",
                        retryable=False,
                        code="MESSAGE-NOT-FOUND",
                        status=400,
                    )

            send = AsyncMock(return_value=99)
            pin = AsyncMock()
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, pin
            )

            send.assert_awaited_once()
            self.assertEqual(result["line_1"], 99)
            saved = json.loads(state.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["messages"]["line_1"], 99)
            transport_edits = [
                call.args[1]
                for call in edit_mock.await_args_list
                if call.args[0] == result["transport"]
            ]
            self.assertIn(
                "https://t.me/c/123/99", transport_edits[-1]
            )

    async def test_deleted_transport_updates_every_backlink(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            state.write(
                "-100123",
                {key: number for number, key in enumerate(keys, start=1)},
            )
            old_transport = keys.index("transport") + 1

            async def edit(message_id, message):
                if message_id == old_transport:
                    raise TelegramError(
                        "missing",
                        retryable=False,
                        code="MESSAGE-NOT-FOUND",
                        status=400,
                    )

            send = AsyncMock(return_value=99)
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, AsyncMock()
            )

            self.assertEqual(result["transport"], 99)
            leaf_edits = [
                call.args[1]
                for call in edit_mock.await_args_list
                if call.args[0] == result["line_1"]
            ]
            self.assertIn("https://t.me/c/123/99", leaf_edits[-1])
            root_edits = [
                call.args[1]
                for call in edit_mock.await_args_list
                if call.args[0] == result["root"]
            ]
            self.assertIn("https://t.me/c/123/99", root_edits[-1])

    async def test_deleted_camera_and_root_are_recreated_together(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            stored = {key: number for number, key in enumerate(keys, start=1)}
            state.write("-100123", stored)
            deleted = {stored["cameras"], stored["root"]}
            next_id = 90

            async def edit(message_id, message):
                if message_id in deleted:
                    raise TelegramError(
                        "missing",
                        retryable=False,
                        code="MESSAGE-NOT-FOUND",
                        status=400,
                    )

            async def send(message):
                nonlocal next_id
                next_id += 1
                return next_id

            pin = AsyncMock()
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, pin
            )

            self.assertEqual(result["cameras"], 91)
            self.assertEqual(result["root"], 92)
            pin.assert_awaited_once_with(92)
            camera_edits = [
                call.args[1]
                for call in edit_mock.await_args_list
                if call.args[0] == 91
            ]
            self.assertIn("https://t.me/c/123/92", camera_edits[-1])
            root_edits = [
                call.args[1]
                for call in edit_mock.await_args_list
                if call.args[0] == 92
            ]
            self.assertIn("https://t.me/c/123/91", root_edits[-1])

    async def test_all_deleted_messages_are_recreated_as_one_valid_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            stored = {key: number for number, key in enumerate(keys, start=1)}
            state.write("-100123", stored)
            next_id = 100

            async def edit(message_id, message):
                if message_id in stored.values():
                    raise TelegramError(
                        "missing",
                        retryable=False,
                        code="MESSAGE-NOT-FOUND",
                        status=400,
                    )

            async def send(message):
                nonlocal next_id
                next_id += 1
                return next_id

            edit_mock = AsyncMock(side_effect=edit)
            pin = AsyncMock()
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, pin
            )

            self.assertEqual(len(set(result.values())), len(keys))
            self.assertTrue(set(result.values()).isdisjoint(stored.values()))
            pin.assert_awaited_once_with(result["root"])
            final_text = {
                message_id: [
                    call.args[1]
                    for call in edit_mock.await_args_list
                    if call.args[0] == message_id
                ][-1]
                for message_id in result.values()
            }
            transport_link = telegram_message_link(
                "-100123", result["transport"]
            )
            root_link = telegram_message_link("-100123", result["root"])
            for key in LEAF_MESSAGES:
                self.assertIn(transport_link, final_text[result[key]])
            self.assertIn(root_link, final_text[result["cameras"]])
            self.assertIn(root_link, final_text[result["transport"]])
            for key in LEAF_MESSAGES:
                self.assertIn(
                    telegram_message_link("-100123", result[key]),
                    final_text[result["transport"]],
                )

    async def test_root_deleted_before_pin_is_recreated_and_relinked(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            stored = {key: number for number, key in enumerate(keys, start=1)}
            state.write("-100123", stored)
            pin = AsyncMock(
                side_effect=(
                    TelegramError(
                        "missing",
                        retryable=False,
                        code="MESSAGE-NOT-FOUND",
                        status=400,
                    ),
                    None,
                )
            )
            send = AsyncMock(return_value=99)

            result = await publish_pinned_guide(
                "-100123", state, send, AsyncMock(), pin
            )

            self.assertEqual(result["root"], 99)
            self.assertEqual(pin.await_count, 2)
            self.assertEqual(pin.await_args_list[-1].args, (99,))

    async def test_unrelated_bad_request_never_creates_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
            state.write(
                "-100123",
                {key: number for number, key in enumerate(keys, start=1)},
            )
            error = TelegramError(
                "bad html", retryable=False, code="HTTP-400", status=400
            )
            send = AsyncMock()

            with self.assertRaises(TelegramError):
                await publish_pinned_guide(
                    "-100123",
                    state,
                    send,
                    AsyncMock(side_effect=error),
                    AsyncMock(),
                )

            send.assert_not_awaited()

    async def test_ambiguous_new_send_is_marked_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            timeout = TelegramError(
                "timeout", retryable=True, code="TIMEOUT"
            )
            send = AsyncMock(side_effect=timeout)

            with self.assertRaises(TelegramError):
                await publish_pinned_guide(
                    "-100123", state, send, AsyncMock(), AsyncMock()
                )

            payload = state.read_payload("-100123")
            self.assertEqual(payload["uncertain_messages"], ["line_1"])
            with self.assertRaises(StateError):
                await publish_pinned_guide(
                    "-100123", state, send, AsyncMock(), AsyncMock()
                )
            self.assertEqual(send.await_count, 1)

    async def test_explicit_rate_limit_does_not_mark_send_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            rate_limited = TelegramError(
                "rate limited", retryable=True, code="HTTP-429", status=429
            )

            with self.assertRaises(TelegramError):
                await publish_pinned_guide(
                    "-100123",
                    state,
                    AsyncMock(side_effect=rate_limited),
                    AsyncMock(),
                    AsyncMock(),
                )

            payload = state.read_payload("-100123")
            self.assertEqual(payload["uncertain_messages"], [])


if __name__ == "__main__":
    unittest.main()
