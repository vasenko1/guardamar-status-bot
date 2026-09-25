import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from telegrambot import alicante_schedule as avanza
from telegrambot.elche_schedule import (
    build_message as build_elche_message,
    fetch_schedules as fetch_elche_schedules,
)
from telegrambot.intercity_schedule import (
    IntercityFare,
    IntercitySchedule,
    IntercityScheduleBundle,
    IntercityScheduleState,
)
from telegrambot.orihuela_schedule import (
    _parse_schedule_response,
    build_message as build_orihuela_message,
    parse_fare_pdf,
)
from telegrambot.branding import FOOTER


TODAY = date(2026, 9, 25)
TOMORROW = date(2026, 9, 26)


class IntercityStateTests(unittest.TestCase):
    def test_round_trip_current_and_next(self):
        with tempfile.TemporaryDirectory() as directory:
            state = IntercityScheduleState(Path(directory) / "route.json")
            bundle = IntercityScheduleBundle(
                current=IntercitySchedule(
                    TODAY,
                    ("06:00", "10:00"),
                    ("07:00", "11:00"),
                    IntercityFare(360),
                ),
                next=IntercitySchedule(
                    TOMORROW,
                    ("06:30",),
                    ("07:30",),
                    IntercityFare(
                        345,
                        effective_date=date(2026, 2, 1),
                        source_url="https://www.bus-siguenza.com/wbus/tarifas/a.pdf",
                        pdf_sha256="a" * 64,
                    ),
                ),
            )
            state.write(bundle)
            self.assertEqual(state.read(), bundle)
            raw = json.loads(state.path.read_text(encoding="utf-8"))
            self.assertNotIn("html", raw)
            self.assertNotIn("pdf", raw["current"])


