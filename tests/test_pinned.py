import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from telegrambot.branding import FOOTER
from telegrambot.pinned import (
    AQUALIDER_BOOKING_URL,
    CAMERAS,
    GUIDE_MESSAGE_KEYS,
    LEAF_MESSAGES,
    PINNED_MESSAGE_KEYS,
    PinnedGuideState,
    build_activities,
    build_cameras,
    build_leaf_message,
    build_places,
    build_polideportivo,
    build_pool_indoor,
    build_pool_outdoor,
    build_root,
    build_swimming,
    build_transport_index,
    build_wifi,
    preview_messages,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.state import StateError
from telegrambot.telegram import TelegramError


class PinnedContentTests(unittest.TestCase):
    def test_public_detail_messages_have_one_footer(self):
        messages = [
            *(build_leaf_message(key) for key in LEAF_MESSAGES),
            build_cameras(),
            build_places(),
            build_polideportivo(),
            build_pool_indoor(),
            build_pool_outdoor(),
            build_wifi(),
            build_activities(),
            build_swimming(),
        ]
        for message in messages:
            with self.subTest(message=message[:40]):
                self.assertLessEqual(len(message), 4096)
                self.assertEqual(message.count(FOOTER), 1)
                self.assertNotIn("Проверено:", message)
                self.assertNotIn("Официальное расписание", message)

    def test_navigators_without_brand_footer_stay_compact(self):
        transport = build_transport_index()
        root = build_root()
        self.assertNotIn(FOOTER, transport)
        self.assertNotIn(FOOTER, root)
        self.assertLessEqual(len(transport), 4096)
        self.assertLessEqual(len(root), 4096)

    def test_preview_contains_complete_guide(self):
        messages = preview_messages()
        self.assertEqual(len(messages), len(LEAF_MESSAGES) + len(GUIDE_MESSAGE_KEYS) + 3)
        self.assertIn(build_cameras(), messages)
        self.assertTrue(any("Транспорт из Гуардамара" in item for item in messages))
        self.assertTrue(any("Polideportivo Municipal" in item for item in messages))
        self.assertTrue(any("Крытый бассейн Manel Estiarte" in item for item in messages))
        self.assertTrue(any("Открытый муниципальный бассейн" in item for item in messages))
        self.assertTrue(any("Занятия и секции" in item for item in messages))
        self.assertTrue(any("Плавание" in item for item in messages))
        self.assertIn("Полезное о Гуардамаре", messages[-1])

    def test_root_is_compact_five_item_navigator(self):
        root = build_root(
            "https://t.me/c/1/20",
            "https://t.me/c/1/21",
            "https://t.me/c/1/22",
            "https://t.me/c/1/23",
            wifi_link="https://t.me/c/1/24",
        )
        self.assertEqual(
            root,
            '📌 <b>Полезное о Гуардамаре</b>\n\n'
            '📹 <a href="https://t.me/c/1/20"><b>Онлайн-камеры</b></a>\n\n'
            '🚌 <a href="https://t.me/c/1/21"><b>Транспорт в Гуардамаре</b></a>\n\n'
            '📍 <a href="https://t.me/c/1/22"><b>Места</b></a>\n\n'
            '📶 <a href="https://t.me/c/1/24"><b>Бесплатный Wi-Fi</b></a>\n\n'
            '🎓 <a href="https://t.me/c/1/23"><b>Занятия и секции</b></a>',
        )
        self.assertNotIn(FOOTER, root)

    def test_places_and_activities_use_direct_links(self):
        places = build_places("https://t.me/c/1/30")
        complex_card = build_polideportivo(
            "https://t.me/c/1/31", "https://t.me/c/1/32"
        )
        indoor = build_pool_indoor("https://t.me/c/1/33")
        outdoor = build_pool_outdoor("https://t.me/c/1/33")
        activities = build_activities("https://t.me/c/1/33")
        swimming = build_swimming(
            "https://t.me/c/1/31", "https://t.me/c/1/32"
        )

        self.assertIn("https://t.me/c/1/30", places)
        self.assertIn("https://t.me/c/1/31", complex_card)
        self.assertIn("https://t.me/c/1/32", complex_card)
        self.assertIn("https://t.me/c/1/33", indoor)
        self.assertIn("https://t.me/c/1/33", outdoor)
        self.assertIn("https://t.me/c/1/33", activities)
        self.assertIn("https://t.me/c/1/31", swimming)
        self.assertIn("https://t.me/c/1/32", swimming)
        self.assertIn(AQUALIDER_BOOKING_URL, swimming)
        self.assertNotIn("будут добавляться", complex_card)
        self.assertNotIn("Aqualider", swimming)

    def test_polideportivo_card_links_verified_maps(self):
        complex_card = build_polideportivo()
        self.assertIn("https://maps.app.goo.gl/KSZV3aVX75UxATQ68", complex_card)
        self.assertIn("https://maps.app.goo.gl/Jp7EA9RqrZQPcVq17", complex_card)
        self.assertIn("https://maps.app.goo.gl/tzMkY17nvVPA4CWx6", complex_card)

    def test_pool_cards_keep_distinct_seasons_and_verified_contacts(self):
        indoor = build_pool_indoor()
        outdoor = build_pool_outdoor()
        self.assertIn("16 сентября по 15 июня", indoor)
        self.assertIn("Piscina Climatizada Manel Estiarte", indoor)
        self.assertIn("https://maps.app.goo.gl/p9GqBDQEbnyQQNaAA", indoor)
        self.assertIn("Av. de Cervantes, s/n", indoor)
        self.assertIn("<code>966726593</code>", indoor)
        self.assertNotIn("966 72 65 93", indoor)
        self.assertIn("16 июня по 15 сентября", outdoor)
        self.assertIn("Piscinas Descubiertas Municipales", outdoor)
        self.assertIn("https://maps.app.goo.gl/dnCq36EzS8DTcq4T6", outdoor)
        self.assertIn("Av. Europa, 3", outdoor)
        self.assertIn("<code>966726335</code>", outdoor)
        self.assertNotIn("966 72 63 35", outdoor)
        self.assertNotIn("965 35 76 93", outdoor)

    def test_transport_navigator_has_navigation_but_no_footer(self):
        index = build_transport_index(root_link="https://t.me/c/1/22")
        self.assertIn("Полезное о Гуардамаре", index)
        self.assertIn("https://t.me/c/1/22", index)
        self.assertNotIn(FOOTER, index)

    def test_transport_navigator_is_a_compact_destination_menu(self):
        links = {
            key: f"https://t.me/c/1/{number}"
            for number, key in enumerate(LEAF_MESSAGES, start=1)
        }
        index = build_transport_index(links)
        self.assertNotIn("Только прямые маршруты", index)
        self.assertIn("<b>Городские маршруты:</b>", index)
        self.assertNotIn("Puerto Deportivo ↔", index)
        self.assertIn("Аэропорт Alicante-Elche", index)
        self.assertIn("Больница в Торревьехе", index)
        for destination in (
            "Аликанте",
            "Эльче",
            "Ла-Мата",
            "Торревьеха",
            "ТЦ Zenia Boulevard",
            "Рохалес",
            "Ориуэла",
            "Университет Аликанте",
        ):
            with self.subTest(destination=destination):
                self.assertIn(destination, index)
        self.assertEqual(index.count(links["south"]), 3)
        self.assertEqual(index.count(links["inland"]), 2)

    def test_south_route_has_stable_prefilled_zenia_search(self):
        south = build_leaf_message("south")
        self.assertIn("Посмотреть рейсы до Zenia Boulevard", south)
        self.assertIn("venta%5Borigen_nombre%5D=GUARDAMAR", south)
        self.assertIn(
            "venta%5Bdestino_nombre%5D=C.C.%20BOULEVAR%20ZENIA",
            south,
        )
        self.assertNotIn("venta%5Bfecha_ida%5D", south)

    def test_hospital_message_has_year_round_timetable_and_live_source(self):
        hospital = build_leaf_message("hospital")
        self.assertIn("линии 6 Avanza", hospital)
        self.assertIn("07:30 · 09:00 · 11:00", hospital)
        self.assertIn("08:00 · 09:30 · 13:30 · 17:00", hospital)
        self.assertIn("По выходным и праздникам", hospital)
        self.assertIn("www.gva.es", hospital)
        self.assertNotIn("regular.autobusing.com", hospital)

    def test_intercity_leaves_use_one_human_passenger_first_style(self):
        route_keys = (
            "airport", "hospital", "alicante", "elche", "south",
            "inland", "university",
        )
        for key in route_keys:
            with self.subTest(key=key):
                message = build_leaf_message(key)
                self.assertNotIn("Проверьте расписание", message)
                self.assertNotIn("Costa Azul / Avanza", message)
                self.assertNotIn("Прямой автобус ·", message)
                self.assertIn("📍 <b>", message)
        for key in ("airport", "alicante", "elche", "south", "inland"):
            with self.subTest(schedule_key=key):
                self.assertIn(
                    "Найти расписание на нужную дату",
                    build_leaf_message(key),
                )
        self.assertIn(
            "Доехать можно без пересадок на автобусе Avanza",
            build_leaf_message("alicante"),
        )
        self.assertIn(
            "остановка на проспекте Vicente Quiles в Elche",
            build_leaf_message("elche"),
        )
        self.assertIn(
            "Для поездки нужно быть членом ADEUGT",
            build_leaf_message("university"),
        )

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
            "https://t.me/c/1/20",
            "https://t.me/c/1/21",
            "https://t.me/c/1/23",
            "https://t.me/c/1/24",
        )
        for link in links.values():
            self.assertIn(link, index)
        for link in (
            "https://t.me/c/1/20",
            "https://t.me/c/1/21",
            "https://t.me/c/1/23",
            "https://t.me/c/1/24",
        ):
            self.assertIn(link, root)
        self.assertIn("https://t.me/c/1/22", index)

    def test_detail_and_camera_messages_have_visible_return_navigation(self):
        leaf = build_leaf_message("airport", "https://t.me/c/1/20")
        cameras = build_cameras("https://t.me/c/1/21")
        self.assertIn("К списку транспорта", leaf)
        self.assertIn("https://t.me/c/1/20", leaf)
        self.assertIn("Полезное о Гуардамаре", cameras)
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
    @staticmethod
    def _messages():
        return {
            key: number
            for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
        }

    async def test_explicitly_managed_leaf_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = self._messages()
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

    async def test_first_run_sends_complete_linked_graph_and_pins_root(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            sent = []

            async def send(message):
                sent.append(message)
                return len(sent)

            edit_mock = AsyncMock()
            pin = AsyncMock()
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, pin
            )

            self.assertEqual(len(sent), len(PINNED_MESSAGE_KEYS))
            self.assertEqual(set(result), set(PINNED_MESSAGE_KEYS))
            self.assertEqual(result["root"], len(sent))
            pin.assert_awaited_once_with(result["root"])
            self.assertEqual(edit_mock.await_count, len(PINNED_MESSAGE_KEYS))

            final = {
                call.args[0]: call.args[1]
                for call in edit_mock.await_args_list
            }
            self.assertIn(
                telegram_message_link("-100123", result["line_1"]),
                final[result["transport"]],
            )
            self.assertIn(
                telegram_message_link("-100123", result["transport"]),
                final[result["line_1"]],
            )
            self.assertIn(
                telegram_message_link("-100123", result["places"]),
                final[result["root"]],
            )
            self.assertIn(
                telegram_message_link("-100123", result["activities"]),
                final[result["root"]],
            )

    async def test_second_run_edits_without_duplicate_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = self._messages()
            state.write("-100123", messages)
            send = AsyncMock()
            edit = AsyncMock()
            pin = AsyncMock()
            result = await publish_pinned_guide(
                "-100123", state, send, edit, pin
            )
            send.assert_not_awaited()
            self.assertEqual(edit.await_count, len(PINNED_MESSAGE_KEYS))
            pin.assert_awaited_once_with(result["root"])

    async def test_unchanged_telegram_messages_do_not_create_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write("-100123", self._messages())
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

    async def test_missing_transport_leaf_is_recreated_and_links_follow_it(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = self._messages()
            state.write("-100123", messages)

            async def edit(message_id, message):
                if message_id == messages["line_1"]:
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
                    )

            send = AsyncMock(return_value=99)
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, AsyncMock()
            )
            send.assert_awaited_once()
            self.assertEqual(result["line_1"], 99)
            saved = json.loads(state.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["messages"]["line_1"], 99)
            transport_edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == result["transport"]
            ]
            self.assertIn("https://t.me/c/123/99", transport_edits[-1])

    async def test_deleted_transport_updates_leaf_and_root_backlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = self._messages()
            state.write("-100123", messages)
            old_transport = messages["transport"]

            async def edit(message_id, message):
                if message_id == old_transport:
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
                    )

            send = AsyncMock(return_value=99)
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, AsyncMock()
            )
            self.assertEqual(result["transport"], 99)
            leaf_edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == result["line_1"]
            ]
            root_edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == result["root"]
            ]
            self.assertIn("https://t.me/c/123/99", leaf_edits[-1])
            self.assertIn("https://t.me/c/123/99", root_edits[-1])

    async def test_deleted_indoor_pool_updates_polideportivo_and_swimming(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = self._messages()
            state.write("-100123", messages)
            old_indoor = messages["pool_indoor"]

            async def edit(message_id, message):
                if message_id == old_indoor:
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
                    )

            send = AsyncMock(return_value=99)
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, AsyncMock()
            )
            self.assertEqual(result["pool_indoor"], 99)
            for key in ("polideportivo", "swimming"):
                edits = [
                    call.args[1] for call in edit_mock.await_args_list
                    if call.args[0] == result[key]
                ]
                self.assertIn("https://t.me/c/123/99", edits[-1])

    async def test_deleted_polideportivo_updates_places(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            messages = self._messages()
            state.write("-100123", messages)
            old_complex = messages["polideportivo"]

            async def edit(message_id, message):
                if message_id == old_complex:
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
                    )

            send = AsyncMock(return_value=99)
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                "-100123", state, send, edit_mock, AsyncMock()
            )
            self.assertEqual(result["polideportivo"], 99)
            places_edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == result["places"]
            ]
            self.assertIn("https://t.me/c/123/99", places_edits[-1])

    async def test_deleted_camera_and_root_are_recreated_together(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            stored = self._messages()
            state.write("-100123", stored)
            deleted = {stored["cameras"], stored["root"]}
            next_id = 90

            async def edit(message_id, message):
                if message_id in deleted:
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
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
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == 91
            ]
            root_edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == 92
            ]
            self.assertIn("https://t.me/c/123/92", camera_edits[-1])
            self.assertIn("https://t.me/c/123/91", root_edits[-1])

    async def test_all_deleted_messages_are_recreated_as_one_valid_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            stored = self._messages()
            state.write("-100123", stored)
            next_id = 100

            async def edit(message_id, message):
                if message_id in stored.values():
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
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

            self.assertEqual(len(set(result.values())), len(PINNED_MESSAGE_KEYS))
            self.assertTrue(set(result.values()).isdisjoint(stored.values()))
            pin.assert_awaited_once_with(result["root"])
            final_text = {
                message_id: [
                    call.args[1] for call in edit_mock.await_args_list
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
                self.assertIn(
                    telegram_message_link("-100123", result[key]),
                    final_text[result["transport"]],
                )
            self.assertIn(root_link, final_text[result["cameras"]])
            self.assertIn(root_link, final_text[result["transport"]])
            self.assertIn(
                telegram_message_link("-100123", result["polideportivo"]),
                final_text[result["places"]],
            )
            self.assertIn(
                telegram_message_link("-100123", result["pool_indoor"]),
                final_text[result["polideportivo"]],
            )
            self.assertIn(
                telegram_message_link("-100123", result["pool_outdoor"]),
                final_text[result["polideportivo"]],
            )
            self.assertIn(
                telegram_message_link("-100123", result["swimming"]),
                final_text[result["pool_indoor"]],
            )
            self.assertIn(
                telegram_message_link("-100123", result["swimming"]),
                final_text[result["activities"]],
            )

    async def test_root_deleted_before_pin_is_recreated_and_relinked(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            stored = self._messages()
            state.write("-100123", stored)
            pin = AsyncMock(
                side_effect=(
                    TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
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
            state.write("-100123", self._messages())
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
