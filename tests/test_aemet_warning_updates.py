import io
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.aemet import normalize_warnings
from telegrambot.models import Warning
from telegrambot.operational_updates import (
    OperationalUpdateState,
    build_update_message,
    observe_warnings,
)

MADRID = ZoneInfo("Europe/Madrid")


def _cap(
    *,
    event="Lluvias",
    severity="Severe",
    onset="2026-09-17T03:00:00+02:00",
    expires="2026-09-17T14:59:59+02:00",
    parameter=None,
    probability="40%-70%",
    description=None,
):
    extra = ""
    if parameter is not None:
        extra += (
            "<parameter><valueName>AEMET-Meteoalerta parametro</valueName>"
            f"<value>{parameter}</value></parameter>"
        )
    if probability is not None:
        extra += (
            "<parameter><valueName>AEMET-Meteoalerta probabilidad</valueName>"
            f"<value>{probability}</value></parameter>"
        )
    description_xml = (
        f"<description>{description}</description>" if description else ""
    )
    return f'''<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <status>Actual</status><info><language>es-ES</language>
      <event>{event}</event><severity>{severity}</severity>
      <onset>{onset}</onset><expires>{expires}</expires>
      {description_xml}{extra}
      <area><areaDesc>Litoral sur de Alicante</areaDesc></area>
      </info></alert>'''.encode()


def _archive(*documents):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        for index, document in enumerate(documents):
            archive.writestr(f"warning-{index}.xml", document)
    return result.getvalue()


class AemetWarningParameterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 20, 0, tzinfo=MADRID)

    def test_p1_and_p2_survive_dedup_and_archive_order(self):
        p1 = _cap(parameter="P1;Precipitación acumulada en una hora;60 mm")
        p2 = _cap(parameter="P2;Precipitación acumulada en 12 horas;120 mm")

        forward = normalize_warnings(_archive(p1, p2), self.now)
        reverse = normalize_warnings(_archive(p2, p1), self.now)

        self.assertEqual(forward, reverse)
        self.assertEqual([item.parameter_code for item in forward], ["P1", "P2"])
        self.assertEqual([item.parameter_value for item in forward], [60.0, 120.0])
        self.assertEqual([item.parameter_unit for item in forward], ["mm", "mm"])

    def test_invalid_parameter_is_ignored_without_dropping_warning(self):
        warnings = normalize_warnings(
            _cap(parameter="P1;Precipitación acumulada en una hora;60 km/h"),
            self.now,
        )
        self.assertEqual(len(warnings), 1)
        self.assertIsNone(warnings[0].parameter_code)
        self.assertIsNone(warnings[0].parameter_value)

    def test_probability_above_seventy_is_retained(self):
        warning = normalize_warnings(
            _cap(parameter="P1;Precipitación acumulada en una hora;60 mm", probability="mayor 70%"),
            self.now,
        )[0]
        self.assertEqual(warning.probability, ">70%")


class AemetWarningUpdateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 20, 0, tzinfo=MADRID)
        self.start = datetime(2026, 9, 17, 3, 0, tzinfo=MADRID)
        self.end = datetime(2026, 9, 17, 14, 59, tzinfo=MADRID)

    def _warning(self, *, code="P1", value=60, level="orange", end=None):
        return Warning(
            event="Lluvias",
            level=level,
            starts_at=self.start,
            ends_at=end or self.end,
            probability="40–70%",
            parameter_code=code,
            parameter_value=value,
            parameter_unit="mm",
        )

    def test_legacy_state_is_enriched_silently_even_when_p1_p2_expand(self):
        state = OperationalUpdateState.empty("2026-09-16")
        state["warnings_initialized"] = True
        state["warnings"] = [{
            "event": "Lluvias",
            "level": "orange",
            "starts_at": self.start.isoformat(),
            "ends_at": self.end.isoformat(),
            "description": None,
            "probability": "40–70%",
        }]

        observe_warnings(
            state,
            (self._warning(code="P1", value=60), self._warning(code="P2", value=120)),
            self.now,
        )

        self.assertIsNone(state["warning_ready"])
        self.assertEqual(len(state["warnings"]), 2)
        self.assertEqual(
            {item["parameter_code"] for item in state["warnings"]},
            {"P1", "P2"},
        )

    def test_parameter_value_change_creates_neutral_update(self):
        state = OperationalUpdateState.empty("2026-09-16")
        state["warnings_initialized"] = True
        old = self._warning(value=40)
        state["warnings"] = [{
            "event": old.event,
            "level": old.level,
            "starts_at": old.starts_at.isoformat(),
            "ends_at": old.ends_at.isoformat(),
            "description": None,
            "probability": old.probability,
            "parameter_code": old.parameter_code,
            "parameter_value": old.parameter_value,
            "parameter_unit": old.parameter_unit,
        }]

        observe_warnings(state, (self._warning(value=60),), self.now)
        message = build_update_message(state, self.now)

        self.assertIsNotNone(state["warning_ready"])
        self.assertIn("AEMET обновила предупреждения на завтра", message)
        self.assertIn("60 л/м² за 1 час", message)

    def test_level_increase_gets_editorial_lead_and_future_heading(self):
        state = OperationalUpdateState.empty("2026-09-16")
        old = self._warning(level="yellow")
        state["warnings_initialized"] = True
        state["warnings"] = [{
            "event": old.event,
            "level": old.level,
            "starts_at": old.starts_at.isoformat(),
            "ends_at": old.ends_at.isoformat(),
            "description": None,
            "probability": old.probability,
            "parameter_code": old.parameter_code,
            "parameter_value": old.parameter_value,
            "parameter_unit": old.parameter_unit,
        }]

        observe_warnings(state, (self._warning(level="orange"),), self.now)
        message = build_update_message(state, self.now)

        self.assertIn(
            "AEMET повысила уровень предупреждения на завтра до оранжевого",
            message,
        )
        self.assertIn("<b>Актуальные предупреждения:</b>", message)
        self.assertNotIn("<b>Сейчас действует:</b>", message)

    def test_matching_p1_p2_are_one_visual_block(self):
        state = OperationalUpdateState.empty("2026-09-16")
        state["warning_ready"] = {
            "previous": [],
            "current": [],
            "cancelled": [],
        }
        for warning in (self._warning(code="P1", value=60), self._warning(code="P2", value=120)):
            state["warning_ready"]["current"].append({
                "event": warning.event,
                "level": warning.level,
                "starts_at": warning.starts_at.isoformat(),
                "ends_at": warning.ends_at.isoformat(),
                "description": None,
                "probability": warning.probability,
                "parameter_code": warning.parameter_code,
                "parameter_value": warning.parameter_value,
                "parameter_unit": warning.parameter_unit,
            })

        message = build_update_message(state, self.now)

        self.assertEqual(message.count("<b>Сильный дождь</b>"), 1)
        self.assertEqual(message.count("Вероятность: 40–70%"), 1)
        self.assertIn("60 л/м² за 1 час", message)
        self.assertIn("120 л/м² за 12 часов", message)

    def test_different_intervals_do_not_merge(self):
        state = OperationalUpdateState.empty("2026-09-16")
        first = self._warning(code="P1", value=60)
        second = self._warning(
            code="P2",
            value=120,
            end=self.end + timedelta(hours=5),
        )
        state["warning_ready"] = {
            "previous": [],
            "current": [
                {
                    "event": item.event,
                    "level": item.level,
                    "starts_at": item.starts_at.isoformat(),
                    "ends_at": item.ends_at.isoformat(),
                    "description": None,
                    "probability": item.probability,
                    "parameter_code": item.parameter_code,
                    "parameter_value": item.parameter_value,
                    "parameter_unit": item.parameter_unit,
                }
                for item in (first, second)
            ],
            "cancelled": [],
        }

        message = build_update_message(state, self.now)
        self.assertEqual(message.count("<b>Сильный дождь</b>"), 2)

    def test_above_seventy_probability_is_human_readable(self):
        warning = self._warning()
        state = OperationalUpdateState.empty("2026-09-16")
        state["warning_ready"] = {
            "previous": [],
            "current": [{
                "event": warning.event,
                "level": warning.level,
                "starts_at": warning.starts_at.isoformat(),
                "ends_at": warning.ends_at.isoformat(),
                "description": None,
                "probability": ">70%",
                "parameter_code": warning.parameter_code,
                "parameter_value": warning.parameter_value,
                "parameter_unit": warning.parameter_unit,
            }],
            "cancelled": [],
        }

        message = build_update_message(state, self.now)
        self.assertIn("Вероятность: более 70%", message)


if __name__ == "__main__":
    unittest.main()
