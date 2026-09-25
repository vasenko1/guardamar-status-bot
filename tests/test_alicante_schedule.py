import io
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from telegrambot.alicante_schedule import (
    AlicanteFare,
    AlicanteSchedule,
    AlicanteScheduleBundle,
    AlicanteScheduleError,
    AlicanteScheduleState,
    _parse_gtfs,
    _parse_price_page,
    _search_form,
    build_alicante_message,
)
from telegrambot.branding import FOOTER
from telegrambot.state import StateError


TODAY = date(2026, 9, 25)
TOMORROW = date(2026, 9, 26)


def _gtfs_zip(*, missing=None, bad_stop=False):
    files = {
        "calendar_dates.txt": (
            "service_id,date,exception_type\n"
            "today,20260925,1\n"
            "tomorrow,20260926,1\n"
        ),
        "routes.txt": (
            "route_id,agency_id,route_short_name,route_long_name,route_type\n"
            "r1,a1,1A,ALACANT-GUARDAMAR-TORREVIEJA,3\n"
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "g,Guardamar del Segura,38.08777,-0.65602\n"
            + (
                "a,Aeropuerto de Alicante,38.33700,-0.49100\n"
                if bad_stop
                else "a,Alicante Estacion de Autobuses,38.33700,-0.49100\n"
            )
        ),
        "trips.txt": (
            "route_id,service_id,trip_id\n"
            "r1,today,t1\n"
            "r1,today,t2\n"
            "r1,tomorrow,t3\n"
            "r1,tomorrow,t4\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "t1,08:00:00,08:00:00,g,1\n"
            "t1,09:00:00,09:00:00,a,2\n"
            "t2,10:00:00,10:00:00,a,1\n"
            "t2,11:00:00,11:00:00,g,2\n"
            "t3,08:30:00,08:30:00,g,1\n"
            "t3,09:30:00,09:30:00,a,2\n"
            "t4,10:30:00,10:30:00,a,1\n"
            "t4,11:30:00,11:30:00,g,2\n"
        ),
    }
    if missing is not None:
        files.pop(missing)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


class AlicanteGtfsTests(unittest.TestCase):
    def test_extracts_today_and_tomorrow_direct_departures(self):
        schedules = _parse_gtfs(_gtfs_zip(), (TODAY, TOMORROW))
        self.assertEqual(schedules[TODAY].to_alicante, ("08:00",))
        self.assertEqual(schedules[TODAY].from_alicante, ("10:00",))
        self.assertEqual(schedules[TOMORROW].to_alicante, ("08:30",))
        self.assertEqual(schedules[TOMORROW].from_alicante, ("10:30",))

    def test_rejects_airport_as_alicante_city_endpoint(self):
        with self.assertRaises(AlicanteScheduleError):
            _parse_gtfs(_gtfs_zip(bad_stop=True), (TODAY, TOMORROW))

    def test_rejects_incomplete_gtfs(self):
        with self.assertRaises(AlicanteScheduleError):
            _parse_gtfs(_gtfs_zip(missing="stop_times.txt"), (TODAY, TOMORROW))


class AlicantePlannerTests(unittest.TestCase):
    def test_search_form_preserves_hidden_fields(self):
        page = b"""
        <form method="post" action="/info/horarios">
          <input type="hidden" name="authenticity_token" value="abc">
          <input name="venta[origen_nombre]" value="">
          <input name="venta[destino_nombre]" value="">
          <input name="venta[fecha_ida]" value="">
        </form>
        """
        action, fields = _search_form(
            page,
            "https://regular.autobusing.com/info?empresa=costa-azul&locale=es",
        )
        self.assertEqual(action, "https://regular.autobusing.com/info/horarios")
        self.assertEqual(fields["authenticity_token"], "abc")

    def test_price_parser_accepts_one_basic_price(self):
        page = """
        <table>
          <tr><th>Salida</th><th>Llegada</th><th>Precio básico</th></tr>
          <tr><td>08:00</td><td>09:10</td><td>4,20 €</td></tr>
          <tr><td>10:00</td><td>11:10</td><td>4,20 €</td></tr>
        </table>
        """.encode()
        fare = _parse_price_page(page)
        self.assertEqual(fare, AlicanteFare(420, False))

    def test_price_parser_marks_variable_prices_as_from(self):
        page = """
        <table>
          <tr><th>Departure</th><th>Arrival</th><th>Basic Price</th></tr>
          <tr><td>08:00</td><td>09:10</td><td>4.20 €</td></tr>
          <tr><td>10:00</td><td>11:10</td><td>5.00 €</td></tr>
        </table>
        """.encode()
        fare = _parse_price_page(page)
        self.assertEqual(fare, AlicanteFare(420, True))

    def test_price_parser_fails_closed_without_table_price(self):
        with self.assertRaises(AlicanteScheduleError):
            _parse_price_page(b"<html><body>4,20 EUR</body></html>")


class AlicanteCardTests(unittest.TestCase):
    def _schedule(self, fare=None):
        return AlicanteSchedule(
            service_date=TODAY,
            to_alicante=(
                "06:00", "06:50", "07:25", "08:10", "09:15",
                "09:40", "10:30",
            ),
            from_alicante=("08:00", "09:00"),
            fare=fare,
        )

    def test_card_has_date_day_wrapped_times_navigation_and_footer(self):
        message = build_alicante_message(
            self._schedule(AlicanteFare(420, False)),
            TODAY,
            "https://t.me/c/1/50",
        )
        self.assertIn("Сегодня, 25 сентября, пятница", message)
        self.assertIn("06:00 · 06:50 · 07:25 · 08:10 · 09:15\n09:40 · 10:30", message)
        self.assertIn("Билет в одну сторону:</b> 4,20 €", message)
        self.assertIn("Найти расписание на другую дату", message)
        self.assertIn("https://t.me/c/1/50", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertLessEqual(len(message), 4096)

    def test_card_uses_from_for_variable_fares(self):
        message = build_alicante_message(
            self._schedule(AlicanteFare(420, True)),
            TODAY,
            "https://t.me/c/1/50",
        )
        self.assertIn("от 4,20 €", message)

    def test_stale_accepted_card_keeps_explicit_date(self):
        schedule = AlicanteSchedule(
            service_date=date(2026, 9, 24),
            to_alicante=("08:00",),
            from_alicante=("10:00",),
        )
        message = build_alicante_message(
            schedule, TODAY, "https://t.me/c/1/50"
        )
        self.assertIn("Расписание на 24 сентября, четверг", message)
        self.assertNotIn("Сегодня, 25 сентября", message)


class AlicanteStateTests(unittest.TestCase):
    def test_round_trip_current_and_next(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alicante.json"
            state = AlicanteScheduleState(path)
            bundle = AlicanteScheduleBundle(
                current=AlicanteSchedule(
                    TODAY, ("08:00",), ("10:00",), AlicanteFare(420, False)
                ),
                next=AlicanteSchedule(
                    TOMORROW, ("08:30",), ("10:30",), AlicanteFare(430, True)
                ),
            )
            state.write(bundle)
            self.assertEqual(state.read(), bundle)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("raw_html", raw)
            self.assertNotIn("gtfs", raw)

    def test_rejects_non_consecutive_next_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = AlicanteScheduleState(Path(directory) / "alicante.json")
            with self.assertRaises(StateError):
                state.write(AlicanteScheduleBundle(
                    current=AlicanteSchedule(TODAY, ("08:00",), ("10:00",)),
                    next=AlicanteSchedule(
                        date(2026, 9, 27), ("08:00",), ("10:00",)
                    ),
                ))


if __name__ == "__main__":
    unittest.main()
