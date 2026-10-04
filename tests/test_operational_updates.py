import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.models import BeachStatus, Warning
from telegrambot.operational_updates import (
    OperationalUpdateState,
    OperationalUpdateStateError,
    build_beach_message,
    build_update_message,
    clear_beach_ready,
    finalize_delivery,
    miss_beach_sample,
    observe_beaches,
    observe_warnings,
    scheduled_run,
    seed_beaches,
    seed_warnings,
)

MADRID = ZoneInfo("Europe/Madrid")


def _status(flags, jellyfish=None, minute=0):
    jellyfish = jellyfish or {}
    return BeachStatus(
        flag_color=None,
        sea_temperature_c=None,
        source_date=date(2026, 8, 7),
        nearby_flags=tuple(flags.items()),
        jellyfish_beaches=tuple(
            name for name, present in jellyfish.items() if present
        ),
        jellyfish_states=tuple(jellyfish.items()),
        updated_times=tuple(
            (name, time(11, minute)) for name in flags
        ),
    )


class ScheduleTests(unittest.TestCase):
    def test_july_beach_and_environment_keep_old_primary_windows(self):
        primary = scheduled_run(
            datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)
        )
        self.assertEqual(primary.beach_phase, 1)
        self.assertTrue(primary.check_environment)
        self.assertFalse(primary.check_aemet)

        confirmation = scheduled_run(
            datetime(2026, 8, 7, 11, 5, tzinfo=MADRID)
        )
        self.assertEqual(confirmation.beach_phase, 2)
        self.assertFalse(confirmation.check_environment)
        self.assertFalse(confirmation.check_aemet)

        final_confirmation = scheduled_run(
            datetime(2026, 8, 7, 11, 10, tzinfo=MADRID)
        )
        self.assertEqual(final_confirmation.beach_phase, 3)
        self.assertFalse(final_confirmation.check_environment)
        self.assertFalse(final_confirmation.check_aemet)

        aemet = scheduled_run(
            datetime(2026, 8, 7, 11, 51, tzinfo=MADRID)
        )
        self.assertIsNone(aemet.beach_phase)
        self.assertFalse(aemet.check_environment)
        self.assertTrue(aemet.check_aemet)

    def test_shoulder_and_winter_environment_cadence_is_preserved(self):
        june_primary = scheduled_run(
            datetime(2026, 6, 1, 12, 0, tzinfo=MADRID)
        )
        self.assertEqual(june_primary.beach_phase, 1)
        self.assertTrue(june_primary.check_environment)
        self.assertFalse(june_primary.check_aemet)

        june_recovery = scheduled_run(
            datetime(2026, 6, 1, 20, 0, tzinfo=MADRID)
        )
        self.assertIsNone(june_recovery.beach_phase)
        self.assertTrue(june_recovery.check_environment)
        self.assertFalse(june_recovery.check_aemet)

        september_primary = scheduled_run(
            datetime(2026, 9, 30, 14, 0, tzinfo=MADRID)
        )
        self.assertEqual(september_primary.beach_phase, 1)
        self.assertTrue(september_primary.check_environment)
        self.assertFalse(september_primary.check_aemet)

        october_primary = scheduled_run(
            datetime(2026, 10, 15, 14, 0, tzinfo=MADRID)
        )
        self.assertEqual(october_primary.beach_phase, 1)
        self.assertTrue(october_primary.check_environment)
        self.assertFalse(october_primary.check_aemet)

        october_environment = scheduled_run(
            datetime(2026, 10, 15, 15, 0, tzinfo=MADRID)
        )
        self.assertIsNone(october_environment.beach_phase)
        self.assertTrue(october_environment.check_environment)
        self.assertFalse(october_environment.check_aemet)

        after_window = scheduled_run(
            datetime(2026, 10, 16, 14, 0, tzinfo=MADRID)
        )
        self.assertIsNone(after_window.beach_phase)
        self.assertFalse(after_window.check_environment)
        self.assertFalse(after_window.check_aemet)

        winter = scheduled_run(
            datetime(2026, 12, 7, 11, 0, tzinfo=MADRID)
        )
        self.assertIsNone(winter.beach_phase)
        self.assertTrue(winter.check_environment)
        self.assertFalse(winter.check_aemet)

    def test_aemet_hourly_bounds_and_exact_minute(self):
        for hour in (7, 8, 12, 19, 23):
            with self.subTest(hour=hour):
                run = scheduled_run(
                    datetime(2026, 12, 7, hour, 51, tzinfo=MADRID)
                )
                self.assertTrue(run.check_aemet)
                self.assertFalse(run.check_environment)
                self.assertIsNone(run.beach_phase)

        for hour, minute in ((6, 51), (0, 51), (7, 50), (7, 52), (23, 50)):
            with self.subTest(hour=hour, minute=minute):
                self.assertFalse(
                    scheduled_run(
                        datetime(2026, 12, 7, hour, minute, tzinfo=MADRID)
                    ).check_aemet
                )


class BeachConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.state = OperationalUpdateState.empty("2026-08-07")
        seed_beaches(self.state, {
            "Centre": {"flag": "green", "jellyfish": False},
            "Roqueta": {"flag": "yellow", "jellyfish": False},
        })

    def test_first_sample_is_a_confirmed_initial_status(self):
        state = OperationalUpdateState.empty("2026-08-07")
        sample = _status({"Centre": "green"}, {"Centre": False})
        observe_beaches(state, sample, 1)
        self.assertEqual(state["beaches"], {})
        self.assertTrue(state["beach_pending"]["initial"])
        observe_beaches(state, sample, 2)
        self.assertTrue(state["beach_ready"][0]["initial"])
        clear_beach_ready(state)
        self.assertEqual(state["beaches"]["Centre"]["flag"], "green")

    def test_published_full_digest_can_seed_beach_baseline(self):
        state = OperationalUpdateState.empty("2026-08-07")
        seed_beaches(state, {
            "Centre": {"flag": "green", "jellyfish": False},
            "unknown": {"flag": "red", "jellyfish": True},
        })
        self.assertEqual(
            state["beaches"],
            {"Centre": {"flag": "green", "jellyfish": False}},
        )

    def test_green_to_yellow_requires_two_matching_samples(self):
        changed = _status(
            {"Centre": "yellow", "Roqueta": "yellow"},
            {"Centre": False, "Roqueta": False},
            1,
        )
        observe_beaches(self.state, changed, 1)
        self.assertEqual(self.state["beach_pending"]["stage"], 1)
        observe_beaches(self.state, changed, 2)
        self.assertIsNone(self.state["beach_pending"])
        self.assertEqual(self.state["beach_ready"][0]["new"], "yellow")
        self.assertEqual(self.state["beaches"]["Centre"]["flag"], "green")
        clear_beach_ready(self.state)
        self.assertEqual(self.state["beaches"]["Centre"]["flag"], "yellow")

    def test_new_state_at_second_sample_gets_one_final_confirmation(self):
        observe_beaches(
            self.state,
            _status({"Centre": "yellow", "Roqueta": "yellow"}, minute=1),
            1,
        )
        observe_beaches(
            self.state,
            _status({"Centre": "red", "Roqueta": "yellow"}, minute=5),
            2,
        )
        self.assertEqual(self.state["beach_pending"]["stage"], 2)
        self.assertEqual(
            self.state["beach_pending"]["candidates"][0]["new"], "red"
        )
        observe_beaches(
            self.state,
            _status({"Centre": "red", "Roqueta": "yellow"}, minute=10),
            3,
        )
        self.assertEqual(self.state["beach_ready"][0]["new"], "red")

    def test_third_different_state_is_not_published(self):
        observe_beaches(
            self.state,
            _status({"Centre": "yellow", "Roqueta": "yellow"}, minute=1),
            1,
        )
        observe_beaches(
            self.state,
            _status({"Centre": "red", "Roqueta": "yellow"}, minute=5),
            2,
        )
        observe_beaches(
            self.state,
            _status({"Centre": "green", "Roqueta": "yellow"}, minute=10),
            3,
        )
        self.assertEqual(self.state["beach_ready"], [])
        self.assertEqual(self.state["beaches"]["Centre"]["flag"], "green")

    def test_missing_second_sample_discards_candidate(self):
        observe_beaches(
            self.state,
            _status({"Centre": "yellow", "Roqueta": "yellow"}, minute=1),
            1,
        )
        miss_beach_sample(self.state, 2)
        self.assertIsNone(self.state["beach_pending"])
        self.assertEqual(self.state["beach_ready"], [])

    def test_missing_third_sample_keeps_already_confirmed_changes(self):
        observe_beaches(
            self.state,
            _status(
                {"Centre": "yellow", "Roqueta": "yellow"}, minute=1
            ),
            1,
        )
        observe_beaches(
            self.state,
            _status(
                {"Centre": "yellow", "Roqueta": "red"}, minute=5
            ),
            2,
        )
        self.assertEqual(self.state["beach_pending"]["stage"], 2)
        miss_beach_sample(self.state, 3)
        self.assertIsNone(self.state["beach_pending"])
        self.assertEqual(
            self.state["beach_ready"],
            [{
                "beach": "Centre",
                "field": "flag",
                "old": "green",
                "new": "yellow",
            }],
        )

    def test_first_positive_jellyfish_value_is_confirmed(self):
        state = OperationalUpdateState.empty("2026-08-07")
        seed_beaches(state, {"Centre": {"flag": "green", "jellyfish": None}})
        positive = _status({"Centre": "green"}, {"Centre": True})
        observe_beaches(state, positive, 1)
        self.assertEqual(
            state["beach_pending"]["candidates"][0]["field"],
            "jellyfish",
        )
        observe_beaches(state, positive, 2)
        self.assertTrue(state["beach_ready"][0]["new"])

    def test_initial_status_has_no_change_arrow(self):
        state = OperationalUpdateState.empty("2026-08-07")
        state["beach_ready"] = [{
            "beach": "Roqueta",
            "field": "flag",
            "old": None,
            "new": "red",
            "initial": True,
        }]
        message = build_beach_message(
            state, datetime(2026, 8, 7, 13, 5, tzinfo=MADRID)
        )
        self.assertIn("<b>Пляжи Guardamar:</b>", message)
        self.assertIn("• Roqueta: 🔴", message)
        self.assertNotIn("→", message)


class WarningChangeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)
        self.warning = Warning(
            event="Tormentas",
            level="yellow",
            starts_at=self.now + timedelta(hours=2),
            ends_at=self.now + timedelta(hours=8),
            probability="40–70%",
        )
        self.state = OperationalUpdateState.empty("2026-08-07")
        seed_warnings(self.state, (self.warning,))

    def test_unchanged_warning_does_not_notify(self):
        observe_warnings(self.state, (self.warning,), self.now)
        self.assertIsNone(self.state["warning_ready"])

    def test_level_change_produces_full_current_warning_without_cancellation(self):
        changed = Warning(
            **{**self.warning.__dict__, "level": "orange"}
        )
        observe_warnings(self.state, (changed,), self.now)
        self.assertEqual(len(self.state["warning_ready"]["current"]), 1)
        self.assertEqual(self.state["warning_ready"]["cancelled"], [])

    def test_natural_expiry_is_silent(self):
        after = self.warning.ends_at + timedelta(minutes=1)
        observe_warnings(self.state, (), after)
        self.assertIsNone(self.state["warning_ready"])
        self.assertEqual(self.state["warnings"], [])


    def test_refetch_clears_undelivered_warning_after_natural_expiry(self):
        changed = Warning(
            **{**self.warning.__dict__, "level": "orange"}
        )
        observe_warnings(self.state, (changed,), self.now)
        self.assertIsNotNone(self.state["warning_ready"])

        after = self.warning.ends_at + timedelta(minutes=1)
        observe_warnings(self.state, (), after)

        self.assertIsNone(self.state["warning_ready"])
        self.assertEqual(self.state["warnings"], [])

    def test_refetch_replaces_undelivered_warning_with_latest_cap(self):
        orange = Warning(
            **{**self.warning.__dict__, "level": "orange"}
        )
        red = Warning(
            **{**self.warning.__dict__, "level": "red"}
        )
        observe_warnings(self.state, (orange,), self.now)
        observe_warnings(self.state, (red,), self.now + timedelta(hours=1))

        self.assertEqual(
            self.state["warning_ready"]["current"][0]["level"], "red"
        )

    def test_aemet_finalize_does_not_mutate_beach_ready_state(self):
        changed = Warning(
            **{**self.warning.__dict__, "level": "orange"}
        )
        self.state["beach_ready"] = [{
            "beach": "Centre",
            "field": "flag",
            "old": "green",
            "new": "yellow",
        }]
        observe_warnings(self.state, (changed,), self.now)

        finalize_delivery(self.state)

        self.assertEqual(len(self.state["beach_ready"]), 1)
        self.assertIsNone(self.state["warning_ready"])
        self.assertEqual(self.state["warnings"][0]["level"], "orange")

    def test_early_cancellation_notifies(self):
        observe_warnings(self.state, (), self.now)
        self.assertEqual(len(self.state["warning_ready"]["cancelled"]), 1)

    def test_same_named_remaining_interval_does_not_hide_cancellation(self):
        tomorrow = Warning(
            **{
                **self.warning.__dict__,
                "starts_at": self.warning.starts_at + timedelta(days=1),
                "ends_at": self.warning.ends_at + timedelta(days=1),
            }
        )
        state = OperationalUpdateState.empty("2026-08-07")
        seed_warnings(state, (self.warning, tomorrow))
        observe_warnings(state, (self.warning,), self.now)
        self.assertEqual(len(state["warning_ready"]["cancelled"]), 1)
        self.assertEqual(
            state["warning_ready"]["cancelled"][0]["starts_at"],
            tomorrow.starts_at.isoformat(),
        )


