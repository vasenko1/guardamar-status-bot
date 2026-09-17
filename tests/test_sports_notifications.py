import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.branding import FOOTER
from telegrambot.sports_notifications import (
    SportsNotificationError,
    _empty_state,
    build_message,
    collect_changes,
    date_events,
    load_state,
    semantic_diff,
    sync_sports_notifications,
)
from telegrambot.telegram import TelegramError


MADRID = ZoneInfo("Europe/Madrid")


def activity(
    source_id=85509,
    *,
    key="judo",
    group_order=1,
    season_start="2026-10-01",
    season_end="2027-05-31",
    audience="2011–2020 г.р.",
    schedule="Ср и Пт · 17:00–18:30",
    venue="Palau Sant Jaume",
    registrations=None,
    registration_until_full=False,
    medical_certificate=True,
    group_may_change=False,
    racket_sports=False,
    independent=False,
    requires_companion=False,
    women_membership=False,
):
    if registrations is None:
        registrations = [{"start": "2026-09-01", "end": "2026-09-30"}]
    return {
        "source_id": source_id,
        "key": key,
        "activity_url": f"https://play.sporttia.com/activities/{source_id}",
        "season_start": season_start,
        "season_end": season_end,
        "group_order": group_order,
        "audience": audience,
        "schedule": schedule,
        "venue": venue,
        "registrations": registrations,
        "registration_until_full": registration_until_full,
        "medical_certificate": medical_certificate,
        "group_may_change": group_may_change,
        "racket_sports": racket_sports,
        "independent": independent,
        "requires_companion": requires_companion,
        "women_membership": women_membership,
    }


def catalog(moment, *items):
    return {
        "observed_at": moment.isoformat(),
        "activities": list(items),
    }


def active_state(previous, *, known_keys=("judo",)):
    state = _empty_state()
    state["catalog"] = previous
    state["known_keys"] = list(known_keys)
    state["launch_overview_done"] = True
    return state


