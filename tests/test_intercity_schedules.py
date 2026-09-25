import json
import tempfile
import unittest
import urllib.parse
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
from telegrambot.zenia_schedule import (
    build_message as build_zenia_message,
    fetch_schedules as fetch_zenia_schedules,
)
from telegrambot.orihuela_schedule import (
    _fetch_schedule,
    _parse_schedule_response,
    _refresh_fare,
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
        self.assertIn(
            "query=38.0877707496%2C-0.6560185196",
            message,
        )
        self.assertIn("https://t.me/c/1/50", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertLessEqual(len(message), 4096)


class ZeniaScheduleTests(unittest.TestCase):
    @patch("telegrambot.zenia_schedule.avanza._fetch_direction")
    @patch("telegrambot.zenia_schedule.avanza._search_form")
    @patch("telegrambot.zenia_schedule.avanza._planner_open")
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
            avanza._Direction(("08:10", "10:10"), avanza.AlicanteFare(275, False)),
            avanza._Direction(("12:15", "16:15"), avanza.AlicanteFare(275, False)),
        ]

        result = fetch_zenia_schedules((TODAY,))

        self.assertEqual(result[TODAY].outbound, ("08:10", "10:10"))
        self.assertEqual(result[TODAY].inbound, ("12:15", "16:15"))
        self.assertEqual(result[TODAY].fare, IntercityFare(275, False))

        calls = fetch_direction.call_args_list
        self.assertEqual(calls[0].args[-2:], ("GUARDAMAR", "C.C. BOULEVAR ZENIA"))
        self.assertEqual(calls[1].args[-2:], ("C.C. BOULEVAR ZENIA", "GUARDAMAR"))

    def test_card_preserves_full_schedule_price_and_navigation(self):
        schedule = IntercitySchedule(
            TODAY,
            ("08:10", "10:10", "12:10", "14:10", "16:10", "18:10"),
            ("11:15", "13:15", "15:15"),
            IntercityFare(275),
        )
        message = build_zenia_message(
            schedule,
            TODAY,
            "https://t.me/c/1/50",
        )

        self.assertIn("Сегодня, 25 сентября, пятница", message)
        self.assertIn("08:10 · 10:10 · 12:10 · 14:10 · 16:10\n18:10", message)
        self.assertIn("Билет в одну сторону:</b> 2,75 €", message)
        self.assertIn("🚌 <b>Маршрут:</b> Alicante ↔ Pilar de la Horadada", message)
        self.assertIn(
            "Из Гуардамара садитесь в сторону <b>Pilar de la Horadada</b>.",
            message,
        )
        self.assertIn(
            "Обратно от Zenia Boulevard садитесь в сторону <b>Alicante</b>.",
            message,
        )
        self.assertIn("Сегодня", message)
        self.assertIn("Найти расписание на другую дату", message)
        self.assertIn(
            "query=38.0877707496%2C-0.6560185196",
            message,
        )
        self.assertIn(
            "query=37.9292298333%2C-0.7346398333",
            message,
        )
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

    @patch("telegrambot.orihuela_schedule._parse_schedule_response")
    @patch("telegrambot.orihuela_schedule.bus._open_bounded")
    def test_fetch_schedule_posts_requested_service_date(
        self,
        open_bounded,
        parse_response,
    ):
        headers = Mock()
        headers.get_content_type.return_value = "text/html"
        open_bounded.return_value = (
            b"<html></html>",
            "https://www.bus-siguenza.com/wbus/procesa.php",
            headers,
            200,
        )
        expected = (
            IntercitySchedule(
                TODAY,
                ("06:20",),
                ("06:45",),
            ),
            None,
        )
        parse_response.return_value = expected

        self.assertEqual(_fetch_schedule(TODAY), expected)

        request = open_bounded.call_args.args[0]
        fields = urllib.parse.parse_qs(request.data.decode("ascii"))
        self.assertEqual(fields["FECHASALIDA"], ["25/09/2026"])
        self.assertEqual(fields["ORIGEN"], ["GUARDAMAR DEL SEGURA"])
        self.assertEqual(fields["DESTINO"], ["ORIHUELA"])

    @patch("telegrambot.orihuela_schedule.bus._run")
    def test_parses_verified_base_general_fare(self, run):
        text = """
Dirección General de Transportes y Logística
CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT
FECHA ENTRADA EN VIGOR: 1 FEBRERO DE 2026
LÍNEA 1: ORIHUELA - (LAS DAYAS A LA DEMANDA) - GUARDAMAR DEL SEGURA
TARIFA BASE GENERAL
  37  3,45 €   31  2,85 €   28  2,60 €   25  2,30 €   22  2,05 €   15  1,60 €   19  1,75 €   11  1,60 €   9  1,60 €   7  1,60 €   11  1,60 €   GUARDAMAR DE SEGURA
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
  36  3,45 €   31  2,85 €   28  2,60 €   25  2,30 €   22  2,05 €   15  1,60 €   19  1,75 €   11  1,60 €   9  1,60 €   7  1,60 €   11  1,60 €   GUARDAMAR DE SEGURA
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

    @patch("telegrambot.orihuela_schedule.parse_fare_pdf")
    @patch("telegrambot.orihuela_schedule.bus.download_fare_pdf")
    def test_future_replacement_keeps_current_verified_fare_until_effective(
        self,
        download_fare_pdf,
        parse_fare_pdf_mock,
    ):
        url = "https://www.bus-siguenza.com/wbus/tarifas/fare.pdf"
        cached = IntercityFare(
            345,
            effective_date=date(2026, 2, 1),
            source_url=url,
            etag='"old"',
            last_modified="old",
            pdf_sha256="a" * 64,
        )
        downloaded = SimpleNamespace(
            payload=b"%PDF-new",
            url=url,
            etag='"new"',
            last_modified="new",
        )
        download_fare_pdf.side_effect = [downloaded, downloaded]
        parse_fare_pdf_mock.return_value = IntercityFare(
            365,
            effective_date=date(2026, 10, 1),
            source_url=url,
            etag='"new"',
            last_modified="new",
            pdf_sha256="b" * 64,
        )

        result = _refresh_fare(url, cached, TODAY)

        self.assertEqual(result, cached)

    @patch("telegrambot.orihuela_schedule.parse_fare_pdf")
    @patch("telegrambot.orihuela_schedule.bus.download_fare_pdf")
    def test_future_replacement_is_accepted_on_effective_date(
        self,
        download_fare_pdf,
        parse_fare_pdf_mock,
    ):
        url = "https://www.bus-siguenza.com/wbus/tarifas/fare.pdf"
        cached = IntercityFare(
            345,
            effective_date=date(2026, 2, 1),
            source_url=url,
            etag='"old"',
            last_modified="old",
            pdf_sha256="a" * 64,
        )
        downloaded = SimpleNamespace(
            payload=b"%PDF-new",
            url=url,
            etag='"new"',
            last_modified="new",
        )
        candidate = IntercityFare(
            365,
            effective_date=date(2026, 10, 1),
            source_url=url,
            etag='"new"',
            last_modified="new",
            pdf_sha256="b" * 64,
        )
        download_fare_pdf.side_effect = [downloaded, downloaded]
        parse_fare_pdf_mock.return_value = candidate

        result = _refresh_fare(
            url,
            cached,
            date(2026, 10, 1),
        )

        self.assertEqual(result, candidate)

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
        self.assertIn(
            "query=38.0877707496%2C-0.6560185196",
            message,
        )
        self.assertIn("https://t.me/c/1/50", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertLessEqual(len(message), 4096)


if __name__ == "__main__":
    unittest.main()
