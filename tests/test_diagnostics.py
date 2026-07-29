import unittest
import urllib.error

from telegrambot.aemet import AemetError
from telegrambot.diagnostics import (
    SourceDiagnostic,
    render_diagnostics,
    source_error,
)


class SourceDiagnosticTests(unittest.TestCase):
    def test_preserves_http_status_without_url(self):
        underlying = urllib.error.HTTPError(
            "https://secret.example/token",
            503,
            "unavailable",
            {},
            None,
        )
        wrapped = AemetError("AEMET request failed")
        wrapped.__cause__ = underlying

        item = source_error(
            "AEMET",
            "AEMET OpenData",
            wrapped,
            stage="DAY",
        )

        self.assertEqual(item.code, "AEMET-DAY-HTTP-503")
        self.assertEqual(item.description, "сервер вернул HTTP 503")
        self.assertNotIn("secret", item.render())

    def test_preserves_aemet_metadata_status(self):
        error = AemetError("AEMET did not provide a product download")
        error.api_status = 401

        item = source_error(
            "AEMET",
            "AEMET OpenData",
            error,
            stage="DAY",
        )

        self.assertEqual(item.code, "AEMET-DAY-API-401")
        self.assertIn("401", item.description)

    def test_renders_unique_operator_lines(self):
        item = SourceDiagnostic(
            "SB-NO-ACTIVE",
            "SafeBeach",
            "активных данных нет",
        )

        rendered = render_diagnostics((item, item))

        self.assertEqual(rendered.count("SB-NO-ACTIVE"), 1)
        self.assertTrue(rendered.startswith("\n\n🔧 Диагностика источников"))


if __name__ == "__main__":
    unittest.main()
