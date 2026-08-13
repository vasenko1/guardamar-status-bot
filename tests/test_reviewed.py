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
                reviewed_translations(_write(directory, data))

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
            for index, (data, read) in enumerate((
                (bad_event, lambda p: reviewed_poster("poster.jpg", p)),
                (bad_rule, schedule_rules),
                (no_set, schedule_rules),
            )):
                path = Path(directory) / f"case{index}.json"
                path.write_text(json.dumps(data), "utf-8")
                with self.assertRaises(ReviewedDataError):
                    read(path)

    def test_rejects_shaped_but_impossible_times(self):
        for value in ("99:99", "88:88", "24:00", "12:60"):
            data = self._base()
            data["schedules"] = [{
                "match": ["x"],
                "requires": {"start_time": value},
                "set": {"place": "Casa"},
            }]
            with tempfile.TemporaryDirectory() as directory:
                with self.subTest(value=value):
                    with self.assertRaises(ReviewedDataError):
                        schedule_rules(_write(directory, data))

    def test_rejects_wrongly_typed_optional_event_fields(self):
        cases = (
            {"ticket_price_cents": True},
            {"capacity_limited": "false"},
            {"participation_note": 123},
            {"registration_contact": []},
        )
        for extra in cases:
            data = self._base()
            data["posters"] = {"p.jpg": {"upload_path": "/u/", "events": [{
                "title_es": "X", "start_date": "2026-08-01",
                "end_date": "2026-08-01", "category": "event", **extra,
            }]}}
            with tempfile.TemporaryDirectory() as directory:
                with self.subTest(field=next(iter(extra))):
                    with self.assertRaises(ReviewedDataError):
                        reviewed_poster("p.jpg", _write(directory, data))

    def test_rejects_a_misspelled_key_at_every_object_level(self):
        top_level = self._base()
        top_level["postrs"] = {}
        poster_level = self._base()
        poster_level["posters"] = {"p.jpg": {
            "upload_path": "/u/",
            # A typo here previously produced a silently empty filter.
            "drop_title": [["ajedrez"]],
            "events": [],
        }}
        event_level = self._base()
        event_level["posters"] = {"p.jpg": {"upload_path": "/u/", "events": [{
            "title_es": "X", "start_date": "2026-08-01",
            "end_date": "2026-08-01", "category": "event", "plaice": "Casa",
        }]}}
        rule_level = self._base()
        rule_level["schedules"] = [{
            "match": ["x"], "requiers": {}, "set": {"place": "Casa"},
        }]

        cases = (
            ("top level", top_level, lambda p: reviewed_translations(p)),
            ("poster", poster_level, lambda p: reviewed_poster("p.jpg", p)),
            ("event", event_level, lambda p: reviewed_poster("p.jpg", p)),
            ("rule", rule_level, schedule_rules),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, (label, data, read) in enumerate(cases):
                path = Path(directory) / f"unknown{index}.json"
                path.write_text(json.dumps(data), "utf-8")
                with self.subTest(level=label):
                    with self.assertRaises(ReviewedDataError):
                        read(path)

    def test_rejects_substring_terms_that_would_match_everything(self):
        # A blank or one-character substring selects nearly every title:
        # in a drop clause it empties the event section, in a match term
        # it rewrites every event.
        for term in (" ", "", "x", "  a  "):
            drop = self._base()
            drop["posters"] = {"p.jpg": {
                "upload_path": "/u/", "drop_titles": [[term]], "events": [],
            }}
            rule = self._base()
            rule["schedules"] = [{
                "match": [term],
                "requires": {"start_time": "18:00"},
                "set": {"place": "Casa"},
            }]
            with tempfile.TemporaryDirectory() as directory:
                with self.subTest(term=repr(term)):
                    with self.assertRaises(ReviewedDataError):
                        reviewed_poster("p.jpg", _write(directory, drop))
                    path = Path(directory) / "rule.json"
                    path.write_text(json.dumps(rule), "utf-8")
                    with self.assertRaises(ReviewedDataError):
                        schedule_rules(path)

    def test_rejects_a_rule_without_an_explicit_guard(self):
        data = self._base()
        data["schedules"] = [{"match": ["concierto"], "set": {"place": "X"}}]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReviewedDataError):
                schedule_rules(_write(directory, data))

    def test_rejects_hours_fighting_weekday_windows(self):
        data = self._base()
        data["schedules"] = [{
            "match": ["concierto"],
            "requires": {"start_time": "09:00"},
            "weekday_windows": {
                "weekday": ["09:00", "20:00"],
                "saturday": None,
                "sunday": None,
            },
            # The window is applied last, so this would silently lose.
            "set": {"start_time": "11:00", "place": "Casa"},
        }]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReviewedDataError):
                schedule_rules(_write(directory, data))

    def test_rejects_an_event_that_ends_before_it_starts(self):
        data = self._base()
        data["posters"] = {"p.jpg": {"upload_path": "/u/", "events": [{
            "title_es": "X", "start_date": "2026-09-01",
            "end_date": "2026-08-01", "category": "event",
        }]}}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReviewedDataError):
                reviewed_poster("p.jpg", _write(directory, data))

    def test_rejects_duplicate_keys_that_json_would_resolve_silently(self):
        # The second block would win, discarding the first drop filter.
        raw = (
            '{"version":1,"translations":{},"schedules":[],'
            '"posters":{"p.jpg":{"upload_path":"/u/",'
            '"drop_titles":[["ajedrez"]],"events":[]}},'
            '"posters":{"p.jpg":{"upload_path":"/u/",'
            '"drop_titles":[],"events":[]}}}'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dup.json"
            path.write_text(raw, "utf-8")
            with self.assertRaises(ReviewedDataError):
                reviewed_poster("p.jpg", path)

    def test_one_bad_section_does_not_disable_the_others(self):
        data = self._base()
        data["translations"] = {"Not Normalized": "x"}
        data["posters"] = {"p.jpg": {
            "upload_path": "/u/",
            "drop_titles": [["ajedrez"]],
            "events": [],
        }}
        with tempfile.TemporaryDirectory() as directory:
            path = _write(directory, data)

            with self.assertRaises(ReviewedDataError):
                reviewed_translations(path)
            # The healthy sections keep working, so a translation typo
            # cannot switch off a poster's known-bad-OCR filter.
            self.assertEqual(
                reviewed_poster("p.jpg", path).drop_titles,
                (("ajedrez",),),
            )
            self.assertEqual(schedule_rules(path), ())


class FailClosedTests(unittest.TestCase):
    def test_rejected_data_never_republishes_known_bad_ocr(self):
        known_bad = SourceEvent(
            "Exposición del 24 Open de ajedrez Villa de Guardamar",
            date(2026, 8, 1), date(2026, 8, 8), None, None,
            "Polideportivo", "exhibition", ("mupi",),
        )
        corroborated = SourceEvent(
            "Concierto municipal", date(2026, 8, 1), date(2026, 8, 1),
            "20:00", None, "Plaza", "event", ("turismo_html", "mupi"),
        )
        text_only = SourceEvent(
            "Charla oficial", date(2026, 8, 1), date(2026, 8, 1),
            "18:00", None, "Casa", "event", ("turismo_html",),
        )
        with patch(
            "telegrambot.municipal_agenda.reviewed_poster",
            side_effect=ReviewedDataError("unrelated typo"),
        ):
            corrected = _apply_reviewed_corrections(
                (
                    "https://www.guardamardelsegura.es/wp-content/uploads/"
                    "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
                ),
                (known_bad, corroborated, text_only),
            )

        titles = [event.title_es for event in corrected]
        # Without a readable drop filter the poster-only row cannot be
        # told apart from a good one, so it is withheld rather than shown.
        self.assertNotIn(known_bad.title_es, titles)
        self.assertIn(corroborated.title_es, titles)
        self.assertIn(text_only.title_es, titles)

    def test_rejected_schedules_keep_uncorrected_source_facts(self):
        event = SourceEvent(
            "Rutas nocturnas: senderismo y dinámica grupal",
            date(2026, 8, 14), date(2026, 8, 14),
            "22:15", "00:15", None, "event",
        )
        with patch(
            "telegrambot.municipal_agenda.schedule_rules",
            side_effect=ReviewedDataError("bad file"),
        ):
            scheduled = _apply_reviewed_daily_schedules(
                (event,), date(2026, 8, 14)
            )

        self.assertEqual(scheduled, (event,))

    def test_data_path_ships_inside_the_package(self):
        self.assertEqual(DATA_PATH.name, "reviewed.json")
        self.assertTrue(DATA_PATH.exists())


if __name__ == "__main__":
    unittest.main()
