import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.event_access import AccessOption, EventAccessRecord
from telegrambot.event_registration_notifications import (
    RegistrationDeliveryUncertain,
    RegistrationNotificationState,
    EventAccessStateError,
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


class MigrationStateTests(unittest.TestCase):
    def test_explicit_migration_writes_backup_and_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(legacy_state()), encoding="utf-8")
            state = RegistrationNotificationState(path)

            result = state.migrate()
            saved = state.read()
            backup = json.loads(
                state.backup_path.read_text(encoding="utf-8")
            )

        self.assertEqual(result, "migrated_v1_to_v2")
        self.assertEqual(saved["version"], 2)
        self.assertEqual(backup, legacy_state())

    def test_migration_is_idempotent_after_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(legacy_state()), encoding="utf-8")
            state = RegistrationNotificationState(path)

            state.migrate()
            before = path.read_bytes()
            result = state.migrate()
            after = path.read_bytes()

        self.assertEqual(result, "already_v2")
        self.assertEqual(before, after)

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
            state.write({
                "version": 2,
                "records": {},
                "uncertain": None,
            })
            current = state.read()
            candidate = {
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
                "root_message_id": None,
                "sent_triggers": [],
            }
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


class RenderingTests(unittest.TestCase):
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


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def run_with(self, records, publish, state=None):
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
        async def publish(_message, _reply_to):
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
