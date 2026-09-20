import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.bathing_water import (
    BATHING_WATER_PAGE_URL,
    BathingWaterSourceError,
    _allowed_page_url,
    _allowed_report_url,
    _parse_programme_page,
    valid_bathing_water_snapshot,
)

MADRID = ZoneInfo("Europe/Madrid")


def page(*, year=2026, report_year=2026):
    return f"""
    <html><body>
      <h2>Programa de control de las zonas de baño</h2>
      <p>Análisis de las aguas e inspección semanal del 1 de junio al
      15 de septiembre. {year}</p>
      <ul>
        <li><a href="/wp-content/uploads/{report_year}/09/latest.pdf">
        ·Fecha: 07.09.{report_year} – 13.09.{report_year}</a></li>
        <li><a href="/wp-content/uploads/{report_year}/06/first.pdf">
        ·Fecha: 15.06.{report_year} - 21.06.{report_year}</a></li>
      </ul>
      <p>Análisis de las aguas e inspección semanal del 1 de junio al
      15 de septiembre. 2025</p>
      <a href="/wp-content/uploads/2025/09/old.pdf">
      Fecha: 08.09.2025 – 14.09.2025</a>
    </body></html>
    """.encode()


class BathingWaterProgrammeTests(unittest.TestCase):
    def test_parses_current_year_and_newest_report(self):
        now = datetime(2026, 9, 20, 9, 2, tzinfo=MADRID)
        snapshot = _parse_programme_page(
            page(),
            expected_year=2026,
            observed_at=now,
        )
        self.assertEqual(snapshot["season_year"], 2026)
        self.assertEqual(snapshot["season_start"], "2026-06-01")
        self.assertEqual(snapshot["season_end"], "2026-09-15")
        self.assertEqual(snapshot["latest_report_start"], "2026-09-07")
        self.assertEqual(snapshot["latest_report_end"], "2026-09-13")
        self.assertEqual(
            snapshot["latest_report_url"],
            "https://www.guardamardelsegura.es/"
            "wp-content/uploads/2026/09/latest.pdf",
        )
        self.assertTrue(valid_bathing_water_snapshot(snapshot))

    def test_requires_exactly_one_current_year_programme(self):
        now = datetime(2027, 1, 10, 9, 2, tzinfo=MADRID)
        with self.assertRaises(BathingWaterSourceError) as caught:
            _parse_programme_page(
                page(year=2026),
                expected_year=2027,
                observed_at=now,
            )
        self.assertEqual(caught.exception.diagnostic_code, "YEAR")

    def test_report_link_must_be_official_pdf(self):
        payload = """
        <p>Análisis de las aguas e inspección semanal del
        1 de junio al 15 de septiembre. 2026</p>
        <a href="https://evil.example/report.pdf">
        Fecha: 07.09.2026 - 13.09.2026</a>
        """.encode("utf-8")
        snapshot = _parse_programme_page(
            payload,
            expected_year=2026,
            observed_at=datetime(2026, 9, 20, 9, 2, tzinfo=MADRID),
        )
        self.assertIsNone(snapshot["latest_report_url"])
        self.assertTrue(valid_bathing_water_snapshot(snapshot))

    def test_page_url_policy_is_exact_https(self):
        self.assertTrue(_allowed_page_url(BATHING_WATER_PAGE_URL))
        for value in (
            "http://www.guardamardelsegura.es/programa-de-control-de-las-zonas-de-bano/",
            "https://evil.example/programa-de-control-de-las-zonas-de-bano/",
            "https://www.guardamardelsegura.es/otra-pagina/",
        ):
            with self.subTest(value=value):
                self.assertFalse(_allowed_page_url(value))

    def test_report_url_policy_is_bounded_to_municipal_uploads(self):
        self.assertTrue(
            _allowed_report_url(
                "https://www.guardamardelsegura.es/"
                "wp-content/uploads/2026/09/report.pdf"
            )
        )
        for value in (
            "https://evil.example/wp-content/uploads/2026/09/report.pdf",
            "https://www.guardamardelsegura.es/report.pdf",
            "https://www.guardamardelsegura.es/wp-content/uploads/2026/09/report.jpg",
        ):
            with self.subTest(value=value):
                self.assertFalse(_allowed_report_url(value))


if __name__ == "__main__":
    unittest.main()
