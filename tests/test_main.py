import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from telegrambot.__main__ import _produce_message
from telegrambot.diagnostics import SourceDiagnostic


MADRID = ZoneInfo("Europe/Madrid")


class PreviewReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_appends_diagnostics_only_in_preview_wrapper(self):
        async def produce(*args, diagnostics=None, **kwargs):
            diagnostics.append(
                SourceDiagnostic(
                    "SB-NO-ACTIVE",
                    "SafeBeach",
                    "активных данных выбранных пляжей нет",
                )
            )
            return "готовый дайджест"

        with patch("telegrambot.__main__.produce_message", new=produce):
            message = await _produce_message(
                "key",
                datetime(2026, 7, 29, 10, 0, tzinfo=MADRID),
            )

        self.assertIn("готовый дайджест", message)
        self.assertIn("🔧 Диагностика источников", message)
        self.assertIn("[SB-NO-ACTIVE] SafeBeach", message)


if __name__ == "__main__":
    unittest.main()