class StateAndMessageTests(unittest.TestCase):
    def test_warning_cancellations_precede_complete_current_status(self):
        now = datetime(2026, 9, 8, 16, 0, tzinfo=MADRID)
        state = OperationalUpdateState.empty("2026-09-08")
        active = Warning(
            event="Temperaturas máximas",
            level="yellow",
            starts_at=now - timedelta(hours=3),
            ends_at=now + timedelta(hours=5),
            probability="40–70%",
        )
        cancelled = (
            Warning(
                event="Tormentas",
                level="orange",
                starts_at=now + timedelta(days=1),
                ends_at=now + timedelta(days=1, hours=8),
                probability="40–70%",
            ),
            Warning(
                event="Lluvias",
                level="orange",
                starts_at=now + timedelta(days=1),
                ends_at=now + timedelta(days=1, hours=8),
                probability="40–70%",
            ),
        )
        state["warning_ready"] = {
            "current": [
                {
                    "event": active.event,
                    "level": active.level,
                    "starts_at": active.starts_at.isoformat(),
                    "ends_at": active.ends_at.isoformat(),
                    "description": None,
                    "probability": active.probability,
                }
            ],
            "cancelled": [
                {
                    "event": item.event,
                    "level": item.level,
                    "starts_at": item.starts_at.isoformat(),
                    "ends_at": item.ends_at.isoformat(),
                    "description": None,
                    "probability": item.probability,
                }
                for item in cancelled
            ],
        }

        message = build_update_message(state, now)

        self.assertIn(
            "✅ На завтра отменены предупреждения: грозы и сильный дождь.",
            message,
        )
        self.assertIn("<b>Сейчас действует:</b>", message)
        self.assertIn("Высокая температура", message)
        self.assertEqual(message.count("AEMET обновила предупреждения"), 1)
        self.assertEqual(message.count("Зона:"), 1)
        self.assertLess(message.index("✅"), message.index("Сейчас действует"))
        self.assertNotIn("Досрочно отменено", message)

    def test_all_cancelled_states_that_no_other_warning_is_active(self):
        now = datetime(2026, 9, 8, 16, 0, tzinfo=MADRID)
        state = OperationalUpdateState.empty("2026-09-08")
        state["warning_ready"] = {
            "current": [],
            "cancelled": [{
                "event": "Tormentas",
                "level": "orange",
                "starts_at": (now + timedelta(days=1)).isoformat(),
                "ends_at": (now + timedelta(days=1, hours=8)).isoformat(),
                "description": None,
                "probability": "40–70%",
            }],
        }

        message = build_update_message(state, now)

        self.assertIn(
            "✅ На завтра отменено предупреждение: грозы.", message
        )
        self.assertIn(
            "Других действующих предупреждений сейчас нет.", message
        )
        self.assertNotIn("Сейчас действует", message)

    def test_unknown_remaining_warning_does_not_claim_none_are_active(self):
        now = datetime(2026, 9, 8, 16, 0, tzinfo=MADRID)
        state = OperationalUpdateState.empty("2026-09-08")
        state["warning_ready"] = {
            "current": [{
                "event": "Aviso AEMET",
                "level": "yellow",
                "starts_at": now.isoformat(),
                "ends_at": (now + timedelta(hours=4)).isoformat(),
                "description": None,
                "probability": None,
            }],
            "cancelled": [{
                "event": "Tormentas",
                "level": "orange",
                "starts_at": (now + timedelta(days=1)).isoformat(),
                "ends_at": (now + timedelta(days=1, hours=8)).isoformat(),
                "description": None,
                "probability": "40–70%",
            }],
        }

        message = build_update_message(state, now)

        self.assertIn("отменено предупреждение: грозы", message)
        self.assertNotIn("Других действующих предупреждений", message)

    def test_state_round_trip_and_daily_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationalUpdateState(Path(directory) / "updates.json")
            now = datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)
            value = store.read(now)
            value["beaches"]["Centre"] = {"flag": "green"}
            store.write(value)
            self.assertEqual(
                store.read(now)["beaches"]["Centre"]["flag"], "green"
            )
            tomorrow = now + timedelta(days=1)
            self.assertEqual(store.read(tomorrow)["beaches"], {})

    def test_malformed_nested_pending_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationalUpdateState(Path(directory) / "updates.json")
            now = datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)
            value = store.empty("2026-08-07")
            value["beach_pending"] = {"stage": 1}
            store.write(value)
            with self.assertRaises(OperationalUpdateStateError):
                store.read(now)

    def test_beach_change_message_uses_latest_status_and_footer(self):
        state = OperationalUpdateState.empty("2026-08-07")
        state["beach_ready"] = [{
            "beach": "Centre",
            "field": "flag",
            "old": "green",
            "new": "yellow",
        }]
        state["beaches"] = {
            "Centre": {"flag": "green", "jellyfish": False},
            "Roqueta": {"flag": "red", "jellyfish": True},
        }
        state["latest_beaches"] = {
            "Centre": {"flag": "yellow", "jellyfish": False},
            "Roqueta": {"flag": "red", "jellyfish": True},
        }
        message = build_beach_message(
            state, datetime(2026, 8, 7, 13, 5, tzinfo=MADRID)
        )
        self.assertIn("Centre / Babilònia: 🟢 → 🟡", message)
        self.assertIn("🔴 Roqueta", message)
        self.assertIn("🪼 Медузы: Roqueta", message)
        self.assertIn("обЪявления Гуардамар", message)


if __name__ == "__main__":
    unittest.main()
