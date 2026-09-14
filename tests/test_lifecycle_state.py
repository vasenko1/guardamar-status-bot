import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.models import AirQualitySummary, PollenSummary
from telegrambot.state import PublicationState, StateError


MADRID = ZoneInfo("Europe/Madrid")


class LifecycleStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "delivery.json"
        self.now = datetime(2026, 9, 14, 7, 30, tzinfo=MADRID)
        self.state = PublicationState(self.path)
        self.state.mark_morning(self.now.date(), 100, self.now)

    def test_cams_semantic_snapshot_round_trips_and_clears(self):
        base = datetime.fromisoformat("2026-09-13T00:00:00+00:00")
        air = AirQualitySummary(
            ("PM10",), "во второй половине дня", dust_related=True, category=3
        )
        pollen = PollenSummary(("оливы",), "днём", True, "вечером")
        self.state.mark_cams_environment(self.now.date(), base, air, pollen)

        _, _, stored_base, stored_air, stored_pollen = (
            self.state.morning_environment_state(self.now.date())
        )
        self.assertEqual(stored_base, base)
        self.assertEqual(stored_air, air)
        self.assertEqual(stored_pollen, pollen)

        new_base = datetime.fromisoformat("2026-09-14T00:00:00+00:00")
        self.state.mark_cams_environment(
            self.now.date(), new_base, None, None
        )
        _, _, stored_base, stored_air, stored_pollen = (
            self.state.morning_environment_state(self.now.date())
        )
        self.assertEqual(stored_base, new_base)
        self.assertIsNone(stored_air)
        self.assertIsNone(stored_pollen)

    def test_legacy_state_without_semantic_fields_is_readable(self):
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["heat_health_level"] = 0
        document["cams_forecast_base"] = "2026-09-13T00:00:00+00:00"
        self.path.write_text(json.dumps(document), encoding="utf-8")
        heat, cold, base, air, pollen = self.state.morning_environment_state(
            self.now.date()
        )
        self.assertEqual(heat, 0)
        self.assertIsNone(cold)
        self.assertIsNotNone(base)
        self.assertIsNone(air)
        self.assertIsNone(pollen)

    def test_invalid_semantic_baseline_fails_closed(self):
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["cams_air"] = {
            "pollutants": ["PM10"],
            "period": "днём",
            "category": 99,
        }
        self.path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(StateError):
            self.state.morning_environment_state(self.now.date())


if __name__ == "__main__":
    unittest.main()
