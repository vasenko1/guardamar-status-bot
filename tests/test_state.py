import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from telegrambot.state import PublicationState, StateError


class PublicationStateTests(unittest.TestCase):
    def test_stores_only_last_successful_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            state = PublicationState(path)

            state.mark_published(date(2026, 7, 26))

            self.assertEqual(
                json.loads(path.read_text()),
                {"last_successful_date": "2026-07-26"},
            )
            self.assertTrue(state.is_published(date(2026, 7, 26)))

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

    def test_reads_confirmed_success_from_previous_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            path.write_text(
                json.dumps(
                    {
                        "local_date": "2026-07-26",
                        "status": "success",
                        "updated_at": "2026-07-26T07:30:00+02:00",
                    }
                )
            )
            self.assertEqual(
                PublicationState(path).last_successful_date(),
                date(2026, 7, 26),
            )

    def test_stores_message_ids_needed_for_safe_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.json"
            state = PublicationState(path)
            local_day = date(2026, 7, 29)
            sent_at = datetime.fromisoformat(
                "2026-07-29T07:30:00+02:00"
            )

            state.mark_morning(local_day, 101, sent_at, "morning")
            state.mark_update_sent(local_day, 202)
            state.mark_morning_deleted(local_day)

            record = state.morning_record(local_day)
            self.assertEqual(record["morning_message_id"], 101)
            self.assertEqual(record["morning_message"], "morning")
            self.assertEqual(record["update_message_id"], 202)
            self.assertTrue(record["morning_deleted"])

    def test_ignores_unsuccessful_previous_attempt(self):
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

            self.assertIsNone(
                PublicationState(path).last_successful_date()
            )

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
