import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.event_access import (
    AccessNotice,
    AccessOption,
    EventAccessDecision,
    EventAccessRecord,
    candidate_record_state,
    empty_state,
)
from telegrambot.event_registration_notifications import (
    RegistrationDeliveryUncertain,
    RegistrationNotificationState,
    EventAccessStateError,
    _run_cli,
    _status_summary,
    render_reply,
    render_root,
    run_registration_notifications,
)
from telegrambot.telegram import TelegramError


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=TZ)


def record(record_id="convega:post-1:stage-21", **changes):
    values = {
        "record_id": record_id,
        "source": "convega",
        "source_url": "https://convega.com/example",
        "access_kind": "registration",
        "title": "Поход с гидом по GR-92 · этап 21",
        "event_start_date": date(2026, 10, 4),
        "event_end_date": None,
        "place": "Guardamar del Segura",
        "route": "Guardamar → Torrevieja",
        "details": ("15,43 км", "4,5–5 ч"),
        "schedule_note": "Сбор 08:00 · старт 08:30",
        "options": (
            AccessOption(
                option_id="default",
                status="open",
                action_url="https://convega.com/register",
                until_full=True,
            ),
        ),
    }
    values.update(changes)
    return EventAccessRecord(**values)


def legacy_state():
    return {
        "version": 1,
        "baseline": {
            "convega:post-42197:stage-21": {
                "record_id": "convega:post-42197:stage-21",
                "source": "convega",
                "source_url": "https://convega.com/example",
                "title": "Ruta guiada GR-92 · Etapa 21",
                "event_start_date": "2026-10-04",
                "event_end_date": None,
                "registration_start_date": None,
                "registration_start_time": None,
                "registration_end_date": None,
                "registration_end_time": None,
                "status": "full",
                "last_explicit_status": "full",
                "until_full": True,
                "registration_url": None,
                "registration_contact": None,
            }
        },
        "announced_record_ids": [],
        "sent_triggers": [],
        "uncertain": None,
    }


def v2_state():
    return {
        "version": 2,
        "records": {
            "convega:post-1:stage-21": {
                "source": "convega",
                "access_kind": "registration",
                "event_start_date": "2026-10-04",
                "event_end_date": None,
                "options": {
                    "default": {
                        "status": "open",
                        "last_explicit_status": "open",
                        "opens_on": None,
                        "opens_time": None,
                        "closes_on": None,
                        "closes_time": None,
                        "until_full": True,
                        "action_url": "https://convega.com/register",
                        "action_text": None,
                    }
                },
                "audience_known": True,
                "root_message_id": 321,
                "sent_triggers": [],
            }
        },
        "uncertain": None,
    }


