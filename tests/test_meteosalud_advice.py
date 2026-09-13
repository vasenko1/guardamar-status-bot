import unittest
from datetime import datetime, timedelta

from telegrambot.digest import GUARDAMAR_TIMEZONE, build_message
from telegrambot.models import ColdHealthRisk, HeatHealthRisk, MorningDigest, Warning, Weather


NOW = datetime(2026, 9, 14, 7, tzinfo=GUARDAMAR_TIMEZONE)
CASES = (
    ("heat", HeatHealthRisk, "Риск жары", "Temperaturas máximas", "💧", {
        1: ("низкий", None),
        2: ("средний", "💧 Пейте больше воды и избегайте жары в середине дня."),
        3: ("высокий", "💧 Избегайте жары и нагрузок; особое внимание детям и пожилым."),
    }),
    ("cold", ColdHealthRisk, "Риск холода", "Temperaturas mínimas", "🧥", {
        1: ("низкий", None),
        2: ("средний", "🧥 Одевайтесь теплее и избегайте длительного пребывания на холоде."),
        3: ("высокий", "🧥 Сократите время на холоде; особое внимание детям и пожилым."),
    }),
)


def _message(kind, risk, warnings=()):
    field = "heat_health_risk" if kind == "heat" else "cold_health_risk"
    digest = MorningDigest(
        weather=Weather(None, 12, 20, None, None, None),
        warnings=warnings,
        warnings_available=True,
        **{field: risk},
    )
    return build_message(digest, now=NOW)


def _warning(event, *, tomorrow=False):
    offset = timedelta(days=1) if tomorrow else timedelta()
    return Warning(event, "yellow", NOW + offset + timedelta(hours=12),
                   NOW + offset + timedelta(hours=5))


class MeteosaludAdviceTests(unittest.TestCase):
    def test_standalone_exact_copy_for_levels_zero_to_three(self):
        for kind, risk_type, label, _, icon, cases in CASES:
            for level in range(4):
                with self.subTest(kind=kind, level=level):
                    message = _message(kind, risk_type(level))
                    if level == 0:
                        self.assertNotIn(label, message)
                        self.assertNotIn(icon, message)
                        continue
                    risk_line = f"❤️‍🩹 {label} для здоровья: {cases[level][0]}"
                    self.assertEqual(message.count(risk_line), 1)
                    advice = cases[level][1]
                    if advice is None:
                        self.assertNotIn(icon, message)
                    else:
                        self.assertIn(f"{risk_line}\n   {advice}", message)
                        self.assertEqual(message.count(icon), 1)

    def test_today_matching_warning_nests_risk_then_one_advice(self):
        for kind, risk_type, label, event, icon, cases in CASES:
            for level in (2, 3):
                with self.subTest(kind=kind, level=level):
                    message = _message(kind, risk_type(level), (_warning(event),))
                    risk_line = f"❤️‍🩹 {label} для здоровья: {cases[level][0]}"
                    self.assertIn(
                        f"   {risk_line}\n      {cases[level][1]}", message
                    )
                    self.assertEqual(message.count(risk_line), 1)
                    self.assertEqual(message.count(icon), 1)
                    self.assertNotIn(f"\n{risk_line}", message)

    def test_future_or_unrelated_warning_keeps_advice_standalone(self):
        for kind, risk_type, label, event, _, cases in CASES:
            for warning in (_warning(event, tomorrow=True), _warning("Viento")):
                with self.subTest(kind=kind, warning=warning.event,
                                  tomorrow=warning.starts_at.date() != NOW.date()):
                    message = _message(kind, risk_type(2), (warning,))
                    risk_line = f"❤️‍🩹 {label} для здоровья: средний"
                    self.assertIn(f"\n{risk_line}\n   {cases[2][1]}", message)
                    self.assertNotIn(f"   {risk_line}", message)

    def test_simultaneous_heat_and_cold_have_independent_advice(self):
        message = build_message(MorningDigest(
            weather=Weather(None, 12, 20, None, None, None),
            warnings=(), warnings_available=True,
            heat_health_risk=HeatHealthRisk(2),
            cold_health_risk=ColdHealthRisk(3),
        ), now=NOW)
        self.assertIn("Риск жары для здоровья: средний\n   💧 Пейте", message)
        self.assertIn("Риск холода для здоровья: высокий\n   🧥 Сократите", message)

    def test_multiple_today_heat_warnings_do_not_repeat_advice(self):
        warnings = (
            Warning("Temperaturas máximas", "yellow", NOW + timedelta(hours=12),
                    NOW + timedelta(hours=5)),
            Warning("Temperaturas máximas", "orange", NOW + timedelta(hours=13),
                    NOW + timedelta(hours=6)),
        )
        message = _message("heat", HeatHealthRisk(2), warnings)
        self.assertEqual(message.count("Риск жары для здоровья"), 1)
        self.assertEqual(message.count("💧 Пейте больше воды"), 1)
