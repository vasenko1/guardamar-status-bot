import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from telegrambot.pharmacy import (
    PharmacyError,
    _write_catalog,
    duty_pharmacies_on,
    normalize_rota,
    refresh_pharmacy_catalog,
)

TZ = ZoneInfo("Europe/Madrid")
EXCEL_EPOCH = date(1899, 12, 30)


def _serial(day: date) -> int:
    return (day - EXCEL_EPOCH).days


def _workbook(rows) -> bytes:
    """Build a minimal inline-string XLSX like the official rota."""

    def cell(value):
        return (
            '<c t="inlineStr"><is><t>'
            + str(value)
            + "</t></is></c>"
        )

    body = "".join(
        "<row>" + "".join(cell(value) for value in row) + "</row>"
        for row in rows
    )
    sheet = (
        '<?xml version="1.0"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet.xml", sheet)
    return buffer.getvalue()


def _row(day, name, address, municipality, hours):
    return (
        _serial(day), "61", "", "02", "100596",
        name, address, municipality, hours,
    )


class RotaNormalizationTests(unittest.TestCase):
    def test_keeps_only_guardamar_rows_inside_the_window(self):
        start = date(2026, 8, 12)
        payload = _workbook([
            ("FECHA", "ZONA", "NOMBRE ZONA", "TURNO", "Nº", "NOMBRE",
             "DIRECCIÓN", "MUNICIPIO", "HORARIO"),
            _row(start, "PLANELLES MAS, ASUNCION",
                 "AV. CERVANTES, Nº29 ", "Guardamar del Segura",
                 "De 9:00 a 9:00"),
            _row(start, "OTRA FARMACIA", "CALLE UNO, 1", "Elche/Elx",
                 "De 9:00 a 9:00"),
            _row(start + timedelta(days=60), "FUTURA, LEJANA",
                 "CALLE DOS, 2", "Guardamar del Segura",
                 "De 9:00 a 9:00"),
            _row(start - timedelta(days=1), "PASADA, AYER",
                 "CALLE TRES, 3", "Guardamar del Segura",
                 "De 9:00 a 9:00"),
        ])

        records = normalize_rota(payload, start)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Planelles Mas, Asuncion")
        self.assertEqual(records[0]["address"], "Av. Cervantes, Nº29")
        self.assertEqual(records[0]["hours"], "круглосуточно (с 9:00)")
        self.assertTrue(records[0]["all_day"])

    def test_night_and_reinforcement_hours_render_as_ranges(self):
        start = date(2026, 8, 12)
        payload = _workbook([
            _row(start, "NOCHE, FARMACIA", "CALLE A, 1",
                 "Guardamar del Segura", "De 21:00 a 9:00"),
            _row(start, "DIA, FARMACIA", "CALLE B, 2",
                 "Guardamar del Segura", "De 9:00 a 22:00"),
        ])

        records = normalize_rota(payload, start)

        self.assertEqual(
            [record["hours"] for record in records],
            ["21:00–9:00", "9:00–22:00"],
        )
        self.assertFalse(any(record["all_day"] for record in records))

    def test_malformed_rows_and_workbooks_fail_closed(self):
        start = date(2026, 8, 12)
        no_hours = _workbook([
            _row(start, "SIN HORARIO", "CALLE C, 3",
                 "Guardamar del Segura", "sin datos"),
        ])
        self.assertEqual(normalize_rota(no_hours, start), ())
        with self.assertRaises(PharmacyError) as raised:
            normalize_rota(b"not a zip", start)
        self.assertEqual(
            raised.exception.diagnostic_code, "INVALID-WORKBOOK"
        )


class DutySelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_all_day_duty_first_without_duplicates(self):
        now = datetime(2026, 8, 12, 7, 30, tzinfo=TZ)
        records = (
            {"date": "2026-08-12", "name": "Дневная", "address": "A, 1",
             "hours": "9:00–22:00", "all_day": False},
            {"date": "2026-08-12", "name": "Круглосуточная",
             "address": "B, 2", "hours": "круглосуточно (с 9:00)",
             "all_day": True},
            {"date": "2026-08-12", "name": "Круглосуточная",
             "address": "B, 2", "hours": "круглосуточно (с 9:00)",
             "all_day": True},
            {"date": "2026-08-13", "name": "Завтрашняя", "address": "C, 3",
             "hours": "9:00–22:00", "all_day": False},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pharmacy.json"
            _write_catalog(path, records, now)

            duties = await duty_pharmacies_on(now, path)

        self.assertEqual(
            [(duty.name, duty.hours) for duty in duties],
            [
                ("Круглосуточная", "круглосуточно (с 9:00)"),
                ("Дневная", "9:00–22:00"),
            ],
        )

    async def test_missing_catalog_returns_no_rows(self):
        now = datetime(2026, 8, 12, 7, 30, tzinfo=TZ)
        with tempfile.TemporaryDirectory() as directory:
            duties = await duty_pharmacies_on(
                now, Path(directory) / "pharmacy.json"
            )
        self.assertEqual(duties, ())


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_writes_catalog_from_fetched_workbook(self):
        now = datetime(2026, 8, 12, 5, 40, tzinfo=TZ)
        payload = _workbook([
            _row(date(2026, 8, 12), "PLANELLES MAS, ASUNCION",
                 "AV. CERVANTES, Nº29", "Guardamar del Segura",
                 "De 9:00 a 9:00"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pharmacy.json"
            with patch(
                "telegrambot.pharmacy.fetch_bounded",
                return_value=(payload, "url", "application/octet-stream"),
            ) as fetched:
                count = await refresh_pharmacy_catalog(now, path)

            duties = await duty_pharmacies_on(now, path)

        self.assertEqual(count, 1)
        self.assertIn("guardias2026.xlsx", fetched.call_args.args[0])
        self.assertEqual(duties[0].name, "Planelles Mas, Asuncion")

    async def test_refresh_without_guardamar_rows_is_an_error(self):
        now = datetime(2026, 8, 12, 5, 40, tzinfo=TZ)
        payload = _workbook([
            _row(date(2026, 8, 12), "OTRA", "CALLE, 1", "Elche/Elx",
                 "De 9:00 a 9:00"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pharmacy.json"
            with patch(
                "telegrambot.pharmacy.fetch_bounded",
                return_value=(payload, "url", "application/octet-stream"),
            ):
                with self.assertRaises(PharmacyError) as raised:
                    await refresh_pharmacy_catalog(now, path)

        self.assertEqual(raised.exception.diagnostic_code, "NO-ROWS")


if __name__ == "__main__":
    unittest.main()
