import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.models import BeachStatus, Warning
from telegrambot.operational_updates import (
    OperationalUpdateState,
    OperationalUpdateStateError,
    build_update_message,
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
    def test_july_primary_and_confirmation_windows(self):
        self.assertEqual(
            scheduled_run(datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)),
            scheduled_run(datetime(2026, 8, 7, 15, 0, tzinfo=MADRID)),
        )
        primary = scheduled_run(
            datetime(2026, 8, 7, 11, 0, tzinfo=MADRID)
        )
        self.assertEqual(primary.beach_phase, 1)
        self.assertTrue(primary.check_aemet)
        self.assertEqual(
            scheduled_run(
                datetime(2026, 8, 7, 11, 5, tzinfo=MADRID)
            ).beach_phase,
            2,
        )
        self.assertEqual(
            scheduled_run(
                datetime(2026, 8, 7, 11, 10, tzinfo=MADRID)
            ).beach_phase,
            3,
        )

    def test_shoulder_season_and_winter(self):
        june = scheduled_run(
            datetime(2026, 6, 20, 12, 0, tzinfo=MADRID)
        )
        self.assertEqual(june.beach_phase, 1)
        self.assertTrue(june.check_aemet)
        winter = scheduled_run(
            datetime(2026, 12, 7, 11, 0, tzinfo=MADRID)
        )
        self.assertIsNone(winter.beach_phase)
        self.assertTrue(winter.check_aemet)


class BeachConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.state = OperationalUpdateState.empty("2026-08-07")
        observe_beaches(
            self.state,
            _status(
                {"Centre": "green", "Roqueta": "yellow"},
                {"Centre": False, "Roqueta": False},
            ),
            1,
        )

    def test_first_sample_is_a_silent_baseline(self):
        self.assertIsNone(self.state["beach_pending"])
        self.assertEqual(self.state["beaches"]["Centre"]["flag"], "green")

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
        finalize_delivery(self.state)
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
        positive = _status({"Centre": "green"}, {"Centre": True})
        observe_beaches(state, positive, 1)
        self.assertEqual(
            state["beach_pending"]["candidates"][0]["field"],
            "jellyfish",
        )
        observe_beaches(state, positive, 2)
        self.assertTrue(state["beach_ready"][0]["new"])


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

    def test_combined_message_uses_latest_status_and_footer(self):
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
        message = build_update_message(
            state, datetime(2026, 8, 7, 13, 5, tzinfo=MADRID)
        )
        self.assertIn("Centre / Babilònia: 🟢 → 🟡", message)
        self.assertIn("🔴 Roqueta", message)
        self.assertIn("🪼 Медузы: Roqueta", message)
        self.assertIn("обЪявления Гуардамар", message)


if __name__ == "__main__":
    unittest.main()
