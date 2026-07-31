import unittest
from datetime import datetime
from pathlib import Path
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

    async def test_preview_uses_both_configured_event_catalogs(self):
        captured = {}

        async def produce(*args, diagnostics=None, **kwargs):
            captured["municipal"] = args[3]
            captured["agenda"] = kwargs["agenda_state_path"]
            return "готовый дайджест"

        with (
            patch("telegrambot.__main__.produce_message", new=produce),
            patch.dict(
                "os.environ",
                {
                    "MUNICIPAL_AGENDA_STATE_PATH": "state/municipal-test.json",
                    "AGENDA_STATE_PATH": "state/agenda-test.json",
                },
            ),
        ):
            await _produce_message(
                "key",
                datetime(2026, 8, 1, 7, 30, tzinfo=MADRID),
            )

        self.assertEqual(
            captured,
            {
                "municipal": Path("state/municipal-test.json"),
                "agenda": Path("state/agenda-test.json"),
            },
        )


if __name__ == "__main__":
    unittest.main()
