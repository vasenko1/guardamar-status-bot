import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.facv import FacvSourceError, parse_facv_html, valid_facv_snapshot


MADRID = ZoneInfo("Europe/Madrid")


def _html(rows: str) -> bytes:
    return f"""
    <html><body><table>
      <tr><th>#</th><th>Nombre</th><th>Inicio</th><th>Final</th><th>Lugar</th><th>Organizador</th><th>Bloquea</th></tr>
      {rows}
    </table></body></html>
    """.encode()


class FacvParserTests(unittest.TestCase):
    def test_keeps_only_current_future_exact_guardamar_rows(self):
        snapshot = parse_facv_html(
            _html(
                """
                <tr><td>1</td><td>Open pasado</td><td>01/09/2026</td><td>02/09/2026</td><td>Guardamar del Segura</td><td>Club Dama</td><td></td></tr>
                <tr><td>2</td><td>Open Dama Guardamar</td><td>20/09/2026</td><td>20/09/2026</td><td>Guardamar del Segura</td><td>Club Dama</td><td></td></tr>
                <tr><td>3</td><td>Open cercano</td><td>21/09/2026</td><td>21/09/2026</td><td>Torrevieja</td><td>Otro club</td><td></td></tr>
                """
            ),
            date(2026, 9, 17),
            datetime(2026, 9, 17, 16, 30, tzinfo=MADRID),
        )
        self.assertTrue(valid_facv_snapshot(snapshot))
        self.assertEqual(len(snapshot["events"]), 1)
        event = snapshot["events"][0]
        self.assertEqual(event["title"], "Open Dama Guardamar")
        self.assertEqual(event["start"], "2026-09-20")
        self.assertEqual(event["sport"], "chess")

    def test_accepts_empty_guardamar_result_when_calendar_schema_is_valid(self):
        snapshot = parse_facv_html(
            _html("<tr><td>1</td><td>Open</td><td>20/09/2026</td><td>20/09/2026</td><td>València</td><td>Club</td><td></td></tr>"),
            date(2026, 9, 17),
            datetime(2026, 9, 17, 16, 30, tzinfo=MADRID),
        )
        self.assertEqual(snapshot["events"], [])
        self.assertTrue(valid_facv_snapshot(snapshot))

    def test_fails_closed_when_table_schema_changes(self):
        payload = b"<table><tr><th>Nombre</th><th>Fecha</th></tr></table>"
        with self.assertRaises(FacvSourceError):
            parse_facv_html(
                payload,
                date(2026, 9, 17),
                datetime(2026, 9, 17, 16, 30, tzinfo=MADRID),
            )


if __name__ == "__main__":
    unittest.main()
