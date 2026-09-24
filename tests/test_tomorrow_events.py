import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.municipal_agenda import (
    SourceEvent,
    _snapshot_data,
    _write_snapshot,
)
from telegrambot.tomorrow_events import (
    TomorrowEventState,
    produce_tomorrow_event_publication,
    tomorrow_notice_due,
)


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 24, 19, 25, tzinfo=TZ)
IMAGE = (
    "https://guardamarturismo.com/wp-content/uploads/"
    "2026/09/fiestas-del-campo-2026-cartel.jpg"
)


def _paths(root):
    root = Path(root)
    return {
        "municipal_agenda_state_path": root / "municipal.json",
        "agenda_state_path": root / "agenda.json",
        "library_agenda_state_path": root / "library.json",
        "am_guardamar_state_path": root / "am.json",
        "facv_state_path": root / "facv.json",
        "pesca_cv_state_path": root / "pesca.json",
        "translation_cache_path": root / "translations.json",
    }


def _write_municipal(path, fetched_at, events):
    _write_snapshot(
        path,
        _snapshot_data("", "", fetched_at, tuple(events)),
    )


class TomorrowEventScheduleTests(unittest.TestCase):
    def test_sunday_through_thursday_are_due(self):
        for day in (20, 21, 22, 23, 24):
            self.assertTrue(tomorrow_notice_due(
                datetime(2026, 9, day, 19, 25, tzinfo=TZ)
            ))

    def test_friday_and_saturday_are_reserved_for_weekend_digest(self):
        self.assertFalse(tomorrow_notice_due(
            datetime(2026, 9, 25, 19, 25, tzinfo=TZ)
        ))
        self.assertFalse(tomorrow_notice_due(
            datetime(2026, 9, 26, 19, 25, tzinfo=TZ)
        ))


class TomorrowEventStateTests(unittest.TestCase):
    def test_uncertain_state_blocks_resend_until_operator_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tomorrow.json"
            state = TomorrowEventState(path)
            target = date(2026, 9, 25)

            state.mark_uncertain(target)

            self.assertEqual(state.status(target), "uncertain")
            self.assertIsNone(state.status(date(2026, 9, 26)))

    def test_sent_state_requires_and_keeps_message_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tomorrow.json"
            state = TomorrowEventState(path)
            target = date(2026, 9, 25)

            state.mark_uncertain(target)
            state.mark_sent(target, 321)

            self.assertEqual(state.status(target), "sent")
            self.assertIn('"message_id": 321', path.read_text(encoding="utf-8"))


class TomorrowEventPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_catalog_cannot_make_tomorrow_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_municipal(
                paths["municipal_agenda_state_path"],
                datetime(2026, 9, 23, 5, 10, tzinfo=TZ),
                [SourceEvent(
                    "Concierto",
                    date(2026, 9, 25),
                    date(2026, 9, 25),
                    "20:00",
                    None,
                    "Casa de Cultura",
                    "event",
                    ("turismo_html",),
                )],
            )
            publication = await produce_tomorrow_event_publication(
                NOW, **paths
            )

        self.assertIsNone(publication)

    async def test_continuing_range_is_silent_between_start_and_final_day(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_municipal(
                paths["municipal_agenda_state_path"],
                datetime(2026, 9, 24, 5, 10, tzinfo=TZ),
                [SourceEvent(
                    "Exposición",
                    date(2026, 9, 20),
                    date(2026, 9, 30),
                    None,
                    None,
                    "Biblioteca Municipal",
                    "exhibition",
                    ("turismo_html",),
                )],
            )
            publication = await produce_tomorrow_event_publication(
                NOW, **paths
            )

        self.assertIsNone(publication)

    async def test_range_start_is_eligible(self):
        now = datetime(2026, 9, 19, 19, 25, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_municipal(
                paths["municipal_agenda_state_path"],
                datetime(2026, 9, 19, 5, 10, tzinfo=TZ),
                [SourceEvent(
                    "Exposición",
                    date(2026, 9, 20),
                    date(2026, 9, 30),
                    None,
                    None,
                    "Biblioteca Municipal",
                    "exhibition",
                    ("turismo_html",),
                )],
            )
            publication = await produce_tomorrow_event_publication(
                now, **paths
            )

        self.assertIsNotNone(publication)
        self.assertEqual(publication.unit_count, 1)
        self.assertIn("Exposición", publication.message)

    async def test_range_final_day_is_eligible_and_labelled(self):
        now = datetime(2026, 9, 29, 19, 25, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_municipal(
                paths["municipal_agenda_state_path"],
                datetime(2026, 9, 29, 5, 10, tzinfo=TZ),
                [SourceEvent(
                    "Exposición",
                    date(2026, 9, 20),
                    date(2026, 9, 30),
                    None,
                    None,
                    "Biblioteca Municipal",
                    "exhibition",
                    ("turismo_html",),
                )],
            )
            publication = await produce_tomorrow_event_publication(
                now, **paths
            )

        self.assertIsNotNone(publication)
        self.assertIn("Последний день:", publication.message)

    async def test_programme_members_collapse_to_one_rich_unit_with_one_poster(self):
        events = [
            SourceEvent(
                "Entrada de bandas",
                date(2026, 9, 25),
                date(2026, 9, 25),
                "18:30",
                None,
                None,
                "event",
                ("turismo_programme",),
                programme_title="Fiestas del Campo — Campo de Guardamar",
                programme_order=20,
                image_url=IMAGE,
            ),
            SourceEvent(
                "Desfile Multicolor",
                date(2026, 9, 25),
                date(2026, 9, 25),
                "19:00",
                None,
                None,
                "event",
                ("turismo_programme",),
                teaser_es="Un desfile con carrozas y música.",
                programme_title="Fiestas del Campo — Campo de Guardamar",
                programme_order=30,
                image_url=IMAGE,
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_municipal(
                paths["municipal_agenda_state_path"],
                datetime(2026, 9, 24, 5, 10, tzinfo=TZ),
                events,
            )
            publication = await produce_tomorrow_event_publication(
                NOW, **paths
            )

        self.assertIsNotNone(publication)
        self.assertEqual(publication.unit_count, 1)
        self.assertEqual(publication.image_url, IMAGE)
        self.assertEqual(
            publication.message.count("Fiestas del Campo — Campo de Guardamar"),
            1,
        )
        self.assertIn("Шествие музыкальных оркестров", publication.message)
        self.assertIn("Красочный парад", publication.message)

    async def test_multiple_units_use_one_compact_text_post_without_image(self):
        events = [
            SourceEvent(
                "Concierto",
                date(2026, 9, 25),
                date(2026, 9, 25),
                "19:00",
                None,
                "Casa de Cultura",
                "event",
                ("turismo_html",),
                teaser_es="Descripción extensa del concierto que solo necesita el post individual.",
                image_url=IMAGE,
            ),
            SourceEvent(
                "Taller de dibujo",
                date(2026, 9, 25),
                date(2026, 9, 25),
                "20:00",
                None,
                "Centro Social Juvenil",
                "workshop",
                ("todo_cultura",),
                teaser_es="Descripción extensa del taller que no va en el paquete.",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(directory)
            _write_municipal(
                paths["municipal_agenda_state_path"],
                datetime(2026, 9, 24, 5, 10, tzinfo=TZ),
                events,
            )
            publication = await produce_tomorrow_event_publication(
                NOW, **paths
            )

        self.assertIsNotNone(publication)
        self.assertEqual(publication.unit_count, 2)
        self.assertIsNone(publication.image_url)
        self.assertIn("Concierto", publication.message)
        self.assertIn("Taller de dibujo", publication.message)
        self.assertNotIn("Descripción extensa", publication.message)


if __name__ == "__main__":
    unittest.main()
