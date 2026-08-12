import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from telegrambot.municipal_agenda import (
    SourceEvent,
    _apply_reviewed_corrections,
    _apply_reviewed_daily_schedules,
)
from telegrambot.reviewed import (
    DATA_PATH,
    ReviewedDataError,
    _load,
    reviewed_poster,
    reviewed_translations,
    schedule_rules,
)


def _write(directory, payload) -> Path:
    path = Path(directory) / "reviewed.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    return path


class ShippedDataTests(unittest.TestCase):
    """The committed file must always validate: CI is the review gate."""

    def test_shipped_file_is_valid_and_complete(self):
        translations = reviewed_translations()
        rules = schedule_rules()

        self.assertTrue(translations)
        self.assertTrue(rules)
        self.assertIsNotNone(reviewed_poster("MUPI-AGOSTO-2026-scaled.jpg"))
        for rule in rules:
            self.assertTrue(rule.match)
            self.assertTrue(rule.set_fields)

    def test_shipped_poster_events_expire_by_date_not_by_deletion(self):
        poster = reviewed_poster("mupi-agosto-2026-scaled.jpg")
        for entry in poster.events:
            # Dates parse and are ordered; rendering still filters by day.
            self.assertLessEqual(
                date.fromisoformat(entry["start_date"]),
                date.fromisoformat(entry["end_date"]),
            )


class ValidationTests(unittest.TestCase):
    def _base(self):
        return {
            "version": 1,
            "translations": {},
            "posters": {},
            "schedules": [],
        }

    def test_rejects_wrong_version_and_broken_json(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReviewedDataError):
                _load(_write(directory, {"version": 2}))
            broken = Path(directory) / "broken.json"
            broken.write_text("not json", "utf-8")
            with self.assertRaises(ReviewedDataError):
                _load(broken)

    def test_rejects_unnormalized_translation_keys(self):
        data = self._base()
        data["translations"] = {"Ball D’Estiu": "Танцы"}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReviewedDataError):
                _load(_write(directory, data))

    def test_rejects_malformed_poster_events_and_rules(self):
        bad_event = self._base()
        bad_event["posters"] = {
            "poster.jpg": {
                "upload_path": "/uploads/",
                "events": [{"title_es": "x", "start_date": "no-date"}],
            }
        }
        bad_rule = self._base()
        bad_rule["schedules"] = [
            {"match": ["x"], "set": {"unknown_field": "y"}}
        ]
        no_set = self._base()
        no_set["schedules"] = [{"match": ["x"], "set": {}}]
        with tempfile.TemporaryDirectory() as directory:
            for index, data in enumerate((bad_event, bad_rule, no_set)):
                path = Path(directory) / f"case{index}.json"
                path.write_text(json.dumps(data), "utf-8")
                with self.assertRaises(ReviewedDataError):
                    _load(path)


class FailClosedTests(unittest.TestCase):
    def test_rejected_data_skips_corrections_without_crashing(self):
        event = SourceEvent(
            "Rutas nocturnas: senderismo y dinámica grupal",
            date(2026, 8, 14), date(2026, 8, 14),
            "22:15", "00:15", None, "event",
        )
        with patch(
            "telegrambot.municipal_agenda.reviewed_poster",
            side_effect=ReviewedDataError("bad file"),
        ):
            corrected = _apply_reviewed_corrections(
                (
                    "https://www.guardamardelsegura.es/wp-content/uploads/"
                    "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
                ),
                (event,),
            )
        with patch(
            "telegrambot.municipal_agenda.schedule_rules",
            side_effect=ReviewedDataError("bad file"),
        ):
            scheduled = _apply_reviewed_daily_schedules(
                (event,), date(2026, 8, 14)
            )

        # Source facts survive untouched; only the corrections are skipped.
        self.assertEqual(corrected, (event,))
        self.assertEqual(scheduled, (event,))

    def test_data_path_ships_inside_the_package(self):
        self.assertEqual(DATA_PATH.name, "reviewed.json")
        self.assertTrue(DATA_PATH.exists())


if __name__ == "__main__":
    unittest.main()
