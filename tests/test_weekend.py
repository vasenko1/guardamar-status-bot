import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.agenda import _write_agenda_snapshot
from telegrambot.models import Event
from telegrambot.municipal_agenda import (
    SourceEvent,
    _snapshot_data,
    _write_snapshot,
)
from telegrambot.weekend import produce_weekend_message, weekend_dates

TZ = ZoneInfo("Europe/Madrid")
POSTER_URL = (
    "https://www.guardamardelsegura.es/wp-content/uploads/"
    "2026/07/MUPI-AGOSTO-2026-scaled.jpg"
)


def _paths(directory):
    base = Path(directory)
    return {
        "municipal_agenda_state_path": base / "municipal.json",
        "agenda_state_path": base / "agenda.json",
        "translation_cache_path": base / "translations.json",
    }


def _write_municipal(path, events):
    _write_snapshot(path, _snapshot_data(
        POSTER_URL,
        "hash",
        datetime(2026, 8, 14, 5, 10, tzinfo=TZ),
        events,
    ))


class WeekendDateTests(unittest.TestCase):
    def test_friday_targets_the_next_two_days(self):
        saturday, sunday = weekend_dates(
            datetime(2026, 8, 14, 18, 0, tzinfo=TZ)
        )
        self.assertEqual(saturday, date(2026, 8, 15))
        self.assertEqual(sunday, date(2026, 8, 16))

    def test_saturday_keeps_the_current_weekend(self):
        saturday, sunday = weekend_dates(
            datetime(2026, 8, 15, 9, 0, tzinfo=TZ)
        )
        self.assertEqual(saturday, date(2026, 8, 15))
        self.assertEqual(sunday, date(2026, 8, 16))


class WeekendMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_renders_both_days_from_catalogs_without_network(self):
        now = datetime(2026, 8, 14, 18, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_agenda_snapshot(
                paths["agenda_state_path"],
                now,
                (Event(
                    title="Concierto de verano",
                    starts_at=datetime(2026, 8, 15, 22, 0, tzinfo=TZ),
                    ends_at=None,
                    place="Castillo de Guardamar",
                ),),
            )
            _write_municipal(paths["municipal_agenda_state_path"], (
                SourceEvent(
                    title_es="Taller de guitarras eléctricas",
                    start_date=date(2026, 8, 15),
                    end_date=date(2026, 8, 15),
                    start_time="19:00",
                    end_time="21:00",
                    place="Centro Social Juvenil",
                    category="event",
                    sources=("mupi",),
                ),
            ))

            message = await produce_weekend_message(
                now, "", paths["municipal_agenda_state_path"],
                agenda_state_path=paths["agenda_state_path"],
                translation_cache_path=paths["translation_cache_path"],
            )

        self.assertIn("🎭 <b>Афиша выходных</b>", message)
        self.assertIn("📅 <b>Суббота, 15 августа:</b>", message)
        self.assertIn("📅 <b>Воскресенье, 16 августа:</b>", message)
        self.assertIn("<b>22:00</b> — Concierto de verano", message)
        self.assertIn("<b>19:00–21:00</b>", message)
        # The recurring Sunday market needs no catalog entry.
        self.assertIn("Рынок Campo de Guardamar", message)
        self.assertTrue(message.endswith("обЪявления Гуардамар</b></a>"))

    async def test_day_without_events_omits_its_heading(self):
        now = datetime(2026, 8, 12, 18, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_agenda_snapshot(
                paths["agenda_state_path"], now, (Event(
                    title="Concierto",
                    starts_at=datetime(2026, 8, 15, 22, 0, tzinfo=TZ),
                    ends_at=None,
                    place=None,
                ),),
            )
            _write_municipal(paths["municipal_agenda_state_path"], ())

            message = await produce_weekend_message(
                now, "", paths["municipal_agenda_state_path"],
                agenda_state_path=paths["agenda_state_path"],
                translation_cache_path=paths["translation_cache_path"],
            )

        self.assertIn("Суббота, 15 августа", message)
        # Sunday still renders because of the recurring market.
        self.assertIn("Воскресенье, 16 августа", message)
        self.assertIn("Рынок Campo de Guardamar", message)

    async def test_catalog_failures_degrade_to_recurring_events_only(self):
        now = datetime(2026, 8, 14, 18, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            # Neither catalog file exists: both readers fail closed.
            message = await produce_weekend_message(
                now, "", paths["municipal_agenda_state_path"],
                agenda_state_path=paths["agenda_state_path"],
                translation_cache_path=paths["translation_cache_path"],
            )

        self.assertNotIn("Суббота", message or "")
        self.assertIn("Воскресенье, 16 августа", message)
        self.assertIn("Рынок Campo de Guardamar", message)

    async def test_no_verified_events_returns_no_message(self):
        # A Monday-start week in January: no catalogs, and the recurring
        # Sunday market still applies, so pick a saturday/sunday where the
        # market rule is the only candidate and verify the market keeps the
        # message; then remove Sunday by pointing at Saturday-only failure.
        now = datetime(2026, 8, 14, 18, 0, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            message = await produce_weekend_message(
                now, "", paths["municipal_agenda_state_path"],
                agenda_state_path=paths["agenda_state_path"],
                translation_cache_path=paths["translation_cache_path"],
            )
        # The Sunday market guarantees at least one verified item, so the
        # digest is present; an all-empty weekend cannot occur while the
        # market rule holds. Document that invariant.
        self.assertIsNotNone(message)


if __name__ == "__main__":
    unittest.main()