class MigrationStateTests(unittest.TestCase):
    def test_missing_state_migrates_to_empty_v3(self):
        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "state.json"
            )

            result = state.migrate()
            saved = state.read()

        self.assertEqual(result, "created_v3")
        self.assertEqual(saved, empty_state())

    def test_explicit_v1_migration_writes_backup_and_v3(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(legacy_state()), encoding="utf-8")
            state = RegistrationNotificationState(path)

            result = state.migrate()
            saved = state.read()
            backup = json.loads(
                state.backup_path.read_text(encoding="utf-8")
            )

        self.assertEqual(result, "migrated_v1_to_v3")
        self.assertEqual(saved["version"], 3)
        self.assertEqual(backup, legacy_state())

    def test_migration_is_idempotent_after_v3(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(legacy_state()), encoding="utf-8")
            state = RegistrationNotificationState(path)

            state.migrate()
            before = path.read_bytes()
            result = state.migrate()
            after = path.read_bytes()

        self.assertEqual(result, "already_v3")
        self.assertEqual(before, after)

    def test_v2_migration_writes_separate_backup_and_v3(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            original = v2_state()
            path.write_text(json.dumps(original), encoding="utf-8")
            state = RegistrationNotificationState(path)

            result = state.migrate()
            saved = state.read()
            backup = json.loads(
                state.v2_backup_path.read_text(encoding="utf-8")
            )

        self.assertEqual(result, "migrated_v2_to_v3")
        self.assertEqual(saved["version"], 3)
        item = saved["records"]["convega:post-1:stage-21"]
        self.assertFalse(item["context_known"])
        self.assertEqual(item["root_message_id"], 321)
        self.assertEqual(backup, original)

    def test_status_reports_v2_as_migration_required(self):
        summary = json.loads(_status_summary(v2_state()))

        self.assertEqual(summary["version"], 2)
        self.assertTrue(summary["migration_required"])
        self.assertEqual(summary["records"], 1)
        self.assertEqual(summary["root_records"], 1)

    def test_backup_collision_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(legacy_state()), encoding="utf-8")
            state = RegistrationNotificationState(path)
            state.backup_path.write_text('{"different":true}', encoding="utf-8")

            with self.assertRaises(EventAccessStateError):
                state.migrate()

    def test_root_resolution_requires_message_id(self):
        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "state.json"
            )
            state.write(empty_state())
            current = state.read()
            candidate = candidate_record_state(record(), None)
            candidate["audience_known"] = True
            state.reserve(
                current,
                "convega:post-1:stage-21",
                "root",
                "message",
                candidate,
                NOW,
            )

            with self.assertRaises(EventAccessStateError):
                state.confirm_uncertain()

    def test_ambiguous_reply_resolution_needs_no_reply_message_id(self):
        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "state.json"
            )
            committed = candidate_record_state(record(), None)
            committed["audience_known"] = True
            committed["root_message_id"] = 321
            state.write({
                "version": 3,
                "records": {"convega:post-1:stage-21": committed},
                "uncertain": None,
            })
            candidate = json.loads(json.dumps(committed))
            candidate["options"]["default"]["status"] = "full"
            candidate["options"]["default"]["last_explicit_status"] = "full"
            candidate["options"]["default"]["action_url"] = None
            current = state.read()
            state.reserve(
                current,
                "convega:post-1:stage-21",
                "reply",
                "message",
                candidate,
                NOW,
            )

            resolved = state.confirm_uncertain()

        self.assertIsNone(resolved["uncertain"])
        self.assertEqual(
            resolved["records"][
                "convega:post-1:stage-21"
            ]["root_message_id"],
            321,
        )
        self.assertEqual(
            resolved["records"][
                "convega:post-1:stage-21"
            ]["options"]["default"]["status"],
            "full",
        )


