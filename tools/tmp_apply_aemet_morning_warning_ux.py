from pathlib import Path


def replace_between(text: str, start: str, end: str, replacement: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[:start_index] + replacement + text[end_index:]


digest_path = Path("src/telegrambot/digest.py")
digest = digest_path.read_text(encoding="utf-8")

helper = '''def _warning_parameter_line(warning: Warning) -> Optional[str]:
    """Return one compact human-readable structured CAP value."""
    if warning.parameter_code is None or warning.parameter_value is None:
        return None
    value = f"{warning.parameter_value:g}".replace(".", ",")
    code = warning.parameter_code
    if code == "P1" and warning.parameter_unit == "mm":
        return f"{value} л/м² за 1 час"
    if code == "P2" and warning.parameter_unit == "mm":
        return f"{value} л/м² за 12 часов"
    if code == "NV" and warning.parameter_unit == "cm":
        return f"Снег: {value} см за 24 часа"
    if code == "RM" and warning.parameter_unit == "km/h":
        return f"Порывы ветра: {value} км/ч"
    if code == "TA" and warning.parameter_unit == "°C":
        return f"Максимальная температура: {value} °C"
    if code == "TI" and warning.parameter_unit == "°C":
        return f"Минимальная температура: {value} °C"
    return None


'''
if "def _warning_parameter_line(" not in digest:
    marker = "def _warning_blocks(\n"
    digest = digest.replace(marker, helper + marker, 1)

new_warning_blocks = '''def _warning_blocks(
    warnings: Sequence[Warning],
    now: datetime,
    heat_health_risk: Optional[HeatHealthRisk] = None,
    air_quality: Optional[AirQualitySummary] = None,
    cold_health_risk: Optional[ColdHealthRisk] = None,
) -> list[str]:
    """Render scan-friendly AEMET warnings, grouping one visible period once."""

    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    priority = {"red": 0, "orange": 1, "yellow": 2}
    active = [
        warning for warning in warnings
        if (
            warning.ends_at is None
            or warning.ends_at.astimezone(GUARDAMAR_TIMEZONE) > now
        )
        and _warning_text(warning.event) is not None
    ]

    def display_day(warning: Warning) -> date:
        if warning.starts_at is None:
            return today
        start_day = warning.starts_at.astimezone(
            GUARDAMAR_TIMEZONE
        ).date()
        return max(start_day, today)

    ordered = sorted(
        active,
        key=lambda warning: (
            display_day(warning),
            priority.get(warning.level, 3),
            warning.starts_at or datetime.min.replace(
                tzinfo=GUARDAMAR_TIMEZONE
            ),
            warning.ends_at or datetime.max.replace(
                tzinfo=GUARDAMAR_TIMEZONE
            ),
            _warning_text(warning.event) or "",
            warning.parameter_code or "",
        ),
    )

    # Presentation grouping is intentionally separate from CAP identity.
    # P1/P2 remain distinct facts in the model/state, but one shared visible
    # period should not repeat the same event, interval, or probability.
    grouped = []
    positions = {}
    for warning in ordered:
        key = (
            display_day(warning),
            warning.level,
            warning.starts_at,
            warning.ends_at,
            warning.probability,
        )
        if key not in positions:
            positions[key] = len(grouped)
            grouped.append([key, []])
        grouped[positions[key]][1].append(warning)

    blocks = []
    heat_nested = False
    cold_nested = False
    air_nested = False

    for (
        _display_day,
        level,
        _starts_at,
        _ends_at,
        probability,
    ), items in grouped:
        dot = WARNING_DOTS.get(level, "⚠️")
        interval = _warning_interval(items[0], today)

        # CAP normally supplies a period. Preserve the established event-first
        # fallback for malformed/partial warnings with no usable interval.
        period_first = bool(interval)
        if period_first:
            blocks.append(f"{dot} <b>{html.escape(interval)}</b>")
            if probability:
                blocks.append(
                    f"   Вероятность: {html.escape(probability)}"
                )

        event_groups = []
        event_positions = {}
        for warning in items:
            label = _warning_text(warning.event) or ""
            if label not in event_positions:
                event_positions[label] = len(event_groups)
                event_groups.append([label, []])
            event_groups[event_positions[label]][1].append(warning)

        for event, event_items in event_groups:
            if period_first:
                blocks.append(f"   • <b>{html.escape(event.capitalize())}</b>")
            else:
                blocks.append(
                    f"{dot} <b>{html.escape(event.capitalize())}</b>"
                )
                if probability:
                    blocks.append(
                        f"   Вероятность: {html.escape(probability)}"
                    )

            parameter_lines = tuple(dict.fromkeys(
                line
                for item in event_items
                if (line := _warning_parameter_line(item)) is not None
            ))
            parameter_indent = "      " if period_first else "   "
            blocks.extend(
                f"{parameter_indent}{html.escape(line)}"
                for line in parameter_lines
            )

            descriptions = tuple(dict.fromkeys(
                description
                for item in event_items
                if (description := _warning_description(item)) is not None
            ))
            blocks.extend(
                f"{parameter_indent}{html.escape(description)}"
                for description in descriptions
            )

            today_block = _display_day == today
            health_indent = "      " if period_first else "   "
            if (
                today_block and event == "высокая температура"
                and heat_health_risk is not None
                and heat_health_risk.level > 0
                and not heat_nested
            ):
                lines = _health_lines(
                    _heat_health_line(heat_health_risk),
                    _HEAT_HEALTH_ADVICE.get(heat_health_risk.level),
                    nested=True,
                )
                if period_first:
                    lines = ["   " + line for line in lines]
                blocks.extend(lines)
                heat_nested = True
            if (
                today_block and event == "низкая температура"
                and cold_health_risk is not None
                and cold_health_risk.level > 0
                and not cold_nested
            ):
                lines = _health_lines(
                    _cold_health_line(cold_health_risk),
                    _COLD_HEALTH_ADVICE.get(cold_health_risk.level),
                    nested=True,
                )
                if period_first:
                    lines = ["   " + line for line in lines]
                blocks.extend(lines)
                cold_nested = True
            if (
                today_block and event == "пыль в воздухе"
                and air_quality is not None and any(
                    pollutant in {"PM10", "PM2.5"}
                    for pollutant in air_quality.pollutants
                )
            ):
                blocks.append(
                    health_indent
                    + _air_quality_line(air_quality, dust_warning=True)
                )
                air_nested = True

    return blocks, heat_nested, cold_nested, air_nested


'''
digest = replace_between(
    digest,
    "def _warning_blocks(\n",
    "def _join_ru(",
    new_warning_blocks,
)
digest_path.write_text(digest, encoding="utf-8")


operational_path = Path("src/telegrambot/operational_updates.py")
operational = operational_path.read_text(encoding="utf-8")
if "    _warning_parameter_line,\n" not in operational:
    operational = operational.replace(
        "    _warning_interval,\n",
        "    _warning_interval,\n    _warning_parameter_line,\n",
        1,
    )
if "def _warning_parameter_line(warning: Warning)" in operational:
    operational = replace_between(
        operational,
        "def _warning_parameter_line(warning: Warning)",
        "def _warning_probability_text(",
        "",
    )
operational_path.write_text(operational, encoding="utf-8")


test_path = Path("tests/test_aemet_morning_warning_ux.py")
test_path.write_text(r'''import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.digest import build_warning_section
from telegrambot.models import Warning

MADRID = ZoneInfo("Europe/Madrid")


class AemetMorningWarningUxTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 17, 7, 0, tzinfo=MADRID)
        self.start = datetime(2026, 9, 17, 3, 0, tzinfo=MADRID)
        self.end = datetime(2026, 9, 17, 14, 59, tzinfo=MADRID)

    def _warning(
        self,
        event,
        *,
        code=None,
        value=None,
        description=None,
        level="orange",
        starts_at=None,
        ends_at=None,
        probability="40–70%",
    ):
        return Warning(
            event=event,
            level=level,
            starts_at=starts_at or self.start,
            ends_at=ends_at or self.end,
            description=description,
            probability=probability,
            parameter_code=code,
            parameter_value=value,
            parameter_unit="mm" if code in {"P1", "P2"} else None,
        )

    def test_p1_p2_and_storm_share_one_period_without_duplicate_rain(self):
        message = build_warning_section(
            (
                self._warning(
                    "Lluvias",
                    code="P1",
                    value=60,
                    description="Precipitación acumulada en una hora: 60 mm.",
                ),
                self._warning(
                    "Lluvias",
                    code="P2",
                    value=120,
                    description="Precipitación acumulada en 12 horas: 120 mm.",
                ),
                self._warning("Tormentas"),
            ),
            self.now,
        )

        self.assertEqual(message.count("<b>Сегодня · 03:00–14:59</b>"), 1)
        self.assertEqual(message.count("<b>Сильный дождь</b>"), 1)
        self.assertEqual(message.count("<b>Грозы</b>"), 1)
        self.assertEqual(message.count("Вероятность: 40–70%"), 1)
        self.assertIn("60 л/м² за 1 час", message)
        self.assertIn("120 л/м² за 12 часов", message)
        self.assertNotIn("Precipitación acumulada", message)

    def test_different_periods_are_not_merged(self):
        later_start = datetime(2026, 9, 17, 15, 0, tzinfo=MADRID)
        later_end = datetime(2026, 9, 17, 19, 59, tzinfo=MADRID)
        message = build_warning_section(
            (
                self._warning("Lluvias", code="P1", value=60),
                self._warning(
                    "Lluvias",
                    code="P1",
                    value=30,
                    level="yellow",
                    starts_at=later_start,
                    ends_at=later_end,
                ),
            ),
            self.now,
        )

        self.assertIn("🟠 <b>Сегодня · 03:00–14:59</b>", message)
        self.assertIn("🟡 <b>Сегодня · 15:00–19:59</b>", message)
        self.assertEqual(message.count("<b>Сильный дождь</b>"), 2)

    def test_different_probabilities_are_not_merged(self):
        message = build_warning_section(
            (
                self._warning("Lluvias", code="P1", value=60),
                self._warning("Tormentas", probability=">70%"),
            ),
            self.now,
        )

        self.assertEqual(message.count("<b>Сегодня · 03:00–14:59</b>"), 2)
        self.assertIn("Вероятность: 40–70%", message)
        self.assertIn("Вероятность: &gt;70%", message)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")


digest_tests_path = Path("tests/test_digest.py")
digest_tests = digest_tests_path.read_text(encoding="utf-8")
replacements = [
    (
        '''        self.assertIn(\n            "🟡 <b>Грозы</b>\\n"\n            "   Сегодня · 16:00–21:59 · вероятность 40–70%",\n            message,\n        )\n''',
        '''        self.assertIn(\n            "🟡 <b>Сегодня · 16:00–21:59</b>\\n"\n            "   Вероятность: 40–70%\\n"\n            "   • <b>Грозы</b>",\n            message,\n        )\n''',
    ),
    (
        '''        self.assertIn(\n            "   Сегодня · 13:00–20:59 · вероятность 40–70%",\n            message,\n        )\n''',
        '''        self.assertIn(\n            "🟡 <b>Сегодня · 13:00–20:59</b>",\n            message,\n        )\n''',
    ),
    (
        '''        self.assertIn(\n            "   Завтра · 13:00–20:59 · вероятность 40–70%",\n            message,\n        )\n''',
        '''        self.assertIn(\n            "🟡 <b>Завтра · 13:00–20:59</b>",\n            message,\n        )\n''',
    ),
    (
        '''        red_today = message.index("🔴 <b>Грозы</b>")\n        orange_today = message.index("🟠 <b>Сильный дождь</b>")\n        yellow_today = message.index("🟡 <b>Сильный ветер</b>")\n        orange_tomorrow = message.index("🟠 <b>Высокая температура</b>")\n''',
        '''        red_today = message.index("<b>Грозы</b>")\n        orange_today = message.index("<b>Сильный дождь</b>")\n        yellow_today = message.index("<b>Сильный ветер</b>")\n        orange_tomorrow = message.index("<b>Высокая температура</b>")\n''',
    ),
    (
        '''        self.assertIn(\n            "   Сегодня · 13:00–20:59 · вероятность 40–70%\\n"\n            "🟡 <b>Высокая температура</b>\\n"\n            "   Завтра · 14:00–20:59 · вероятность 40–70%",\n            message,\n        )\n''',
        '''        self.assertIn(\n            "🟡 <b>Сегодня · 13:00–20:59</b>\\n"\n            "   Вероятность: 40–70%\\n"\n            "   • <b>Высокая температура</b>",\n            message,\n        )\n        self.assertIn(\n            "🟡 <b>Завтра · 14:00–20:59</b>\\n"\n            "   Вероятность: 40–70%\\n"\n            "   • <b>Высокая температура</b>",\n            message,\n        )\n''',
    ),
]
for old, new in replacements:
    if old not in digest_tests:
        raise SystemExit(f"expected digest test block not found: {old[:80]!r}")
    digest_tests = digest_tests.replace(old, new, 1)
digest_tests_path.write_text(digest_tests, encoding="utf-8")
