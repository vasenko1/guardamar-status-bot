import asyncio
import json
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.pesca_cv import (
    PescaCvSourceError,
    fetch_today_pesca_cv_events,
    parse_pesca_cv_html,
    pesca_cv_translation_items,
    refresh_pesca_cv_catalog,
    valid_pesca_cv_snapshot,
)


MADRID = ZoneInfo("Europe/Madrid")


def _html(rows: str) -> bytes:
    return f"""
    <html><body><table>
      <tr><th>FECHA</th><th>CLUB</th><th>ENTIDAD</th><th>AMBITO</th><th>MODALIDAD</th><th>ESCENARIO</th><th>PROVINCIA</th><th>ZONA</th></tr>
      {rows}
    </table></body></html>
    """.encode()


class PescaCvParserTests(unittest.TestCase):
    def test_filters_noise_and_collapses_consecutive_national_days(self):
        rows = []
        for day in range(23, 30):
            rows.append(
                f"<tr><td>{day:02d}/11/2026</td><td>0</td><td>FED. ESPAÑOLA PESCA Y C.</td><td>NACIONAL</td><td>MAR COSTA DÚOS</td><td>GUARDAMAR</td><td>ALICANTE</td><td>PLAYA *</td></tr>"
            )
        rows.append(
            "<tr><td>30/11/2026</td><td>A091</td><td>C.P. HORADADA</td><td>SOCIAL CLASIF.</td><td>MAR COSTA</td><td>GUARDAMAR</td><td>ALICANTE</td><td>PLAYA *</td></tr>"
        )
        snapshot = parse_pesca_cv_html(
            _html("".join(rows)),
            date(2026, 9, 17),
            datetime(2026, 9, 17, 16, 30, tzinfo=MADRID),
        )
        self.assertTrue(valid_pesca_cv_snapshot(snapshot))
        self.assertEqual(len(snapshot["events"]), 1)
        event = snapshot["events"][0]
        self.assertEqual(event["title"], "Mar Costa Dúos")
        self.assertEqual(event["start"], "2026-11-23")
        self.assertEqual(event["end"], "2026-11-29")
        self.assertEqual(event["organizer"], "FED. ESPAÑOLA PESCA Y C.")
        self.assertEqual(event["place"], "Guardamar · Playa")

    def test_keeps_provincial_but_rejects_special(self):
        snapshot = parse_pesca_cv_html(
            _html(
                """
                <tr><td>01/10/2026</td><td>0</td><td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td><td>MAR COSTA</td><td>GUARDAMAR</td><td>ALICANTE</td><td>PLAYA</td></tr>
                <tr><td>02/10/2026</td><td>A001</td><td>CLUB</td><td>ESPECIAL (A)</td><td>MAR COSTA</td><td>GUARDAMAR</td><td>ALICANTE</td><td>PLAYA</td></tr>
                """
            ),
            date(2026, 9, 17),
            datetime(2026, 9, 17, 16, 30, tzinfo=MADRID),
        )
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(snapshot["events"][0]["level"], "PROVINCIAL")

    def test_fails_closed_when_production_columns_disappear(self):
        payload = b"<table><tr><th>FECHA</th><th>CLUB</th></tr></table>"
        with self.assertRaises(PescaCvSourceError):
            parse_pesca_cv_html(
                payload,
                date(2026, 9, 17),
                datetime(2026, 9, 17, 16, 30, tzinfo=MADRID),
            )

    def test_cached_reader_uses_fepyc_authority_for_national_dates(self):
        observed = datetime(2026, 9, 17, 5, 10, tzinfo=MADRID)
        rows = []
        for day in range(23, 30):
            rows.append(
                f"<tr><td>{day:02d}/11/2026</td><td>0</td><td>FED. ESPAÑOLA PESCA Y C.</td><td>NACIONAL</td><td>MAR COSTA DÚOS</td><td>GUARDAMAR</td><td>ALICANTE</td><td>PLAYA *</td></tr>"
            )
        snapshot = parse_pesca_cv_html(
            _html("".join(rows)),
            date(2026, 9, 17),
            observed,
        )
        authority = {
            "version": 1,
            "records": [{
                "source_id": "26MC26",
                "match_title": "Mar Costa Dúos",
                "competition_name": "XVI Campeonato de España Mar-costa Dúos",
                "specialty": "Lanzado Mar Costa",
                "category": "Dúos",
                "competition_type": "Nacional",
                "start": "2026-11-26",
                "end": "2026-11-29",
                "place": "Guardamar del Segura (Alicante)",
                "source_url": "https://www.fepyc.es/26MC26",
                "observed_at": datetime(
                    2026, 11, 26, 5, 10, tzinfo=MADRID
                ).isoformat(),
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            authority_state = Path(directory) / "authority.json"
            details_state = Path(directory) / "details.json"
            translations = Path(directory) / "translations.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            authority_state.write_text(json.dumps(authority), encoding="utf-8")

            before = asyncio.run(fetch_today_pesca_cv_events(
                datetime(2026, 11, 25, 7, 30, tzinfo=MADRID),
                state,
                translations,
                fepyc_authority_state_path=authority_state,
                details_state_path=details_state,
            ))
            events = asyncio.run(fetch_today_pesca_cv_events(
                datetime(2026, 11, 26, 7, 30, tzinfo=MADRID),
                state,
                translations,
                fepyc_authority_state_path=authority_state,
                details_state_path=details_state,
            ))
            items = asyncio.run(pesca_cv_translation_items(observed, state))

        self.assertEqual(before, ())
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0].title,
            "Национальные соревнования — Mar Costa Dúos",
        )
        self.assertEqual(events[0].active_from, date(2026, 11, 26))
        self.assertEqual(events[0].active_until, date(2026, 11, 29))
        self.assertEqual(
            events[0].details,
            ("Чемпионат Испании · категория дуэты",),
        )
        self.assertEqual(events[0].sport, "fishing")
        self.assertEqual(items, (("pesca_cv", "Mar Costa Dúos"),))

    def test_national_event_is_withheld_without_fepyc_authority(self):
        observed = datetime(2026, 9, 17, 5, 10, tzinfo=MADRID)
        rows = "".join(
            f"<tr><td>{day:02d}/11/2026</td><td>0</td><td>FED. ESPAÑOLA PESCA Y C.</td><td>NACIONAL</td><td>MAR COSTA DÚOS</td><td>GUARDAMAR</td><td>ALICANTE</td><td>PLAYA *</td></tr>"
            for day in range(23, 30)
        )
        snapshot = parse_pesca_cv_html(
            _html(rows),
            date(2026, 9, 17),
            observed,
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            events = asyncio.run(fetch_today_pesca_cv_events(
                datetime(2026, 11, 26, 7, 30, tzinfo=MADRID),
                state,
                Path(directory) / "translations.json",
                fepyc_authority_state_path=Path(directory) / "missing-authority.json",
                details_state_path=Path(directory) / "missing-details.json",
            ))
        self.assertEqual(events, ())

    def test_provincial_event_uses_normalized_convocatoria_details(self):
        observed = datetime(2026, 10, 5, 5, 11, tzinfo=MADRID)
        snapshot = parse_pesca_cv_html(
            _html(
                "<tr><td>17/10/2026</td><td>0</td>"
                "<td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td>"
                "<td>MAR COSTA</td><td>GUARDAMAR</td>"
                "<td>ALICANTE</td><td>ZONA B - CENTRO, LA ROQUETA Y MONCAYO *</td></tr>"
            ),
            observed.date(),
            observed,
        )
        detail = {
            "join_key": "2026-10-17|provincial|mar costa",
            "base_start": "2026-10-17",
            "base_level": "PROVINCIAL",
            "base_title": "Mar Costa",
            "index_date": "2026-10-17",
            "cancelled": False,
            "source_url": (
                "https://federacionpescacv.com/wp-content/uploads/2026/09/"
                "bases-prov-mar-costa-captura-y-suelta-2026.pdf"
            ),
            "document_identity": "a" * 64,
            "content_sha256": "c" * 64,
            "competition_context": (
                "Провинциальный чемпионат Аликанте · "
                "отбор на Comunidad Valenciana 2027"
            ),
            "details": [
                (
                    "Провинциальный чемпионат Аликанте · "
                    "отбор на Comunidad Valenciana 2027"
                ),
                "2 тура по 3 часа",
                "Сбор участников: 16:00",
                "1-й тур: 18:00–21:00",
                "2-й тур: 22:30–01:30",
            ],
            "starts_at": "2026-10-17T18:00:00+02:00",
            "ends_at": "2026-10-18T01:30:00+02:00",
            "place": "Playas La Roqueta y Centro",
            "schedule_note": (
                "Время может немного измениться из-за занятости пляжей"
            ),
            "registration_method": "clubs",
            "registration_deadline": "2026-10-13T12:00:00+02:00",
            "registration_fee_cents": 2000,
            "observed_at": datetime(
                2026, 10, 17, 5, 10, tzinfo=MADRID
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            details_state = Path(directory) / "details.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            details_state.write_text(
                json.dumps({"version": 1, "records": [detail]}),
                encoding="utf-8",
            )
            events = asyncio.run(fetch_today_pesca_cv_events(
                datetime(2026, 10, 17, 7, 30, tzinfo=MADRID),
                state,
                Path(directory) / "translations.json",
                fepyc_authority_state_path=Path(directory) / "missing-authority.json",
                details_state_path=details_state,
            ))

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.starts_at.hour, 18)
        self.assertEqual(event.ends_at.date(), date(2026, 10, 18))
        self.assertEqual(event.place, "Playas La Roqueta y Centro")
        self.assertIn("Провинциальный чемпионат Аликанте", event.details[0])
        self.assertIn("2 тура по 3 часа", event.details)
        self.assertEqual(
            event.schedule_note,
            "Время может немного измениться из-за занятости пляжей",
        )
        self.assertEqual(event.sport, "fishing")

    def test_cancelled_fpcv_detail_suppresses_normal_event_projection(self):
        observed = datetime(2026, 10, 5, 5, 11, tzinfo=MADRID)
        snapshot = parse_pesca_cv_html(
            _html(
                "<tr><td>17/10/2026</td><td>0</td>"
                "<td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td>"
                "<td>MAR COSTA</td><td>GUARDAMAR</td>"
                "<td>ALICANTE</td><td>PLAYA</td></tr>"
            ),
            observed.date(),
            observed,
        )
        cancelled = {
            "join_key": "2026-10-17|provincial|mar costa",
            "base_start": "2026-10-17",
            "base_level": "PROVINCIAL",
            "base_title": "Mar Costa",
            "index_date": "2026-10-17",
            "cancelled": True,
            "source_url": None,
            "document_identity": "b" * 64,
            "content_sha256": None,
            "competition_context": None,
            "details": [],
            "starts_at": None,
            "ends_at": None,
            "place": None,
            "schedule_note": None,
            "registration_method": None,
            "registration_deadline": None,
            "registration_fee_cents": None,
            "observed_at": datetime(
                2026, 10, 17, 5, 10, tzinfo=MADRID
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            details_state = Path(directory) / "details.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            details_state.write_text(
                json.dumps({"version": 1, "records": [cancelled]}),
                encoding="utf-8",
            )
            events = asyncio.run(fetch_today_pesca_cv_events(
                datetime(2026, 10, 17, 7, 30, tzinfo=MADRID),
                state,
                Path(directory) / "translations.json",
                fepyc_authority_state_path=Path(directory) / "missing-authority.json",
                details_state_path=details_state,
            ))

        self.assertEqual(events, ())

    def test_stale_cancelled_detail_does_not_hide_current_base_event(self):
        observed = datetime(2026, 10, 5, 5, 11, tzinfo=MADRID)
        snapshot = parse_pesca_cv_html(
            _html(
                "<tr><td>17/10/2026</td><td>0</td>"
                "<td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td>"
                "<td>MAR COSTA</td><td>GUARDAMAR</td>"
                "<td>ALICANTE</td><td>PLAYA</td></tr>"
            ),
            observed.date(),
            observed,
        )
        stale = {
            "join_key": "2026-10-17|provincial|mar costa",
            "base_start": "2026-10-17",
            "base_level": "PROVINCIAL",
            "base_title": "Mar Costa",
            "index_date": "2026-10-17",
            "cancelled": True,
            "source_url": None,
            "document_identity": "e" * 64,
            "content_sha256": None,
            "competition_context": None,
            "details": [],
            "starts_at": None,
            "ends_at": None,
            "place": None,
            "schedule_note": None,
            "registration_method": None,
            "registration_deadline": None,
            "registration_fee_cents": None,
            "observed_at": observed.isoformat(),
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            details_state = Path(directory) / "details.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            details_state.write_text(
                json.dumps({"version": 1, "records": [stale]}),
                encoding="utf-8",
            )
            events = asyncio.run(fetch_today_pesca_cv_events(
                datetime(2026, 10, 17, 7, 30, tzinfo=MADRID),
                state,
                Path(directory) / "translations.json",
                fepyc_authority_state_path=Path(directory) / "missing-authority.json",
                details_state_path=details_state,
            ))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].sport, "fishing")

    def test_validator_rejects_non_guardamar_place(self):
        observed = datetime(2026, 9, 17, 5, 10, tzinfo=MADRID)
        snapshot = parse_pesca_cv_html(
            _html(
                "<tr><td>17/10/2026</td><td>0</td>"
                "<td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td>"
                "<td>MAR COSTA</td><td>GUARDAMAR</td>"
                "<td>ALICANTE</td><td>PLAYA</td></tr>"
            ),
            date(2026, 9, 17),
            observed,
        )
        snapshot["events"][0]["place"] = "Torrevieja"
        self.assertFalse(valid_pesca_cv_snapshot(snapshot))

    def test_refresh_preserves_last_good_on_source_failure(self):
        observed = datetime(2026, 9, 17, 5, 10, tzinfo=MADRID)
        snapshot = parse_pesca_cv_html(
            _html(
                "<tr><td>17/10/2026</td><td>0</td>"
                "<td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td>"
                "<td>MAR COSTA</td><td>GUARDAMAR</td>"
                "<td>ALICANTE</td><td>PLAYA</td></tr>"
            ),
            date(2026, 9, 17),
            observed,
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            with patch(
                "telegrambot.pesca_cv.fetch_pesca_cv_snapshot",
                new=AsyncMock(
                    side_effect=PescaCvSourceError("down", code="NETWORK")
                ),
            ):
                events = asyncio.run(refresh_pesca_cv_catalog(observed, state))
            saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(len(events), 1)
        self.assertEqual(saved, snapshot)

    def test_successful_empty_refresh_replaces_old_future_event(self):
        observed = datetime(2026, 9, 17, 5, 10, tzinfo=MADRID)
        previous = parse_pesca_cv_html(
            _html(
                "<tr><td>17/10/2026</td><td>0</td>"
                "<td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td>"
                "<td>MAR COSTA</td><td>GUARDAMAR</td>"
                "<td>ALICANTE</td><td>PLAYA</td></tr>"
            ),
            date(2026, 9, 17),
            observed,
        )
        current = {"observed_at": observed.isoformat(), "events": []}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            state.write_text(json.dumps(previous), encoding="utf-8")
            with patch(
                "telegrambot.pesca_cv.fetch_pesca_cv_snapshot",
                new=AsyncMock(return_value=current),
            ):
                events = asyncio.run(refresh_pesca_cv_catalog(observed, state))
            saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(events, ())
        self.assertEqual(saved["events"], [])

    def test_corrupt_local_state_recovers_from_valid_remote(self):
        observed = datetime(2026, 9, 17, 5, 10, tzinfo=MADRID)
        current = parse_pesca_cv_html(
            _html(
                "<tr><td>17/10/2026</td><td>0</td>"
                "<td>DELEGACIÓN ALICANTE</td><td>PROVINCIAL</td>"
                "<td>MAR COSTA</td><td>GUARDAMAR</td>"
                "<td>ALICANTE</td><td>PLAYA</td></tr>"
            ),
            date(2026, 9, 17),
            observed,
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "pesca.json"
            state.write_text("{broken", encoding="utf-8")
            with patch(
                "telegrambot.pesca_cv.fetch_pesca_cv_snapshot",
                new=AsyncMock(return_value=current),
            ):
                events = asyncio.run(refresh_pesca_cv_catalog(observed, state))
            saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(len(events), 1)
        self.assertTrue(valid_pesca_cv_snapshot(saved))


if __name__ == "__main__":
    unittest.main()
