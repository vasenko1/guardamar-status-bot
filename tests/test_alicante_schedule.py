import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from telegrambot.alicante_schedule import (
    AlicanteFare,
    AlicanteSchedule,
    AlicanteScheduleBundle,
    AlicanteScheduleError,
    AlicanteScheduleState,
    _parse_schedule_page,
    _search_form,
    build_alicante_message,
)
from telegrambot.branding import FOOTER
from telegrambot.state import StateError


TODAY = date(2026, 9, 25)
TOMORROW = date(2026, 9, 26)


def _planner_page(
    *,
    service_date=TODAY,
    origin="GUARDAMAR",
    destination="ALICANTE",
    rows=(("05:45", "06:25", "4,95€"), ("06:50", "07:55", "4,95€")),
    price_header="Precio",
):
    body = "".join(
        "<tr>"
        f"<td><strong>{departure}</strong></td>"
        f"<td><strong>{arrival}</strong></td>"
        f'<td class="numeric">{price}</td>'
        "</tr>"
        for departure, arrival, price in rows
    )
    return (
        "<html><body>"
        '<fieldset class="campos-valor">'
        f"<p>{service_date.strftime('%d/%m/%Y')}</p>"
        f"<p>{origin}</p><p>{destination}</p>"
        "</fieldset>"
        '<table class="horarios" id="ida">'
        "<thead><tr><th class=\"salida\">Salida</th>"
        "<th class=\"llegada\">Llegada</th>"
        f'<th class="precio numeric">{price_header}</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
        "</body></html>"
    ).encode("utf-8")


class AlicantePlannerTests(unittest.TestCase):
    def test_search_form_preserves_hidden_company(self):
        page = b"""
        <form method="post" action="/info/horarios">
          <input type="hidden" name="empresa" value="costa-azul">
          <input name="venta[origen_nombre]" value="">
          <input name="venta[destino_nombre]" value="">
          <input name="venta[fecha_ida]" value="">
          <select name="venta[tipo_iyv]"><option value="ida">Ida</option></select>
        </form>
        """
        action, fields = _search_form(
            page,
            "https://regular.autobusing.com/info?empresa=costa-azul&locale=es",
        )
        self.assertEqual(
            action,
            "https://regular.autobusing.com/info/horarios",
        )
        self.assertEqual(fields, {"empresa": "costa-azul"})

    def test_schedule_parser_reads_departures_and_exact_fare(self):
        parsed = _parse_schedule_page(
            _planner_page(),
            TODAY,
            "GUARDAMAR",
            "ALICANTE",
        )
        self.assertEqual(parsed.departures, ("05:45", "06:50"))
        self.assertEqual(parsed.fare, AlicanteFare(495, False))

    def test_schedule_parser_marks_variable_price_as_from(self):
        parsed = _parse_schedule_page(
            _planner_page(
                rows=(
                    ("05:45", "06:25", "4,95€"),
                    ("06:50", "07:55", "5,50€"),
                )
            ),
            TODAY,
            "GUARDAMAR",
            "ALICANTE",
        )
        self.assertEqual(parsed.fare, AlicanteFare(495, True))

    def test_price_markup_failure_does_not_hide_schedule(self):
        parsed = _parse_schedule_page(
            _planner_page(
                rows=(
                    ("05:45", "06:25", "consultar"),
                    ("06:50", "07:55", "consultar"),
                )
            ),
            TODAY,
            "GUARDAMAR",
            "ALICANTE",
        )
        self.assertEqual(parsed.departures, ("05:45", "06:50"))
        self.assertIsNone(parsed.fare)

    def test_route_or_date_mismatch_fails_closed(self):
        with self.assertRaises(AlicanteScheduleError):
            _parse_schedule_page(
                _planner_page(destination="TORREVIEJA"),
                TODAY,
                "GUARDAMAR",
                "ALICANTE",
            )
        with self.assertRaises(AlicanteScheduleError):
            _parse_schedule_page(
                _planner_page(service_date=TOMORROW),
                TODAY,
                "GUARDAMAR",
                "ALICANTE",
            )

    def test_missing_or_ambiguous_schedule_table_fails_closed(self):
        with self.assertRaises(AlicanteScheduleError):
            _parse_schedule_page(
                b"<html><body>25/09/2026 GUARDAMAR ALICANTE</body></html>",
                TODAY,
                "GUARDAMAR",
                "ALICANTE",
            )
        duplicate = (
            _planner_page().decode("utf-8")
            + _planner_page().decode("utf-8")
        ).encode("utf-8")
        with self.assertRaises(AlicanteScheduleError):
            _parse_schedule_page(
                duplicate,
                TODAY,
                "GUARDAMAR",
                "ALICANTE",
            )


