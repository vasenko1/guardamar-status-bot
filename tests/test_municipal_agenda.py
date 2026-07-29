import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.municipal_agenda import (
    MunicipalAgendaError,
    _current_events,
    _apply_reviewed_corrections,
    _load_snapshot,
    _merge_reviewed_text_agenda,
    _snapshot_data,
    _write_snapshot,
    extract_poster_url,
    fetch_today_municipal_events,
    normalize_extraction,
)

TZ = ZoneInfo("Europe/Madrid")


def extraction():
    return {
        "month": "2026-07",
        "events": [
            {
                "title_es": "Concierto en el castillo",
                "start_date": "2026-07-27",
                "end_date": None,
                "start_time": "21:00",
                "end_time": "23:00",
                "place": "Castillo",
                "category": "event",
            },
            {
                "title_es": "Entropía",
                "start_date": "2026-07-01",
                "end_date": "2026-07-31",
                "start_time": None,
                "end_time": None,
                "place": "Biblioteca",
                "category": "exhibition",
            },
            {
                "title_es": "Ecoparque móvil",
                "start_date": "2026-07-27",
                "end_date": None,
                "start_time": "09:00",
                "end_time": "12:00",
                "place": None,
                "category": "municipal_service",
            },
        ],
    }


class MunicipalAgendaTests(unittest.IsolatedAsyncioTestCase):
    def test_finds_only_official_mupi_poster(self):
        page = b"""
        <a href="https://example.com/MUPI-JULIO.jpg">bad</a>
        <a href="https://www.guardamardelsegura.es/wp-content/uploads/2026/07/MUPI-JULIO-2026-scaled.jpg">poster</a>
        """
        self.assertIn("MUPI-JULIO-2026", extract_poster_url(page))

    def test_normalizes_events_and_excludes_services(self):
        events = normalize_extraction(extraction())
        self.assertEqual([event.title_es for event in events], [
            "Concierto en el castillo",
            "Entropía",
        ])

    def test_snapshot_contains_source_facts_not_translation(self):
        events = normalize_extraction(extraction())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            data = _snapshot_data(
                "https://www.guardamardelsegura.es/wp-content/uploads/MUPI.jpg",
                "abc",
                datetime(2026, 7, 27, tzinfo=TZ),
                events,
            )
            _write_snapshot(path, data)
            loaded = _load_snapshot(path)
            raw = json.loads(path.read_text())
        self.assertEqual(len(loaded["_events"]), 2)
        self.assertNotIn("title_ru", path.read_text() if path.exists() else json.dumps(raw))
        self.assertEqual(raw["events"][0]["title_es"], "Concierto en el castillo")

    def test_repairs_reviewed_entropia_facts_without_reprocessing_poster(self):
        incorrect = (
            normalize_extraction(
                {
                    "events": [
                        {
                            "title_es": "Exposición de pintura: Conchi Montes",
                            "start_date": "2026-07-03",
                            "end_date": "2026-07-29",
                            "start_time": "09:00",
                            "end_time": "14:00",
                            "place": "Biblioteca Municipal",
                            "category": "exhibition",
                        }
                    ]
                }
            )
        )

        corrected = _apply_reviewed_corrections(
            (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-JULIO-2026.jpg"
            ),
            incorrect,
        )

        self.assertEqual(
            corrected[0].title_es,
            "Exposición de pintura «Entropía» de Conchi Montes",
        )
        self.assertEqual(corrected[0].start_time, "08:00")
        self.assertEqual(corrected[0].end_time, "14:00")
        self.assertEqual(
            corrected[0].place,
            "Biblioteca Pública Municipal",
        )

    def test_keeps_entropia_when_site_advances_to_august_poster(self):
        august_events = normalize_extraction(
            {
                "events": [
                    {
                        "title_es": "Evento de agosto",
                        "start_date": "2026-08-01",
                        "end_date": "2026-08-01",
                        "start_time": None,
                        "end_time": None,
                        "place": None,
                        "category": "event",
                    }
                ]
            }
        )

        merged = _merge_reviewed_text_agenda(august_events)

        entropia = next(
            event for event in merged if "Entropía" in event.title_es
        )
        self.assertEqual(entropia.end_date, datetime(2026, 7, 29).date())
        self.assertEqual(entropia.start_time, "08:00")

    async def test_unchanged_poster_uses_snapshot_without_ocr(self):
        events = normalize_extraction(extraction())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            url = (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/07/MUPI-JULIO-2026-scaled.jpg"
            )
            _write_snapshot(
                path,
                _snapshot_data(
                    url, "abc", datetime(2026, 7, 26, tzinfo=TZ), events
                ),
            )
            page = f'<a href="{url}">poster</a>'.encode()
            with patch(
                "telegrambot.municipal_agenda._read_url",
                return_value=(page, "text/html"),
            ), patch(
                "telegrambot.municipal_agenda.extract_agenda_events",
                new=AsyncMock(),
            ) as ocr:
                current = await _current_events(
                    "key", datetime(2026, 7, 27, tzinfo=TZ), path
                )
        self.assertEqual(len(current), 2)
        ocr.assert_not_awaited()

    async def test_site_failure_uses_snapshot_and_translates_selected_events(self):
        events = normalize_extraction(extraction())
        diagnostics = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agenda.json"
            _write_snapshot(
                path,
                _snapshot_data(
                    "https://www.guardamardelsegura.es/wp-content/uploads/MUPI.jpg",
                    "abc",
                    datetime(2026, 7, 26, tzinfo=TZ),
                    events,
                ),
            )
            with patch(
                "telegrambot.municipal_agenda._read_url",
                side_effect=MunicipalAgendaError("offline"),
            ), patch(
                "telegrambot.municipal_agenda.translate_event_titles",
                new=AsyncMock(
                    return_value=["Концерт в замке", "Выставка «Энтропия»"]
                ),
            ):
                current = await fetch_today_municipal_events(
                    datetime(2026, 7, 27, tzinfo=TZ),
                    "key",
                    path,
                    diagnostics,
                )
        self.assertEqual(current[0].title, "Концерт в замке")
        self.assertEqual(current[0].starts_at.hour, 21)
        self.assertEqual(current[0].ends_at.hour, 23)
        self.assertEqual(current[1].place, "Biblioteca")
        self.assertEqual(current[1].category, "exhibition")
        self.assertEqual(
            diagnostics[0].code,
            "MUNI-AGENDA-FALLBACK-INVALID",
        )
        self.assertIn("локальный снимок", diagnostics[0].description)


if __name__ == "__main__":
    unittest.main()
