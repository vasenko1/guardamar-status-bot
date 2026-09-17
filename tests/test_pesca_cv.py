import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.pesca_cv import (
    PescaCvSourceError,
    parse_pesca_cv_html,
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


if __name__ == "__main__":
    unittest.main()
