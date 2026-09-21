import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.bathing_water import (
    BATHING_WATER_PAGE_URL,
    BathingWaterSourceError,
    _allowed_page_url,
    _allowed_report_url,
    _parse_programme_page,
    _parse_report_text,
    bathing_water_report_fingerprint,
    valid_bathing_water_report_snapshot,
    valid_bathing_water_snapshot,
)

MADRID = ZoneInfo("Europe/Madrid")


def report_text(
    *,
    period="15.06.2026 - 21.06.2026",
    centre_water="BUENA",
    roqueta_sand="BUENA",
    ortigues_sand="BUENA",
):
    header = (
        f'{"Playa":<42}'
        f'{"Análisis Agua":<20}'
        f'{"Aspecto Agua":<20}'
        f'{"Aspecto Arena":<20}'
        f'{"Enterococos":<18}'
        "Escherichia Coli"
    )
    rows = [
        ("PLAYA DE TUSALES", "EXCELENTE", "EXCELENTE", "EXCELENTE"),
        ("PLAYA DE VIVERS", "EXCELENTE", "EXCELENTE", "EXCELENTE"),
        ("PLAYA DE BABILONIA", "EXCELENTE", "EXCELENTE", "EXCELENTE"),
        ("PLAYA CENTRO", "EXCELENTE", centre_water, "EXCELENTE"),
        ("PLAYA DE LA ROQUETA", "EXCELENTE", "EXCELENTE", roqueta_sand),
        ("PLAYA DEL MONCAYO", "EXCELENTE", "EXCELENTE", "EXCELENTE"),
        ("PLAYA DE ORTIGUES", "EXCELENTE", "EXCELENTE", ortigues_sand),
    ]
    body = "\n".join(
        f"{name:<42}{analysis:<20}{water:<20}{sand:<20}{0:<18}0"
        for name, analysis, water, sand in rows
    )
    return (
        "Programa de control de las zonas de baño.\n"
        "Análisis de las aguas e inspección semanal del 1 de junio al 15 de septiembre. 2026\n"
        "Guardamar del Segura\n"
        f"Fecha: {period}\n"
        f"{header}\n"
        f"{body}\n"
        "Valoración EXCELENTE / BUENA / SUFICIENTE / INSUFICIENTE\n"
        "\fPrograma de control de les zones de bany.\n"
    )


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


class BathingWaterReportTests(unittest.TestCase):
    def _parse(self, text=None, url=None):
        return _parse_report_text(
            text or report_text(),
            report_url=url or (
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/06/report.pdf"
            ),
            report_start=datetime(2026, 6, 15, tzinfo=MADRID).date(),
            report_end=datetime(2026, 6, 21, tzinfo=MADRID).date(),
            observed_at=datetime(2026, 6, 22, 9, 2, tzinfo=MADRID),
        )

    def test_parses_seven_named_beaches_and_three_official_ratings(self):
        snapshot = self._parse()

        self.assertTrue(valid_bathing_water_report_snapshot(snapshot))
        self.assertEqual(
            [beach["name"] for beach in snapshot["beaches"]],
            [
                "Tusales", "Vivers", "Babilonia", "Centro",
                "La Roqueta", "Moncayo", "Ortigues",
            ],
        )
        centro = snapshot["beaches"][3]
        roqueta = snapshot["beaches"][4]
        ortigues = snapshot["beaches"][6]
        self.assertEqual(centro["water_analysis"], "excellent")
        self.assertEqual(centro["water_appearance"], "good")
        self.assertEqual(roqueta["sand_appearance"], "good")
        self.assertEqual(ortigues["sand_appearance"], "good")

    def test_rejects_report_period_that_disagrees_with_index(self):
        with self.assertRaises(BathingWaterSourceError) as caught:
            self._parse(report_text(period="16.06.2026 - 22.06.2026"))
        self.assertEqual(caught.exception.diagnostic_code, "REPORT-PERIOD")

    def test_rejects_missing_beach_or_unknown_rating(self):
        missing = report_text().replace(
            "PLAYA DEL MONCAYO", "PLAYA DEL CAMP"
        )
        with self.assertRaises(BathingWaterSourceError) as caught:
            self._parse(missing)
        self.assertEqual(caught.exception.diagnostic_code, "REPORT-SCHEMA")

        unknown = report_text(centre_water="REGULAR")
        with self.assertRaises(BathingWaterSourceError) as caught:
            self._parse(unknown)
        self.assertEqual(caught.exception.diagnostic_code, "REPORT-SCHEMA")

    def test_fingerprint_ignores_source_url_and_observation_time(self):
        first = self._parse()
        second = self._parse(
            url=(
                "https://www.guardamardelsegura.es/wp-content/uploads/"
                "2026/06/replacement.pdf"
            )
        )
        second["observed_at"] = datetime(
            2026, 6, 23, 9, 2, tzinfo=MADRID
        ).isoformat()
        self.assertEqual(
            bathing_water_report_fingerprint(first),
            bathing_water_report_fingerprint(second),
        )


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