class RenderingTests(unittest.TestCase):
    def test_future_opening_root_keeps_exact_boundary(self):
        from telegrambot.event_access import plan_event_access_record

        item = record(
            options=(
                AccessOption(
                    option_id="default",
                    opens_on=date(2026, 10, 3),
                    opens_time=datetime.strptime("10:30", "%H:%M").time(),
                ),
            )
        )
        decision = plan_event_access_record(item, None, NOW)

        message = render_root(item, decision)

        self.assertIn("Завтра открывается регистрация", message)
        self.assertIn("Регистрация: с 3 октября, 10:30", message)

    def test_unknown_deadline_wording_does_not_claim_registration_is_open(self):
        item = record(
            options=(
                AccessOption(
                    option_id="default",
                    status="unknown",
                    closes_on=date(2026, 10, 10),
                ),
            )
        )
        decision = EventAccessDecision(
            candidate_record={},
            notices=(AccessNotice("deadline-known", "default"),),
            operation="reply",
            reply_to_message_id=100,
        )

        message = render_reply(item, decision)

        self.assertIn("Указан срок регистрации", message)
        self.assertNotIn("Записаться можно", message)

    def test_root_is_self_contained_and_uses_current_action(self):
        from telegrambot.event_access import plan_event_access_record

        item = record()
        decision = plan_event_access_record(item, None, NOW)

        message = render_root(item, decision)

        self.assertIn("Открыта регистрация", message)
        self.assertIn("Поход с гидом по GR-92", message)
        self.assertIn("Guardamar → Torrevieja", message)
        self.assertIn("15,43 км", message)
        self.assertIn("Сбор 08:00", message)
        self.assertIn("Записаться", message)
        self.assertIn("Места ограничены", message)


    def test_reservation_root_uses_reservation_wording(self):
        from telegrambot.event_access import plan_event_access_record

        item = record(access_kind="reservation")
        decision = plan_event_access_record(item, None, NOW)

        message = render_root(item, decision)

        self.assertIn("Открыто бронирование", message)
        self.assertIn("Забронировать", message)
        self.assertNotIn("Открыта регистрация", message)

    def test_ticket_root_uses_ticket_wording(self):
        from telegrambot.event_access import plan_event_access_record

        item = record(access_kind="ticket")
        decision = plan_event_access_record(item, None, NOW)

        message = render_root(item, decision)

        self.assertIn("Билеты доступны", message)
        self.assertIn("Получить билет", message)
        self.assertNotIn("Открыта регистрация", message)

    def test_multi_option_root_labels_each_action(self):
        from telegrambot.event_access import plan_event_access_record

        item = record(
            options=(
                AccessOption(
                    option_id="adult",
                    label="Взрослый забег",
                    status="open",
                    action_url="https://example.com/adult",
                ),
                AccessOption(
                    option_id="kids",
                    label="Детский забег",
                    status="open",
                    action_url="https://example.com/kids",
                ),
            )
        )
        decision = plan_event_access_record(item, None, NOW)

        message = render_root(item, decision)

        self.assertIn("Взрослый забег", message)
        self.assertIn("Детский забег", message)

    def test_event_date_correction_reply_is_explicit(self):
        item = record(event_start_date=date(2026, 10, 5))
        decision = EventAccessDecision(
            candidate_record={},
            notices=(AccessNotice("event-date-changed"),),
            operation="reply",
            reply_to_message_id=100,
        )

        message = render_reply(item, decision)

        self.assertIn("Дата события изменилась", message)
        self.assertIn("5 октября", message)

    def test_event_details_correction_reply_shows_current_facts(self):
        item = record(
            place="Palau Sant Jaume",
            schedule_note="Старт 11:00",
        )
        decision = EventAccessDecision(
            candidate_record={},
            notices=(AccessNotice("event-details-changed"),),
            operation="reply",
            reply_to_message_id=100,
        )

        message = render_reply(item, decision)

        self.assertIn("Изменились данные события", message)
        self.assertIn("Palau Sant Jaume", message)
        self.assertIn("Старт 11:00", message)

    def test_restored_event_reply_is_explicit(self):
        item = record(occurrence_status="scheduled")
        decision = EventAccessDecision(
            candidate_record={},
            notices=(AccessNotice("event-restored"),),
            operation="reply",
            reply_to_message_id=100,
        )

        message = render_reply(item, decision)

        self.assertIn("Событие снова подтверждено", message)

    def test_explicit_cancellation_reply_is_not_registration_worded(self):
        item = record(
            occurrence_status="cancelled",
            options=(
                AccessOption(
                    option_id="default",
                    status="unknown",
                ),
            ),
        )
        decision = EventAccessDecision(
            candidate_record={},
            notices=(AccessNotice("event-cancelled"),),
            operation="reply",
            reply_to_message_id=100,
        )

        message = render_reply(item, decision)

        self.assertIn("Событие отменено", message)
        self.assertNotIn("Регистрация", message)


class DeliveryPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_enables_only_rate_limit_retry_for_new_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "notify.json"
            state = RegistrationNotificationState(state_path)
            state.write(empty_state())

            async def fake_run(
                _now,
                _state,
                publish,
                *,
                source_state_path,
                publish_photo,
            ):
                self.assertIsNotNone(publish_photo)
                self.assertEqual(
                    source_state_path,
                    Path(directory) / "convega.json",
                )
                message_id = await publish("hello", None)
                self.assertEqual(message_id, 77)
                return "sent"

            with (
                patch.dict(
                    os.environ,
                    {
                        "EVENT_REGISTRATION_STATE_PATH": str(state_path),
                        "CONVEGA_STATE_PATH": str(
                            Path(directory) / "convega.json"
                        ),
                        "TELEGRAM_BOT_TOKEN": "token",
                        "TELEGRAM_CHAT_ID": "-100123",
                    },
                    clear=False,
                ),
                patch(
                    "telegrambot.event_registration_notifications."
                    "run_registration_notifications",
                    new=fake_run,
                ),
                patch(
                    "telegrambot.event_registration_notifications.send_message",
                    new=AsyncMock(return_value=77),
                ) as send,
            ):
                code = await _run_cli("run")

        self.assertEqual(code, 0)
        send.assert_awaited_once_with(
            "token",
            "-100123",
            "hello",
            disable_notification=False,
            reply_to_message_id=None,
            retry_only_rate_limits=True,
        )


    async def test_cli_photo_root_is_not_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "notify.json"
            state = RegistrationNotificationState(state_path)
            state.write(empty_state())

            async def fake_run(
                _now,
                _state,
                _publish,
                *,
                source_state_path,
                publish_photo,
            ):
                self.assertEqual(
                    source_state_path,
                    Path(directory) / "convega.json",
                )
                message_id = await publish_photo(
                    "https://example.com/poster.jpg",
                    "caption",
                )
                self.assertEqual(message_id, 88)
                return "sent"

            with (
                patch.dict(
                    os.environ,
                    {
                        "EVENT_REGISTRATION_STATE_PATH": str(state_path),
                        "CONVEGA_STATE_PATH": str(
                            Path(directory) / "convega.json"
                        ),
                        "TELEGRAM_BOT_TOKEN": "token",
                        "TELEGRAM_CHAT_ID": "-100123",
                    },
                    clear=False,
                ),
                patch(
                    "telegrambot.event_registration_notifications."
                    "run_registration_notifications",
                    new=fake_run,
                ),
                patch(
                    "telegrambot.event_registration_notifications."
                    "send_photo_url",
                    new=AsyncMock(return_value=(88, "file-id")),
                ) as send_photo,
            ):
                code = await _run_cli("run")

        self.assertEqual(code, 0)
        send_photo.assert_awaited_once_with(
            "token",
            "-100123",
            "https://example.com/poster.jpg",
            "caption",
            disable_notification=False,
        )


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def run_with(
        self,
        records,
        publish,
        state=None,
        *,
        publish_photo=None,
    ):
        if state is None:
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            state = RegistrationNotificationState(
                Path(temp.name) / "notify.json"
            )

        with (
            patch(
                "telegrambot.event_registration_notifications."
                "convega_snapshot_is_access_fresh",
                return_value=True,
            ),
            patch(
                "telegrambot.event_registration_notifications."
                "load_convega_access_records",
                new=AsyncMock(return_value=tuple(records)),
            ),
        ):
            return await run_registration_notifications(
                NOW,
                state,
                publish,
                source_state_path=Path("unused.json"),
                publish_photo=publish_photo,
            )

    async def test_photo_root_stores_photo_message_id(self):
        async def publish(_message, _reply_to):
            raise AssertionError("text root must not be used")

        async def publish_photo(photo_url, caption):
            self.assertEqual(photo_url, "https://example.com/poster.jpg")
            self.assertIn("Открыта регистрация", caption)
            return 345

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            result = await self.run_with(
                (record(image_url="https://example.com/poster.jpg"),),
                publish,
                state,
                publish_photo=publish_photo,
            )
            saved = state.read()

        self.assertEqual(result, "sent")
        self.assertEqual(
            saved["records"][
                "convega:post-1:stage-21"
            ]["root_message_id"],
            345,
        )
        self.assertIsNone(saved["uncertain"])

    async def test_remote_media_rejection_falls_back_to_text_root(self):
        calls = []

        async def publish(message, reply_to):
            calls.append(("text", reply_to, message))
            return 456

        async def publish_photo(_photo_url, _caption):
            calls.append(("photo", None, None))
            raise TelegramError(
                "remote media rejected",
                retryable=False,
                code="REMOTE-MEDIA",
                status=400,
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            result = await self.run_with(
                (record(image_url="https://example.com/poster.jpg"),),
                publish,
                state,
                publish_photo=publish_photo,
            )
            saved = state.read()

        self.assertEqual(result, "sent")
        self.assertEqual([item[0] for item in calls], ["photo", "text"])
        self.assertEqual(calls[1][1], None)
        self.assertEqual(
            saved["records"][
                "convega:post-1:stage-21"
            ]["root_message_id"],
            456,
        )
        self.assertIsNone(saved["uncertain"])

    async def test_ambiguous_photo_failure_never_falls_back_to_text(self):
        text_calls = 0

        async def publish(_message, _reply_to):
            nonlocal text_calls
            text_calls += 1
            return 999

        async def publish_photo(_photo_url, _caption):
            raise TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            with self.assertRaises(RegistrationDeliveryUncertain):
                await self.run_with(
                    (record(image_url="https://example.com/poster.jpg"),),
                    publish,
                    state,
                    publish_photo=publish_photo,
                )
            saved = state.read()

        self.assertEqual(text_calls, 0)
        self.assertIsNotNone(saved["uncertain"])
        self.assertEqual(saved["uncertain"]["operation"], "root")

    async def test_long_root_uses_text_instead_of_photo(self):
        photo_calls = 0

        async def publish(message, reply_to):
            self.assertGreater(len(message), 1024)
            self.assertIsNone(reply_to)
            return 567

        async def publish_photo(_photo_url, _caption):
            nonlocal photo_calls
            photo_calls += 1
            return 999

        item = record(
            title="Событие " + "А" * 950,
            image_url="https://example.com/poster.jpg",
        )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            result = await self.run_with(
                (item,),
                publish,
                state,
                publish_photo=publish_photo,
            )

        self.assertEqual(result, "sent")
        self.assertEqual(photo_calls, 0)

    async def test_duplicate_record_ids_fail_before_delivery(self):
        async def publish(_message, _reply_to):
            raise AssertionError("duplicate records must not publish")

        duplicate = record("convega:duplicate")

        with self.assertRaises(EventAccessStateError):
            await self.run_with(
                (duplicate, duplicate),
                publish,
            )

    async def test_confirmed_root_stores_returned_message_id(self):
        async def publish(message, reply_to):
            self.assertIsNone(reply_to)
            self.assertIn("Открыта регистрация", message)
            return 123

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            result = await self.run_with((record(),), publish, state)
            saved = state.read()

        self.assertEqual(result, "sent")
        item = saved["records"]["convega:post-1:stage-21"]
        self.assertEqual(item["root_message_id"], 123)
        self.assertTrue(item["audience_known"])
        self.assertIsNone(saved["uncertain"])

    async def test_deterministic_failure_clears_uncertain(self):
        async def publish(_message, _reply_to):
            raise TelegramError(
                "rejected",
                retryable=False,
                code="HTTP-400",
                status=400,
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            with self.assertRaises(TelegramError):
                await self.run_with((record(),), publish, state)
            saved = state.read()

        self.assertIsNone(saved["uncertain"])
        self.assertNotIn(
            "convega:post-1:stage-21",
            saved["records"],
        )

    async def test_ambiguous_failure_keeps_root_reservation(self):
        calls = 0

        async def publish(_message, _reply_to):
            nonlocal calls
            calls += 1
            raise TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            with self.assertRaises(RegistrationDeliveryUncertain):
                await self.run_with((record(),), publish, state)
            raw = state.read()

        self.assertIsNotNone(raw["uncertain"])
        self.assertEqual(raw["uncertain"]["operation"], "root")
        self.assertEqual(
            raw["uncertain"]["record_id"],
            "convega:post-1:stage-21",
        )
        self.assertEqual(calls, 1)

    async def test_replies_never_repeat_root_photo(self):
        text_calls = []
        photo_calls = 0

        async def publish(message, reply_to):
            text_calls.append((message, reply_to))
            return 222

        async def publish_photo(_photo_url, _caption):
            nonlocal photo_calls
            photo_calls += 1
            return 222

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            item = record(image_url="https://example.com/poster.jpg")
            await self.run_with(
                (item,),
                publish,
                state,
                publish_photo=publish_photo,
            )

            full = record(
                image_url="https://example.com/poster.jpg",
                options=(
                    AccessOption(
                        option_id="default",
                        status="full",
                        until_full=True,
                    ),
                ),
            )
            await self.run_with(
                (full,),
                publish,
                state,
                publish_photo=publish_photo,
            )

        self.assertEqual(photo_calls, 1)
        self.assertEqual(len(text_calls), 1)
        self.assertEqual(text_calls[0][1], 222)
        self.assertIn("Мест больше нет", text_calls[0][0])

    async def test_reply_uses_existing_root_id(self):
        calls = []

        async def publish(message, reply_to):
            calls.append((message, reply_to))
            return 222

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            await self.run_with((record(),), publish, state)

            full = record(
                options=(
                    AccessOption(
                        option_id="default",
                        status="full",
                        until_full=True,
                    ),
                )
            )
            result = await self.run_with((full,), publish, state)
            saved = state.read()

        self.assertEqual(result, "sent")
        self.assertEqual(calls[-1][1], 222)
        self.assertIn("Мест больше нет", calls[-1][0])
        self.assertEqual(
            saved["records"][
                "convega:post-1:stage-21"
            ]["root_message_id"],
            222,
        )

    async def test_missing_reply_target_fails_closed_without_replacement_root(self):
        calls = []

        async def publish(message, reply_to):
            calls.append((message, reply_to))
            if len(calls) == 1:
                return 222
            raise TelegramError(
                "reply target missing",
                retryable=False,
                code="MESSAGE-NOT-FOUND",
                status=400,
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            await self.run_with((record(),), publish, state)

            full = record(
                options=(
                    AccessOption(
                        option_id="default",
                        status="full",
                        until_full=True,
                    ),
                )
            )
            with self.assertRaises(TelegramError):
                await self.run_with((full,), publish, state)
            saved = state.read()

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1][1], 222)
        self.assertIsNone(saved["uncertain"])
        item = saved["records"]["convega:post-1:stage-21"]
        self.assertEqual(item["root_message_id"], 222)
        self.assertEqual(item["options"]["default"]["status"], "open")

    async def test_state_write_failure_after_send_leaves_uncertain(self):
        async def publish(_message, _reply_to):
            return 123

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            original = state.confirm_uncertain

            def fail_confirm(root_message_id=None):
                raise OSError("disk failure")

            state.confirm_uncertain = fail_confirm
            with self.assertRaises(OSError):
                await self.run_with((record(),), publish, state)
            state.confirm_uncertain = original
            saved = state.read()

        self.assertIsNotNone(saved["uncertain"])
        self.assertEqual(saved["uncertain"]["operation"], "root")

    async def test_ambiguous_first_record_blocks_later_record_same_run(self):
        calls = []

        async def publish(message, reply_to):
            calls.append((message, reply_to))
            raise TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            first = record("convega:post-1:stage-21")
            second = record("convega:post-2:stage-22")

            with self.assertRaises(RegistrationDeliveryUncertain):
                await self.run_with((first, second), publish, state)
            saved = state.read()

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            saved["uncertain"]["record_id"],
            "convega:post-1:stage-21",
        )
        self.assertNotIn(
            "convega:post-2:stage-22",
            saved["records"],
        )

    async def test_uncertain_blocks_automatic_followup(self):
        async def timeout(_message, _reply_to):
            raise TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            with self.assertRaises(RegistrationDeliveryUncertain):
                await self.run_with((record(),), timeout, state)

            async def should_not_send(_message, _reply_to):
                raise AssertionError("must not publish while uncertain")

            result = await self.run_with(
                (record(),),
                should_not_send,
                state,
            )

        self.assertEqual(result, "uncertain")

    async def test_earlier_record_stays_committed_when_later_is_ambiguous(self):
        first = record("convega:post-1:stage-21")
        second = record("convega:post-2:stage-22")
        calls = 0

        async def publish(_message, _reply_to):
            nonlocal calls
            calls += 1
            if calls == 1:
                return 111
            raise TelegramError(
                "timeout",
                retryable=True,
                code="TIMEOUT",
            )

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            with self.assertRaises(RegistrationDeliveryUncertain):
                await self.run_with((first, second), publish, state)
            saved = state.read()

        self.assertEqual(
            saved["records"][
                "convega:post-1:stage-21"
            ]["root_message_id"],
            111,
        )
        self.assertEqual(
            saved["uncertain"]["record_id"],
            "convega:post-2:stage-22",
        )

    async def test_stale_source_skips_before_loading_records(self):
        async def publish(_message, _reply_to):
            raise AssertionError

        with tempfile.TemporaryDirectory() as directory:
            state = RegistrationNotificationState(
                Path(directory) / "notify.json"
            )
            with (
                patch(
                    "telegrambot.event_registration_notifications."
                    "convega_snapshot_is_access_fresh",
                    return_value=False,
                ),
                patch(
                    "telegrambot.event_registration_notifications."
                    "load_convega_access_records",
                    new=AsyncMock(
                        side_effect=AssertionError("must not load stale")
                    ),
                ),
            ):
                result = await run_registration_notifications(
                    NOW,
                    state,
                    publish,
                    source_state_path=Path("unused.json"),
                )

        self.assertEqual(result, "stale_source")


if __name__ == "__main__":
    unittest.main()