class AlicanteCardTests(unittest.TestCase):
    def _schedule(self, fare=None):
        return AlicanteSchedule(
            service_date=TODAY,
            to_alicante=(
                "05:45",
                "06:50",
                "07:45",
                "08:15",
                "08:45",
                "09:20",
                "09:50",
            ),
            from_alicante=("06:45", "08:00"),
            fare=fare,
        )

    def test_card_has_date_day_wrapped_times_navigation_and_footer(self):
        message = build_alicante_message(
            self._schedule(AlicanteFare(495, False)),
            TODAY,
            "https://t.me/c/1/50",
        )
        self.assertIn(
            "Сегодня, 25 сентября, пятница",
            message,
        )
        self.assertIn(
            "05:45 · 06:50 · 07:45 · 08:15 · 08:45\n09:20 · 09:50",
            message,
        )
        self.assertIn(
            "Билет в одну сторону:</b> 4,95 €",
            message,
        )
        self.assertIn(
            "Найти расписание на другую дату",
            message,
        )
        self.assertIn("https://t.me/c/1/50", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertLessEqual(len(message), 4096)

    def test_card_uses_from_for_variable_fares(self):
        message = build_alicante_message(
            self._schedule(AlicanteFare(495, True)),
            TODAY,
            "https://t.me/c/1/50",
        )
        self.assertIn("от 4,95 €", message)

    def test_stale_accepted_card_keeps_explicit_date(self):
        schedule = AlicanteSchedule(
            service_date=date(2026, 9, 24),
            to_alicante=("08:00",),
            from_alicante=("10:00",),
        )
        message = build_alicante_message(
            schedule,
            TODAY,
            "https://t.me/c/1/50",
        )
        self.assertIn(
            "Расписание на 24 сентября, четверг",
            message,
        )
        self.assertNotIn(
            "Сегодня, 25 сентября",
            message,
        )


class AlicanteStateTests(unittest.TestCase):
    def test_round_trip_current_and_next(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alicante.json"
            state = AlicanteScheduleState(path)
            bundle = AlicanteScheduleBundle(
                current=AlicanteSchedule(
                    TODAY,
                    ("05:45",),
                    ("06:45",),
                    AlicanteFare(495, False),
                ),
                next=AlicanteSchedule(
                    TOMORROW,
                    ("06:00",),
                    ("06:45",),
                    AlicanteFare(495, False),
                ),
            )
            state.write(bundle)
            self.assertEqual(state.read(), bundle)
            raw = json.loads(
                path.read_text(encoding="utf-8")
            )
            self.assertNotIn("raw_html", raw)
            self.assertNotIn("planner_html", raw)

    def test_round_trip_without_tomorrow_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            state = AlicanteScheduleState(
                Path(directory) / "alicante.json"
            )
            bundle = AlicanteScheduleBundle(
                current=AlicanteSchedule(
                    TODAY,
                    ("05:45",),
                    ("06:45",),
                ),
                next=None,
            )
            state.write(bundle)
            self.assertEqual(state.read(), bundle)

    def test_rejects_non_consecutive_next_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = AlicanteScheduleState(
                Path(directory) / "alicante.json"
            )
            with self.assertRaises(StateError):
                state.write(
                    AlicanteScheduleBundle(
                        current=AlicanteSchedule(
                            TODAY,
                            ("05:45",),
                            ("06:45",),
                        ),
                        next=AlicanteSchedule(
                            date(2026, 9, 27),
                            ("06:00",),
                            ("06:45",),
                        ),
                    )
                )


if __name__ == "__main__":
    unittest.main()
