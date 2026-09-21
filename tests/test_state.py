import json
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from telegrambot.models import BeachStatus
from telegrambot.state import PublicationState, StateError


class PublicationStateTests(unittest.TestCase):
    def _beach_status(self, local_day, names, color="green"):
        return BeachStatus(
            flag_color=color if "Centre" in names else None,
            sea_temperature_c=28 if "Centre" in names else None,
            source_date=local_day,
            nearby_flags=tuple((name, color) for name in names),
            jellyfish_states=tuple((name, False) for name in names),
            updated_times=tuple((name, time(10, 0)) for name in names),
        )

    def test_keeps_electricity_explanation_across_publication_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity.json"
            state = PublicationState(path)

            state.mark_electricity_published(date(2026, 8, 3))
            state.mark_electricity_explanation(321)
            state.mark_electricity_published(date(2026, 8, 4))

            self.assertTrue(state.is_published(date(2026, 8, 4)))
            self.assertEqual(
                state.electricity_explanation_message_id(), 321
            )

    def test_anchor_can_exist_before_first_table_is_published(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "electricity.json"
            state = PublicationState(path)

            state.mark_electricity_explanation(321)

            self.assertIsNone(state.last_successful_date())
            self.assertEqual(
                state.electricity_explanation_message_id(), 321
            )

    def test_stores_message_ids_needed_for_safe_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            state = PublicationState(path)
            local_day = date(2026, 7, 29)
            sent_at = datetime.fromisoformat(
                "2026-07-29T07:30:00+02:00"
            )

            state.mark_morning(local_day, 101, sent_at)
            state.mark_update_sent(
                local_day,
                202,
                BeachStatus(
                    flag_color="green",
                    sea_temperature_c=27,
                    nearby_flags=(("Centre", "green"),),
                    jellyfish_states=(("Centre", False),),
                ),
            )
            state.mark_morning_deleted(local_day)

            record = state.morning_record(local_day)
            self.assertEqual(record["morning_message_id"], 101)
            self.assertEqual(record["update_message_id"], 202)
            self.assertTrue(record["morning_deleted"])
            self.assertEqual(
                record["beach_baseline"],
                {"Centre": {"flag": "green", "jellyfish": False}},
            )

    def test_records_each_late_event_catalog_once_for_current_day(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            local_day = date(2026, 8, 7)
            state.mark_morning(
                local_day,
                101,
                datetime.fromisoformat("2026-08-07T07:30:00+02:00"),
            )

            self.assertFalse(
                state.event_catalog_sync_attempted(local_day, "municipal")
            )
            state.mark_event_catalog_sync_attempted(local_day, "municipal")
            state.mark_event_catalog_sync_attempted(local_day, "municipal")

            self.assertTrue(
                state.event_catalog_sync_attempted(local_day, "municipal")
            )
            self.assertEqual(
                state.morning_record(local_day)["event_catalog_sync"],
                ["municipal"],
            )

    def test_stores_morning_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / "delivery.json")
            local_day = date(2026, 8, 7)
            morning = datetime.fromisoformat("2026-08-07T07:30:00+02:00")
            base = datetime.fromisoformat("2026-08-06T00:00:00+00:00")
            state.mark_morning(local_day, 101, morning)

            state.mark_morning_environment(local_day, 2, base, cold_level=3)
            self.assertEqual(state.morning_environment(local_day), (2, 3, base))
            self.assertEqual(state.morning_environment(date(2026, 8, 8)), (None, None, None))
            state.mark_morning_environment(local_day, 2, base)
            self.assertEqual(state.morning_environment(local_day), (2, None, base))

    def test_unknown_state_structure_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            path.write_text(
                json.dumps(
                    {
                        "local_date": "2026-07-26",
                        "status": "failed",
                    }
                )
            )

            with self.assertRaises(StateError):
                PublicationState(path).last_successful_date()

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            path.write_text("not json")

            with self.assertRaises(StateError):
                PublicationState(path).last_successful_date()

    def test_unknown_state_shape_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            path.write_text(json.dumps({"unexpected": "value"}))

            with self.assertRaises(StateError):
                PublicationState(path).last_successful_date()

    def test_overlapping_run_fails_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            first = PublicationState(path)
            second = PublicationState(path)

            with first.exclusive_run():
                with self.assertRaises(StateError):
                    with second.exclusive_run():
                        self.fail("overlapping run acquired the lock")


if __name__ == "__main__":
    unittest.main()
