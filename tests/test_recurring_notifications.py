import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.recurring_notifications import (
    RecurringNotificationError,
    _empty_state,
    build_message,
    collect_changes,
    load_state,
    semantic_diff,
    sync_recurring_notifications,
)
from telegrambot.telegram import TelegramError


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 18, 16, 30, tzinfo=MADRID)


def chess(**changes):
    value = {
        "observed_at": NOW.isoformat(),
        "source_url": "https://ajedrezdamadeguardamar.com/cuotas/",
        "days": ["tuesday", "thursday"],
        "start_time": "16:00",
        "end_time": "20:00",
        "level_from": "INICIACIÓN",
        "level_to": "AVANZADO",
    }
    value.update(changes)
    return value


def literary(**changes):
    value = {
        "observed_at": NOW.isoformat(),
        "source_url": (
            "https://www.bibliotecaspublicas.es/guardamardelsegura/"
            "actividades-programas/Tertulia-Literaria-de-Guardamar.html"
        ),
        "day": "tuesday",
        "start_time": "11:00",
        "end_time": "13:00",
        "venue": "library_auditorium",
    }
    value.update(changes)
    return value


def group(key, schedules, start_date=None, end_date=None):
    return {
        "key": key,
        "schedules": schedules,
        "start_date": start_date,
        "end_date": end_date,
    }


def dinamizacion(**changes):
    value = {
        "observed_at": NOW.isoformat(),
        "season": "2026/27",
        "campaign_url": (
            "https://www.guardamardelsegura.es/2026/09/07/"
            "programa-dinamizacion-social-2026-2027/"
        ),
        "form_url": "https://docs.google.com/forms/d/e/test/viewform",
        "registration_start": "2026-09-09",
        "registration_end": "2026-09-16",
        "registration_until_full": True,
        "resident_priority": True,
        "groups": [
            group(
                "mindful_movement",
                ["Пн/Ср · 11:15–12:15", "Пн/Ср · 12:15–13:15"],
            ),
            group(
                "mobile",
                ["Вт/Чт · 09:30–10:30", "Вт/Чт · 10:30–11:30"],
                "2026-11-10",
            ),
        ],
    }
    value.update(changes)
    return value


class RecurringNotificationDiffTests(unittest.TestCase):
    def test_first_observation_is_silent_baseline(self):
        state = collect_changes(
            {
                "chess": chess(),
                "literary_group": literary(),
                "dinamizacion": dinamizacion(),
            },
            _empty_state(),
            NOW.date(),
        )
        self.assertIsNone(state["pending"])
        self.assertEqual(
            set(state["snapshots"]),
            {"chess", "literary_group", "dinamizacion"},
        )

    def test_chess_and_literary_schedule_changes_are_semantic(self):
        chess_events = semantic_diff(
            "chess",
            chess(),
            chess(start_time="17:00", end_time="21:00"),
        )
        literary_events = semantic_diff(
            "literary_group",
            literary(),
            literary(start_time="10:30"),
        )
        self.assertEqual([event["type"] for event in chess_events], ["schedule"])
        self.assertEqual(
            [event["type"] for event in literary_events],
            ["schedule"],
        )

    def test_dinamizacion_addition_and_changes_are_batched(self):
        old = dinamizacion()
        changed_groups = list(old["groups"]) + [
            group("textile_painting", ["Пт · 16:30–18:30"])
        ]
        current = dinamizacion(
            registration_end="2026-09-20",
            groups=changed_groups,
        )
        events = semantic_diff("dinamizacion", old, current)
        self.assertEqual(
            [event["type"] for event in events],
            ["registration_window", "new_group"],
        )

    def test_group_disappearance_alone_is_silent(self):
        old = dinamizacion()
        current = dinamizacion(groups=[old["groups"][0]])
        self.assertEqual(semantic_diff("dinamizacion", old, current), [])

    def test_new_campaign_is_one_program_event_not_group_spam(self):
        current = dinamizacion(
            season="2027/28",
            campaign_url=(
                "https://www.guardamardelsegura.es/2027/09/07/"
                "programa-dinamizacion-social-2027-2028/"
            ),
        )
        events = semantic_diff("dinamizacion", dinamizacion(), current)
        self.assertEqual([event["type"] for event in events], ["new_program"])

    def test_source_observation_timestamp_churn_is_silent(self):
        later = NOW.replace(hour=17).isoformat()
        self.assertEqual(
            semantic_diff("chess", chess(), chess(observed_at=later)),
            [],
        )

    def test_missing_current_source_preserves_baseline_without_notification(self):
        initial = collect_changes(
            {"chess": chess(), "literary_group": literary()},
            _empty_state(),
            NOW.date(),
        )
        next_state = collect_changes(
            {"chess": chess()},
            initial,
            NOW.date(),
        )
        self.assertIsNone(next_state["pending"])
        self.assertIn("literary_group", next_state["snapshots"])