class ElcheScheduleTests(unittest.TestCase):
    @patch("telegrambot.elche_schedule.avanza._fetch_direction")
    @patch("telegrambot.elche_schedule.avanza._search_form")
    @patch("telegrambot.elche_schedule.avanza._planner_open")
    def test_fetches_both_directions_and_fare(
        self,
        planner_open,
        search_form,
        fetch_direction,
    ):
        planner_open.return_value = (b"<html></html>", avanza.PLANNER_URL)
        search_form.return_value = (
            "https://regular.autobusing.com/info/horarios",
            {"empresa": "costa-azul"},
        )
        fetch_direction.side_effect = [
            avanza._Direction(("06:50", "08:50"), avanza.AlicanteFare(360, False)),
            avanza._Direction(("07:45", "10:45"), avanza.AlicanteFare(360, False)),
        ]
        result = fetch_elche_schedules((TODAY,))
        self.assertEqual(result[TODAY].outbound, ("06:50", "08:50"))
        self.assertEqual(result[TODAY].inbound, ("07:45", "10:45"))
        self.assertEqual(result[TODAY].fare, IntercityFare(360, False))

    def test_card_preserves_full_schedule_price_and_navigation(self):
        schedule = IntercitySchedule(
            TODAY,
            ("06:50", "08:50", "10:50", "11:50", "15:55", "17:50"),
            ("07:45", "10:45"),
            IntercityFare(360),
        )
        message = build_elche_message(
            schedule,
            TODAY,
            "https://t.me/c/1/50",
        )
        self.assertIn("Сегодня, 25 сентября, пятница", message)
        self.assertIn("06:50 · 08:50 · 10:50 · 11:50 · 15:55\n17:50", message)
        self.assertIn("Билет в одну сторону:</b> 3,60 €", message)
        self.assertIn("Найти расписание на другую дату", message)
        self.assertIn("https://t.me/c/1/50", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertLessEqual(len(message), 4096)


class OrihuelaScheduleTests(unittest.TestCase):
    def _html(self):
        return b"""
        <html><body>
          <h3 class="panel-title">GUARDAMAR DEL SEGURA ORIHUELA</h3>
          <table>
            <tr><td><button>06:20</button></td></tr>
            <tr><td><button>08:15</button></td></tr>
          </table>
          <h3 class="panel-title">ORIHUELA GUARDAMAR DEL SEGURA</h3>
          <table>
            <tr><td><button>06:45</button></td></tr>
            <tr><td><button>09:15</button></td></tr>
          </table>
          <a href="wbus/tarifas/2026_CE-714%20test.pdf">Tarifas</a>
        </body></html>
        """

    def test_parses_exact_two_directions_and_fare_link(self):
        schedule, fare_url = _parse_schedule_response(
            self._html(),
            TODAY,
            "https://www.bus-siguenza.com/wbus/procesa.php",
        )
        self.assertEqual(schedule.outbound, ("06:20", "08:15"))
        self.assertEqual(schedule.inbound, ("06:45", "09:15"))
        self.assertEqual(
            fare_url,
            "https://www.bus-siguenza.com/wbus/tarifas/2026_CE-714%20test.pdf",
        )

    @patch("telegrambot.orihuela_schedule.bus._run")
    def test_parses_verified_base_general_fare(self, run):
        text = """
Dirección General de Transportes y Logística
CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT
FECHA ENTRADA EN VIGOR: 1 FEBRERO DE 2026
LÍNEA 1: ORIHUELA - (LAS DAYAS A LA DEMANDA) - GUARDAMAR DEL SEGURA
TARIFA BASE GENERAL
  37  3,45 €   31  2,85 €   28  2,60 €   25  2,30 €   22  2,05 €   15  1,60 €   12  1,60 €   8  1,60 €   6  1,60 €   12  1,60 €   16  1,60 €   14  1,60 €   10  1,60 €   10  1,60 €
TARIFA MAYORES DE 65 AÑOS
FIRMADO ELECTRÓNICAMENTE POR EL JEFE DEL SERVICIO DE TRANSPORTE PÚBLICO
"""
        run.side_effect = [
            b"Pages:          1\nEncrypted:      no\n",
            text.encode("utf-8"),
        ]
        fare = parse_fare_pdf(
            b"%PDF-fake",
            "https://www.bus-siguenza.com/wbus/tarifas/fare.pdf",
            etag='"x"',
            last_modified="today",
        )
        self.assertEqual(fare.cents, 345)
        self.assertEqual(fare.effective_date, date(2026, 2, 1))
        self.assertEqual(fare.pdf_sha256, __import__("hashlib").sha256(b"%PDF-fake").hexdigest())

    @patch("telegrambot.orihuela_schedule.bus._run")
    def test_fare_parser_rejects_wrong_distance_row(self, run):
        text = """
Dirección General de Transportes y Logística
CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT
FECHA ENTRADA EN VIGOR: 1 FEBRERO DE 2026
LÍNEA 1: ORIHUELA - (LAS DAYAS A LA DEMANDA) - GUARDAMAR DEL SEGURA
TARIFA BASE GENERAL
  36  3,45 €   31  2,85 €   28  2,60 €   25  2,30 €   22  2,05 €   15  1,60 €   12  1,60 €   8  1,60 €   6  1,60 €   12  1,60 €   16  1,60 €   14  1,60 €   10  1,60 €   10  1,60 €
TARIFA MAYORES DE 65 AÑOS
FIRMADO ELECTRÓNICAMENTE POR EL JEFE DEL SERVICIO DE TRANSPORTE PÚBLICO
"""
        run.side_effect = [
            b"Pages:          1\nEncrypted:      no\n",
            text.encode("utf-8"),
        ]
        from telegrambot.intercity_schedule import IntercityScheduleError
        with self.assertRaises(IntercityScheduleError):
            parse_fare_pdf(
                b"%PDF-fake",
                "https://www.bus-siguenza.com/wbus/tarifas/fare.pdf",
                etag=None,
                last_modified=None,
            )

    def test_card_shows_price_source_and_full_schedule(self):
        schedule = IntercitySchedule(
            TODAY,
            ("06:20", "08:15", "09:30", "11:30", "12:00", "15:00"),
            ("06:45", "09:15"),
            IntercityFare(
                345,
                effective_date=date(2026, 2, 1),
                source_url="https://www.bus-siguenza.com/wbus/tarifas/fare.pdf",
            ),
        )
        message = build_orihuela_message(
            schedule,
            TODAY,
            "https://t.me/c/1/50",
        )
        self.assertIn("Сегодня, 25 сентября, пятница", message)
        self.assertIn("06:20 · 08:15 · 09:30 · 11:30 · 12:00\n15:00", message)
        self.assertIn("3,45 €", message)
        self.assertIn("wbus/tarifas/fare.pdf", message)
        self.assertIn("Найти расписание на другую дату", message)
        self.assertIn("https://t.me/c/1/50", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertLessEqual(len(message), 4096)


if __name__ == "__main__":
    unittest.main()