class SportsNotificationDiffTests(unittest.TestCase):
    def test_first_fresh_observation_queues_launch_overview_not_fake_new_activity(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        current = catalog(moment, activity())

        result = collect_changes(current, _empty_state(), moment.date())

        self.assertEqual(result["pending"]["kind"], "launch")
        self.assertEqual(
            [event["type"] for event in result["pending"]["events"]],
            ["launch_registration"],
        )
        self.assertFalse(result["launch_overview_done"])
        self.assertEqual(result["known_keys"], ["judo"])

    def test_first_stale_observation_is_silent_and_waits_for_fresh_launch(self):
        old = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        current_day = date(2026, 9, 17)
        first = collect_changes(catalog(old, activity()), _empty_state(), current_day)
        self.assertIsNone(first["pending"])
        self.assertFalse(first["launch_overview_done"])

        fresh = datetime(2026, 9, 18, 16, 30, tzinfo=MADRID)
        second = collect_changes(
            catalog(fresh, activity()), first, fresh.date()
        )
        self.assertEqual(second["pending"]["kind"], "launch")

    def test_no_open_registration_finishes_silent_launch_baseline(self):
        moment = datetime(2026, 10, 2, 16, 30, tzinfo=MADRID)
        result = collect_changes(
            catalog(moment, activity()), _empty_state(), moment.date()
        )
        self.assertIsNone(result["pending"])
        self.assertTrue(result["launch_overview_done"])

    def test_row_reordering_and_removal_do_not_notify(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        first = activity(85509, group_order=1)
        second = activity(85510, group_order=2, schedule="Ср и Пт · 18:30–20:00")
        previous = catalog(moment, first, second)
        reordered = catalog(moment, second, first)
        removed = catalog(moment, first)

        self.assertEqual(semantic_diff(previous, reordered, ["judo"]), [])
        self.assertEqual(semantic_diff(previous, removed, ["judo"]), [])

    def test_new_activity_group_and_season_are_distinguished(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        previous = catalog(moment, activity())

        new_activity = activity(
            85508,
            key="deporte_plus",
            audience="2011–2017 г.р.",
            schedule="Вт и Чт · 19:30–21:00",
            venue="Complejo Deportivo Les Raboses",
        )
        diff = semantic_diff(
            previous,
            catalog(moment, activity(), new_activity),
            ["judo"],
        )
        self.assertEqual([event["type"] for event in diff], ["new_activity"])

        new_group = activity(
            85510,
            group_order=2,
            schedule="Ср и Пт · 18:30–20:00",
        )
        diff = semantic_diff(
            previous,
            catalog(moment, activity(), new_group),
            ["judo"],
        )
        self.assertEqual([event["type"] for event in diff], ["new_group"])

        new_season = activity(
            95509,
            season_start="2027-10-01",
            season_end="2028-05-31",
            registrations=[{"start": "2027-09-01", "end": "2027-09-30"}],
        )
        diff = semantic_diff(
            previous,
            catalog(moment, new_season),
            ["judo"],
        )
        self.assertEqual([event["type"] for event in diff], ["new_season"])

    def test_semantic_fields_create_material_events(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        previous_item = activity()
        changed = activity(
            schedule="Вт и Чт · 18:00–19:00",
            venue="Complejo Deportivo Les Raboses",
            audience="2012–2020 г.р.",
            registrations=[{"start": "2026-09-05", "end": "2026-10-05"}],
            registration_until_full=True,
            medical_certificate=False,
            requires_companion=True,
        )
        diff = semantic_diff(
            catalog(moment, previous_item),
            catalog(moment, changed),
            ["judo"],
        )
        self.assertEqual(
            {event["type"] for event in diff},
            {
                "registration_window",
                "schedule",
                "venue",
                "audience",
                "conditions",
                "until_full",
            },
        )

    def test_opening_and_three_day_deadline_events_are_deduplicated(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        current = catalog(
            moment,
            activity(
                registrations=[
                    {"start": "2026-09-17", "end": "2026-09-30"},
                    {"start": "2026-09-01", "end": "2026-09-20"},
                ]
            ),
        )
        events, ids = date_events(current, moment.date(), [])
        self.assertEqual(
            [event["type"] for event in events],
            ["registration_open", "deadline_reminder"],
        )
        again, again_ids = date_events(current, moment.date(), ids)
        self.assertEqual(again, [])
        self.assertEqual(again_ids, [])

    def test_stale_catalog_never_emits_date_trigger(self):
        baseline_moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        today = date(2026, 9, 17)
        item = activity(
            registrations=[{"start": "2026-09-17", "end": "2026-09-30"}]
        )
        previous = catalog(baseline_moment, item)
        state = active_state(previous)
        result = collect_changes(previous, state, today)
        self.assertIsNone(result["pending"])


class SportsNotificationMessageTests(unittest.TestCase):
    def test_launch_copy_is_explicitly_current_not_new(self):
        pending = {
            "created_date": "2026-09-17",
            "kind": "launch",
            "events": [
                {
                    "key": "judo",
                    "type": "launch_registration",
                    "group_order": 1,
                    "registrations": [
                        {"start": "2026-09-01", "end": "2026-09-30"}
                    ],
                }
            ],
            "date_event_ids": [],
            "marks_launch": True,
        }
        message = build_message(pending, "-100123", {"judo": 500})
        self.assertIn("Спорт · сейчас открыта запись", message)
        self.assertIn("Сейчас идёт запись", message)
        self.assertNotIn("новая муниципальная", message.casefold())
        self.assertIn("https://t.me/c/123/500", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertLessEqual(len(message), 4096)

    def test_change_message_batches_activity_events(self):
        pending = {
            "created_date": "2026-09-17",
            "kind": "changes",
            "events": [
                {
                    "key": "judo",
                    "type": "schedule",
                    "group_order": 1,
                    "value": "Вт и Чт · 18:00–19:00",
                },
                {
                    "key": "judo",
                    "type": "deadline_reminder",
                    "group_order": 1,
                    "start": "2026-09-01",
                    "end": "2026-09-20",
                },
            ],
            "date_event_ids": ["deadline:judo:2026-09-01:2026-09-20"],
            "marks_launch": False,
        }
        message = build_message(pending, "-100123", {"judo": 500})
        self.assertEqual(message.count("🥋"), 1)
        self.assertIn("новое расписание", message)
        self.assertIn("осталось 3 дня", message)
        self.assertEqual(message.count(FOOTER), 1)


class SportsNotificationDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_marks_uncertain_before_send_then_commits_success(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        current = catalog(moment, activity())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sports.json"

            async def accepted(*args, **kwargs):
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["delivery_state"], "uncertain")
                self.assertIsNotNone(saved["pending"])
                return 901

            with (
                patch.dict(
                    "os.environ",
                    {"SPORTS_NOTIFICATION_STATE_PATH": str(path)},
                    clear=False,
                ),
                patch(
                    "telegrambot.sports_notifications.send_message",
                    new=AsyncMock(side_effect=accepted),
                ) as send,
            ):
                result = await sync_sports_notifications(
                    "token", "-100123", current, {"judo": 500}, moment
                )

            self.assertEqual(result, "published")
            self.assertEqual(send.await_count, 1)
            saved = load_state(path)
            self.assertEqual(saved["delivery_state"], "idle")
            self.assertIsNone(saved["pending"])
            self.assertTrue(saved["launch_overview_done"])
            self.assertEqual(saved["last_message_id"], 901)

    async def test_http_429_restores_idle_and_keeps_pending_for_safe_retry(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        current = catalog(moment, activity())
        error = TelegramError(
            "rate limited", retryable=True, status=429, code="HTTP-429"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sports.json"
            with (
                patch.dict(
                    "os.environ",
                    {"SPORTS_NOTIFICATION_STATE_PATH": str(path)},
                    clear=False,
                ),
                patch(
                    "telegrambot.sports_notifications.send_message",
                    new=AsyncMock(side_effect=error),
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_sports_notifications(
                        "token", "-100123", current, {"judo": 500}, moment
                    )
            saved = load_state(path)
            self.assertEqual(saved["delivery_state"], "idle")
            self.assertIsNotNone(saved["pending"])
            self.assertFalse(saved["launch_overview_done"])

    async def test_ambiguous_failure_stays_uncertain_and_blocks_automatic_resend(self):
        moment = datetime(2026, 9, 17, 16, 30, tzinfo=MADRID)
        current = catalog(moment, activity())
        error = TelegramError(
            "timeout", retryable=True, code="TIMEOUT"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sports.json"
            send = AsyncMock(side_effect=error)
            with (
                patch.dict(
                    "os.environ",
                    {"SPORTS_NOTIFICATION_STATE_PATH": str(path)},
                    clear=False,
                ),
                patch(
                    "telegrambot.sports_notifications.send_message",
                    new=send,
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_sports_notifications(
                        "token", "-100123", current, {"judo": 500}, moment
                    )
                self.assertEqual(load_state(path)["delivery_state"], "uncertain")
                with self.assertRaises(SportsNotificationError):
                    await sync_sports_notifications(
                        "token", "-100123", current, {"judo": 500}, moment
                    )
            self.assertEqual(send.await_count, 1)

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sports.json"
            path.write_text(
                json.dumps({"version": 1, "delivery_state": "maybe"}),
                encoding="utf-8",
            )
            with self.assertRaises(SportsNotificationError):
                load_state(path)


if __name__ == "__main__":
    unittest.main()