class RecurringNotificationMessageTests(unittest.TestCase):
    def test_message_batches_changes_and_links_to_cards(self):
        pending = {
            "created_date": NOW.date().isoformat(),
            "events": [
                {
                    "key": "chess",
                    "type": "schedule",
                    "start_time": "17:00",
                    "end_time": "21:00",
                },
                {
                    "key": "dinamizacion",
                    "type": "new_group",
                    "group": "textile_painting",
                    "schedules": ["Пт · 16:30–18:30"],
                    "start_date": None,
                    "end_date": None,
                },
            ],
        }
        message = build_message(
            pending,
            "-100123",
            {"chess": 501, "dinamizacion": 503},
            {"chess": chess(), "dinamizacion": dinamizacion()},
        )
        self.assertIn("Занятия и секции · изменения", message)
        self.assertIn("https://t.me/c/123/501", message)
        self.assertIn("https://t.me/c/123/503", message)
        self.assertIn("Роспись по ткани", message)
        self.assertLessEqual(len(message), 4096)


class RecurringNotificationDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_baseline_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notifications.json"
            send = AsyncMock()
            with (
                patch.dict(
                    "os.environ",
                    {"RECURRING_NOTIFICATION_STATE_PATH": str(path)},
                    clear=False,
                ),
                patch(
                    "telegrambot.recurring_notifications.send_message",
                    new=send,
                ),
            ):
                result = await sync_recurring_notifications(
                    "token",
                    "-100123",
                    {"chess": chess()},
                    {"chess": 501},
                    NOW,
                )
            self.assertEqual(result, "baseline")
            send.assert_not_awaited()
            self.assertIn("chess", load_state(path)["snapshots"])

    async def test_change_marks_uncertain_before_send_then_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notifications.json"
            baseline = _empty_state()
            baseline["snapshots"] = {"chess": chess()}
            path.write_text(
                json.dumps(baseline, ensure_ascii=False),
                encoding="utf-8",
            )

            async def accepted(*args, **kwargs):
                during = load_state(path)
                self.assertEqual(during["delivery_state"], "uncertain")
                self.assertIsNotNone(during["pending"])
                return 901

            with (
                patch.dict(
                    "os.environ",
                    {"RECURRING_NOTIFICATION_STATE_PATH": str(path)},
                    clear=False,
                ),
                patch(
                    "telegrambot.recurring_notifications.send_message",
                    new=AsyncMock(side_effect=accepted),
                ),
            ):
                result = await sync_recurring_notifications(
                    "token",
                    "-100123",
                    {"chess": chess(start_time="17:00")},
                    {"chess": 501},
                    NOW,
                )

            self.assertEqual(result, "published")
            saved = load_state(path)
            self.assertEqual(saved["delivery_state"], "idle")
            self.assertIsNone(saved["pending"])
            self.assertEqual(saved["last_message_id"], 901)

    async def test_ambiguous_failure_stays_uncertain_and_blocks_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notifications.json"
            baseline = _empty_state()
            baseline["snapshots"] = {"chess": chess()}
            path.write_text(
                json.dumps(baseline, ensure_ascii=False),
                encoding="utf-8",
            )
            error = TelegramError("timeout", retryable=True, code="TIMEOUT")
            send = AsyncMock(side_effect=error)
            with (
                patch.dict(
                    "os.environ",
                    {"RECURRING_NOTIFICATION_STATE_PATH": str(path)},
                    clear=False,
                ),
                patch(
                    "telegrambot.recurring_notifications.send_message",
                    new=send,
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_recurring_notifications(
                        "token",
                        "-100123",
                        {"chess": chess(start_time="17:00")},
                        {"chess": 501},
                        NOW,
                    )
                self.assertEqual(load_state(path)["delivery_state"], "uncertain")
                with self.assertRaises(RecurringNotificationError):
                    await sync_recurring_notifications(
                        "token",
                        "-100123",
                        {"chess": chess(start_time="17:00")},
                        {"chess": 501},
                        NOW,
                    )
            self.assertEqual(send.await_count, 1)

    async def test_rate_limit_keeps_pending_but_restores_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notifications.json"
            baseline = _empty_state()
            baseline["snapshots"] = {"chess": chess()}
            path.write_text(
                json.dumps(baseline, ensure_ascii=False),
                encoding="utf-8",
            )
            error = TelegramError(
                "rate limited",
                retryable=True,
                status=429,
                code="HTTP-429",
            )
            with (
                patch.dict(
                    "os.environ",
                    {"RECURRING_NOTIFICATION_STATE_PATH": str(path)},
                    clear=False,
                ),
                patch(
                    "telegrambot.recurring_notifications.send_message",
                    new=AsyncMock(side_effect=error),
                ),
            ):
                with self.assertRaises(TelegramError):
                    await sync_recurring_notifications(
                        "token",
                        "-100123",
                        {"chess": chess(start_time="17:00")},
                        {"chess": 501},
                        NOW,
                    )
            saved = load_state(path)
            self.assertEqual(saved["delivery_state"], "idle")
            self.assertIsNotNone(saved["pending"])


if __name__ == "__main__":
    unittest.main()
