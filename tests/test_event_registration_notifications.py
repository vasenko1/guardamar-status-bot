import asyncio
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.event_registration_notifications import (
    RegistrationDeliveryUncertain,
    RegistrationNotificationState,
    RegistrationRecord,
    plan_registration_run,
    run_registration_notifications,
)
from telegrambot.telegram import TelegramError


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 2, 12, 47, tzinfo=TZ)


def record(**changes):
    values = {
        "record_id": "official:event-1",
        "source": "official",
        "source_url": "https://official.example/event",
        "title": "Evento de prueba",
        "event_start_date": date(2026, 10, 10),
        "status": "unknown",
    }
    values.update(changes)
    if (
        values["status"] == "open"
        and "registration_url" not in changes
        and "registration_contact" not in changes
    ):
        values["registration_url"] = "https://official.example/register"
    return RegistrationRecord(**values)


def empty_state():
    with tempfile.TemporaryDirectory() as directory:
        return RegistrationNotificationState(
            Path(directory) / "state.json"
        ).read()


class RegistrationPlanningTests(unittest.TestCase):
    def test_first_seen_full_is_silent_but_keeps_explicit_evidence(self):
        plan = plan_registration_run(
            (record(status="full"),),
            empty_state(),
            NOW,
        )

        self.assertIsNone(plan.publication)
        saved = plan.candidate_baseline["official:event-1"]
        self.assertEqual(saved["status"], "full")
        self.assertEqual(saved["last_explicit_status"], "full")
        self.assertEqual(plan.candidate_announced_record_ids, ())

    def test_first_seen_open_publishes_current_active_registration(self):
        active = record(
            status="open",
            registration_url="https://official.example/register",
        )
        plan = plan_registration_run((active,), empty_state(), NOW)

        self.assertIsNotNone(plan.publication)
        self.assertIn("Идёт запись", plan.publication.message)
        self.assertIn("Записаться", plan.publication.message)
        self.assertEqual(
            plan.candidate_announced_record_ids,
            ("official:event-1",),
        )

    def test_first_seen_full_then_open_is_active_not_reopened(self):
        first = plan_registration_run(
            (record(status="full"),),
            empty_state(),
            NOW,
        )
        state = {
            "version": 1,
            "baseline": dict(first.candidate_baseline),
            "announced_record_ids": list(first.candidate_announced_record_ids),
            "sent_triggers": list(first.candidate_sent_triggers),
            "uncertain": None,
        }

        second = plan_registration_run(
            (record(status="open"),),
            state,
            datetime(2026, 10, 3, 12, 47, tzinfo=TZ),
        )

        self.assertIn("Идёт запись", second.publication.message)
        self.assertNotIn("снова открыта", second.publication.message)

    def test_announced_full_unknown_open_keeps_reopening_evidence(self):
        state = empty_state()
        opened = plan_registration_run((record(status="open"),), state, NOW)
        state = {
            "version": 1,
            "baseline": dict(opened.candidate_baseline),
            "announced_record_ids": list(opened.candidate_announced_record_ids),
            "sent_triggers": list(opened.candidate_sent_triggers),
            "uncertain": None,
        }
        full = plan_registration_run(
            (record(status="full"),),
            state,
            datetime(2026, 10, 3, 12, 47, tzinfo=TZ),
        )
        state = {
            "version": 1,
            "baseline": dict(full.candidate_baseline),
            "announced_record_ids": list(full.candidate_announced_record_ids),
            "sent_triggers": list(full.candidate_sent_triggers),
            "uncertain": None,
        }
        unknown = plan_registration_run(
            (record(status="unknown"),),
            state,
            datetime(2026, 10, 4, 12, 47, tzinfo=TZ),
        )
        self.assertIsNone(unknown.publication)
        self.assertEqual(
            unknown.candidate_baseline["official:event-1"]["status"],
            "unknown",
        )
        self.assertEqual(
            unknown.candidate_baseline["official:event-1"]["last_explicit_status"],
            "full",
        )
        state = {
            "version": 1,
            "baseline": dict(unknown.candidate_baseline),
            "announced_record_ids": list(unknown.candidate_announced_record_ids),
            "sent_triggers": list(unknown.candidate_sent_triggers),
            "uncertain": None,
        }

        reopened = plan_registration_run(
            (record(status="open"),),
            state,
            datetime(2026, 10, 5, 12, 47, tzinfo=TZ),
        )

        self.assertIn("Регистрация снова открыта", reopened.publication.message)

    def test_first_seen_open_with_deadline_tomorrow_prefers_deadline_notice(self):
        active = record(
            status="open",
            registration_end_date=date(2026, 10, 3),
        )

        plan = plan_registration_run((active,), empty_state(), NOW)

        self.assertIn("Завтра заканчивается запись", plan.publication.message)
        self.assertNotIn("<b>Идёт запись</b>", plan.publication.message)

    def test_contact_only_open_registration_renders_contact(self):
        active = record(
            status="open",
            registration_url=None,
            registration_contact="inscripciones@official.example",
        )

        plan = plan_registration_run((active,), empty_state(), NOW)

        self.assertIn(
            "регистрация: inscripciones@official.example",
            plan.publication.message,
        )

    def test_full_transition_beats_deadline_reminder(self):
        state = empty_state()
        opened = plan_registration_run(
            (
                record(
                    status="open",
                    registration_end_date=date(2026, 10, 4),
                ),
            ),
            state,
            NOW,
        )
        state = {
            "version": 1,
            "baseline": dict(opened.candidate_baseline),
            "announced_record_ids": list(opened.candidate_announced_record_ids),
            "sent_triggers": list(opened.candidate_sent_triggers),
            "uncertain": None,
        }

        plan = plan_registration_run(
            (
                record(
                    status="full",
                    registration_end_date=date(2026, 10, 4),
                ),
            ),
            state,
            datetime(2026, 10, 3, 12, 47, tzinfo=TZ),
        )

        self.assertIn("Места закончились", plan.publication.message)
        self.assertNotIn("Завтра заканчивается", plan.publication.message)

    def test_future_opening_notice_does_not_offer_signup_action(self):
        future = record(
            status="unknown",
            registration_start_date=date(2026, 10, 3),
            registration_url="https://official.example/register",
        )

        plan = plan_registration_run((future,), empty_state(), NOW)

        self.assertIn("Завтра открывается", plan.publication.message)
        self.assertNotIn("Записаться", plan.publication.message)

    def test_opening_tomorrow_suppresses_same_day_fallback_after_success(self):
        opening = record(
            registration_start_date=date(2026, 10, 3),
            status="unknown",
        )
        advance = plan_registration_run((opening,), empty_state(), NOW)

        self.assertIn("Завтра открывается", advance.publication.message)
        state = {
            "version": 1,
            "baseline": dict(advance.candidate_baseline),
            "announced_record_ids": list(advance.candidate_announced_record_ids),
            "sent_triggers": list(advance.candidate_sent_triggers),
            "uncertain": None,
        }

        same_day = plan_registration_run(
            (opening,),
            state,
            datetime(2026, 10, 3, 8, 0, tzinfo=TZ),
        )

        self.assertIsNone(same_day.publication)

    def test_one_day_window_tomorrow_is_one_semantic_notice(self):
        one_day = record(
            registration_start_date=date(2026, 10, 3),
            registration_end_date=date(2026, 10, 3),
            status="unknown",
        )

        plan = plan_registration_run((one_day,), empty_state(), NOW)

        self.assertIn("Регистрация только завтра", plan.publication.message)
        self.assertNotIn("заканчивается запись", plan.publication.message)
        self.assertEqual(len(plan.publication.trigger_ids), 1)

    def test_one_day_advance_suppresses_expected_closed_followup(self):
        one_day = record(
            registration_start_date=date(2026, 10, 3),
            registration_end_date=date(2026, 10, 3),
            status="unknown",
        )
        advance = plan_registration_run((one_day,), empty_state(), NOW)
        state = {
            "version": 1,
            "baseline": dict(advance.candidate_baseline),
            "announced_record_ids": list(advance.candidate_announced_record_ids),
            "sent_triggers": list(advance.candidate_sent_triggers),
            "uncertain": None,
        }

        closed = plan_registration_run(
            (replace(one_day, status="closed"),),
            state,
            datetime(2026, 10, 3, 18, 0, tzinfo=TZ),
        )

        self.assertIsNone(closed.publication)

    def test_explicit_open_today_does_not_also_claim_it_will_open(self):
        active = record(
            status="open",
            registration_start_date=date(2026, 10, 2),
        )

        plan = plan_registration_run((active,), empty_state(), NOW)

        self.assertIn("Идёт запись", plan.publication.message)
        self.assertNotIn("Сегодня открывается регистрация", plan.publication.message)

    def test_exact_time_retry_recomputes_after_boundary(self):
        timed = record(
            registration_start_date=date(2026, 10, 2),
            registration_start_time=time(10, 30),
            status="unknown",
        )
        before = plan_registration_run(
            (timed,),
            empty_state(),
            datetime(2026, 10, 2, 9, 0, tzinfo=TZ),
        )
        self.assertIn("Сегодня в 10:30 откроется", before.publication.message)

        after = plan_registration_run(
            (
                replace(
                    timed,
                    status="open",
                    registration_url="https://official.example/register",
                ),
            ),
            empty_state(),
            datetime(2026, 10, 2, 11, 0, tzinfo=TZ),
        )
        self.assertIn("Идёт запись", after.publication.message)
        self.assertNotIn("10:30 откроется", after.publication.message)

    def test_disappearance_is_silent_and_preserves_baseline(self):
        initial = plan_registration_run(
            (record(status="full"),),
            empty_state(),
            NOW,
        )
        state = {
            "version": 1,
            "baseline": dict(initial.candidate_baseline),
            "announced_record_ids": list(initial.candidate_announced_record_ids),
            "sent_triggers": list(initial.candidate_sent_triggers),
            "uncertain": None,
        }

        missing = plan_registration_run(
            (),
            state,
            datetime(2026, 10, 3, 12, 47, tzinfo=TZ),
        )

        self.assertIsNone(missing.publication)
        self.assertIn("official:event-1", missing.candidate_baseline)

    def test_event_date_correction_preserves_identity_and_notifies_announced_record(self):
        initial = plan_registration_run(
            (record(status="open"),),
            empty_state(),
            NOW,
        )
        state = {
            "version": 1,
            "baseline": dict(initial.candidate_baseline),
            "announced_record_ids": list(initial.candidate_announced_record_ids),
            "sent_triggers": list(initial.candidate_sent_triggers),
            "uncertain": None,
        }
        changed = replace(
            record(status="open"),
            event_start_date=date(2026, 10, 12),
        )

        plan = plan_registration_run(
            (changed,),
            state,
            datetime(2026, 10, 3, 12, 47, tzinfo=TZ),
        )

        self.assertIn("Изменилась дата мероприятия", plan.publication.message)
        self.assertEqual(changed.record_id, "official:event-1")

    def test_open_before_explicit_start_is_rejected(self):
        impossible = record(
            status="open",
            registration_start_date=date(2026, 10, 3),
        )

        plan = plan_registration_run((impossible,), empty_state(), NOW)

        self.assertIsNone(plan.publication)
        self.assertNotIn("official:event-1", plan.candidate_baseline)

    def test_open_after_exact_deadline_is_rejected(self):
        impossible = record(
            status="open",
            registration_end_date=date(2026, 10, 2),
            registration_end_time=time(12, 0),
        )

        plan = plan_registration_run((impossible,), empty_state(), NOW)

        self.assertIsNone(plan.publication)
        self.assertNotIn("official:event-1", plan.candidate_baseline)

    def test_past_event_does_not_create_new_notice(self):
        past = record(
            event_start_date=date(2026, 10, 1),
            status="open",
        )

        plan = plan_registration_run((past,), empty_state(), NOW)

        self.assertIsNone(plan.publication)


class RegistrationDeliveryStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_send_commits_candidate_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = RegistrationNotificationState(root / "notify.json")
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")

            async def publish(message):
                self.assertIn("Идёт запись", message)
                return 123

            with (
                patch(
                    "telegrambot.event_registration_notifications."
                    "convega_snapshot_observed_at",
                    new=AsyncMock(return_value=NOW),
                ),
                patch(
                    "telegrambot.event_registration_notifications."
                    "load_registration_records",
                    new=AsyncMock(return_value=(record(status="open"),)),
                ),
            ):
                result = await run_registration_notifications(
                    NOW,
                    state,
                    publish,
                    source_state_path=source,
                    translation_path=root / "translations.json",
                )

            saved = state.read()

        self.assertEqual(result, "sent")
        self.assertIsNone(saved["uncertain"])
        self.assertEqual(saved["announced_record_ids"], ["official:event-1"])

    async def test_deterministic_telegram_failure_clears_uncertainty_and_old_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = RegistrationNotificationState(root / "notify.json")
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")

            async def publish(_message):
                raise TelegramError(
                    "rejected",
                    retryable=False,
                    code="HTTP-400",
                    status=400,
                )

            with (
                patch(
                    "telegrambot.event_registration_notifications."
                    "convega_snapshot_observed_at",
                    new=AsyncMock(return_value=NOW),
                ),
                patch(
                    "telegrambot.event_registration_notifications."
                    "load_registration_records",
                    new=AsyncMock(return_value=(record(status="open"),)),
                ),
            ):
                with self.assertRaises(TelegramError):
                    await run_registration_notifications(
                        NOW,
                        state,
                        publish,
                        source_state_path=source,
                        translation_path=root / "translations.json",
                    )

            saved = state.read()

        self.assertIsNone(saved["uncertain"])
        self.assertEqual(saved["baseline"], {})
        self.assertEqual(saved["announced_record_ids"], [])

    async def test_ambiguous_telegram_failure_keeps_candidate_for_operator_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = RegistrationNotificationState(root / "notify.json")
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")

            async def publish(_message):
                raise TelegramError(
                    "timeout",
                    retryable=True,
                    code="TIMEOUT",
                )

            with (
                patch(
                    "telegrambot.event_registration_notifications."
                    "convega_snapshot_observed_at",
                    new=AsyncMock(return_value=NOW),
                ),
                patch(
                    "telegrambot.event_registration_notifications."
                    "load_registration_records",
                    new=AsyncMock(return_value=(record(status="open"),)),
                ),
            ):
                with self.assertRaises(RegistrationDeliveryUncertain):
                    await run_registration_notifications(
                        NOW,
                        state,
                        publish,
                        source_state_path=source,
                        translation_path=root / "translations.json",
                    )

            uncertain = state.read()["uncertain"]
            self.assertIsNotNone(uncertain)
            self.assertEqual(
                uncertain["candidate_announced_record_ids"],
                ["official:event-1"],
            )

            with state.exclusive_run():
                state.confirm_uncertain()
            resolved = state.read()

        self.assertIsNone(resolved["uncertain"])
        self.assertEqual(resolved["announced_record_ids"], ["official:event-1"])

    async def test_future_source_never_mutates_lifecycle_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = RegistrationNotificationState(root / "notify.json")
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")

            with patch(
                "telegrambot.event_registration_notifications."
                "convega_snapshot_observed_at",
                new=AsyncMock(
                    return_value=datetime(2026, 10, 2, 13, 0, tzinfo=TZ)
                ),
            ):
                result = await run_registration_notifications(
                    NOW,
                    state,
                    AsyncMock(return_value=123),
                    source_state_path=source,
                    translation_path=root / "translations.json",
                )

            saved = state.read()

        self.assertEqual(result, "stale_source")
        self.assertEqual(saved["baseline"], {})

    async def test_stale_source_never_mutates_lifecycle_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = RegistrationNotificationState(root / "notify.json")
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")

            with patch(
                "telegrambot.event_registration_notifications."
                "convega_snapshot_observed_at",
                new=AsyncMock(
                    return_value=datetime(2026, 10, 1, 12, 47, tzinfo=TZ)
                ),
            ):
                result = await run_registration_notifications(
                    NOW,
                    state,
                    AsyncMock(return_value=123),
                    source_state_path=source,
                    translation_path=root / "translations.json",
                )

            saved = state.read()

        self.assertEqual(result, "stale_source")
        self.assertEqual(saved["baseline"], {})


if __name__ == "__main__":
    unittest.main()
