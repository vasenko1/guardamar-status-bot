import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot.suma import (
    SumaCampaign,
    SumaDeliveryUncertain,
    SumaError,
    SumaState,
    _is_allowed_url,
    monitor_suma,
    parse_campaign,
)

TZ = ZoneInfo("Europe/Madrid")


MUNICIPAL_HTML = b"""
<html><body>
<h1>GUARDAMAR DEL SEGURA</h1>
<h4>Tributos puestos al cobro</h4>
<p>Tributos en plazo de cobro o proximos a iniciarse el plazo</p>
<div>IMPTO BIENES INMUEBLES URBANA; Periodo: 2026-ANUAL; Plazo de pago: Del 27/07/2026 al 08/10/2026.</div>
<div>IMPTO BIENES INMUEBLES RUSTICA; Periodo: 2026-ANUAL; Plazo de pago: Del 27/07/2026 al 08/10/2026.</div>
<div>ACTIVIDADES ECONOMICAS; Periodo: 2026-ANUAL; Plazo de pago: Del 27/07/2026 al 08/10/2026.</div>
<div>VADOS; Periodo: 2026-ANUAL; Plazo de pago: Del 27/07/2026 al 08/10/2026.</div>
</body></html>
"""

PERIOD_HTML = """
<html><body>
<h1>Periodo pago voluntario</h1>
<p>El periodo de pago de este año es del 27 de julio al 8 de octubre de 2026.</p>
<p>La fecha de cargo de domiciliaciones es el 1 de octubre.
El plazo para domiciliar el pago de sus recibos finaliza el 23 de septiembre.</p>
</body></html>
""".encode("utf-8")


def campaign(
    *,
    start=date(2026, 7, 27),
    end=date(2026, 10, 8),
    debit_deadline=date(2026, 9, 23),
    debit_charge=date(2026, 10, 1),
):
    return SumaCampaign(
        start,
        end,
        debit_deadline,
        debit_charge,
        (
            "IMPTO BIENES INMUEBLES URBANA",
            "IMPTO BIENES INMUEBLES RUSTICA",
            "ACTIVIDADES ECONOMICAS",
            "VADOS",
        ),
    )


def at(year, month, day):
    return datetime(year, month, day, 7, 30, tzinfo=TZ)


class SumaSourceTests(unittest.TestCase):
    def test_parses_and_cross_checks_current_guardamar_campaign(self):
        value = parse_campaign(MUNICIPAL_HTML, PERIOD_HTML)

        self.assertEqual(value.starts_on, date(2026, 7, 27))
        self.assertEqual(value.ends_on, date(2026, 10, 8))
        self.assertEqual(value.direct_debit_deadline, date(2026, 9, 23))
        self.assertEqual(value.direct_debit_charge, date(2026, 10, 1))
        self.assertEqual(
            value.taxes,
            (
                "IMPTO BIENES INMUEBLES URBANA",
                "IMPTO BIENES INMUEBLES RUSTICA",
                "ACTIVIDADES ECONOMICAS",
                "VADOS",
            ),
        )

    def test_multiple_period_labels_with_same_dates_are_valid(self):
        municipal = MUNICIPAL_HTML.replace(
            b"VADOS; Periodo: 2026-ANUAL;",
            b"VADOS; Periodo: 2026-SEMESTRAL-2;",
        )
        value = parse_campaign(municipal, PERIOD_HTML)

        self.assertIn("VADOS", value.taxes)
        self.assertEqual(len(value.taxes), 4)

    def test_guardamar_period_must_match_general_suma_period(self):
        municipal = MUNICIPAL_HTML.replace(
            b"08/10/2026", b"09/10/2026"
        )
        with self.assertRaises(SumaError):
            parse_campaign(municipal, PERIOD_HTML)

    def test_payment_page_requires_all_four_date_markers(self):
        broken = PERIOD_HTML.replace(
            b"La fecha de cargo de domiciliaciones",
            b"Fecha no reconocida",
        )
        with self.assertRaises(SumaError):
            parse_campaign(MUNICIPAL_HTML, broken)

    def test_url_policy_is_exact_and_guardamar_specific(self):
        self.assertTrue(_is_allowed_url(
            "https://www.suma.es/cuerpo_infmunicipal.xhtml?m=76"
        ))
        self.assertTrue(_is_allowed_url(
            "https://www.suma.es/periodo-pago-voluntario"
        ))
        self.assertFalse(_is_allowed_url(
            "https://www.suma.es/cuerpo_infmunicipal.xhtml?m=118"
        ))
        self.assertFalse(_is_allowed_url(
            "http://www.suma.es/periodo-pago-voluntario"
        ))


class SumaStateTests(unittest.TestCase):
    def test_state_write_wraps_local_io_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            with patch(
                "telegrambot.suma.tempfile.mkstemp",
                side_effect=OSError("storage unavailable"),
            ):
                with self.assertRaises(SumaError):
                    state.write([], date(2026, 9, 24))


class SumaMonitorTests(unittest.TestCase):
    def run_monitor(self, state, now, current_campaign, send):
        async def fetch():
            return current_campaign

        return asyncio.run(
            monitor_suma(
                state,
                now,
                send,
                fetch_campaign_fn=fetch,
            )
        )

    def test_first_successful_run_mid_period_is_silent_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return 1

            result = self.run_monitor(
                state,
                at(2026, 9, 24),
                campaign(),
                send,
            )

            self.assertEqual(result, "baseline")
            self.assertEqual(calls, [])
            saved = json.loads(state.path.read_text(encoding="utf-8"))
            self.assertIn("opening:2026-07-27", saved["sent"])
            self.assertIn("direct-debit:2026-09-16", saved["sent"])
            self.assertNotIn("charge:2026-10-01", saved["sent"])
            self.assertNotIn("final:2026-10-07", saved["sent"])

    def test_opening_notice_only_happens_on_exact_start_date(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return len(calls)

            self.assertEqual(
                self.run_monitor(state, at(2026, 7, 20), campaign(), send),
                "baseline",
            )
            self.assertEqual(
                self.run_monitor(state, at(2026, 7, 27), campaign(), send),
                "published",
            )
            self.assertEqual(len(calls), 1)
            self.assertIn("Открыт период оплаты SUMA", calls[0])
            self.assertIn("8 октября", calls[0])
            self.assertIn("IBI urbana", calls[0])
            self.assertIn("IAE", calls[0])

    def test_direct_debit_reminder_is_exactly_seven_days_before_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return 1

            self.run_monitor(state, at(2026, 9, 1), campaign(), send)
            result = self.run_monitor(
                state,
                at(2026, 9, 16),
                campaign(),
                send,
            )

            self.assertEqual(result, "published")
            self.assertEqual(len(calls), 1)
            self.assertIn("23 сентября", calls[0])
            self.assertIn("1 октября", calls[0])
            self.assertIn("domiciliación", calls[0])

    def test_october_first_and_seventh_are_the_next_notices_after_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return len(calls)

            self.assertEqual(
                self.run_monitor(state, at(2026, 9, 24), campaign(), send),
                "baseline",
            )
            self.assertEqual(
                self.run_monitor(state, at(2026, 10, 1), campaign(), send),
                "published",
            )
            self.assertIn("сегодня списание", calls[-1])
            self.assertIn("8 октября", calls[-1])

            self.assertEqual(
                self.run_monitor(state, at(2026, 10, 7), campaign(), send),
                "published",
            )
            self.assertIn("завтра заканчивается срок оплаты", calls[-1])
            self.assertIn("8 октября", calls[-1])
            self.assertEqual(len(calls), 2)

    def test_no_trigger_does_not_rewrite_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")

            async def send(message):
                return 1

            self.run_monitor(state, at(2026, 9, 1), campaign(), send)
            original = state.path.read_bytes()

            with patch.object(state, "write", wraps=state.write) as write:
                result = self.run_monitor(
                    state,
                    at(2026, 9, 2),
                    campaign(),
                    send,
                )

            self.assertEqual(result, "no_trigger")
            write.assert_not_called()
            self.assertEqual(state.path.read_bytes(), original)

    def test_missed_trigger_is_never_sent_retroactively(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return 1

            self.run_monitor(state, at(2026, 9, 1), campaign(), send)
            result = self.run_monitor(
                state,
                at(2026, 9, 17),
                campaign(),
                send,
            )

            self.assertEqual(result, "no_trigger")
            self.assertEqual(calls, [])

    def test_revised_future_deadline_gets_a_new_exact_date_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return 1

            self.run_monitor(state, at(2026, 9, 24), campaign(), send)
            revised = campaign(end=date(2026, 10, 15))
            result = self.run_monitor(
                state,
                at(2026, 10, 14),
                revised,
                send,
            )

            self.assertEqual(result, "published")
            self.assertEqual(len(calls), 1)
            self.assertIn("15 октября", calls[0])

    def test_definite_delivery_failure_remains_retryable_same_day(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")

            async def quiet_send(message):
                return 1

            self.run_monitor(state, at(2026, 9, 24), campaign(), quiet_send)

            async def fail(message):
                raise RuntimeError("telegram unavailable")

            with self.assertRaises(RuntimeError):
                self.run_monitor(
                    state,
                    at(2026, 10, 1),
                    campaign(),
                    fail,
                )

            calls = []

            async def send(message):
                calls.append(message)
                return 2

            self.assertEqual(
                self.run_monitor(state, at(2026, 10, 1), campaign(), send),
                "published",
            )
            self.assertEqual(len(calls), 1)

    def test_uncertain_delivery_is_not_automatically_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")

            async def quiet_send(message):
                return 1

            self.run_monitor(state, at(2026, 9, 24), campaign(), quiet_send)

            async def uncertain(message):
                raise SumaDeliveryUncertain()

            with self.assertRaises(SumaDeliveryUncertain):
                self.run_monitor(
                    state,
                    at(2026, 10, 1),
                    campaign(),
                    uncertain,
                )

            calls = []

            async def send(message):
                calls.append(message)
                return 2

            self.assertEqual(
                self.run_monitor(state, at(2026, 10, 1), campaign(), send),
                "duplicate",
            )
            self.assertEqual(calls, [])

    def test_charge_on_final_day_uses_last_day_wording(self):
        special = campaign(
            end=date(2026, 10, 1),
            debit_charge=date(2026, 10, 1),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return 1

            self.run_monitor(state, at(2026, 9, 24), special, send)
            self.assertEqual(
                self.run_monitor(state, at(2026, 10, 1), special, send),
                "published",
            )
            self.assertEqual(len(calls), 1)
            self.assertIn("сегодня также последний день", calls[0])
            self.assertNotIn("0 дней", calls[0])

    def test_charge_wins_if_charge_and_final_reminder_share_a_date(self):
        special = campaign(
            end=date(2026, 10, 2),
            debit_charge=date(2026, 10, 1),
        )
        with tempfile.TemporaryDirectory() as directory:
            state = SumaState(Path(directory) / "suma.json")
            calls = []

            async def send(message):
                calls.append(message)
                return 1

            self.run_monitor(state, at(2026, 9, 24), special, send)
            self.assertEqual(
                self.run_monitor(state, at(2026, 10, 1), special, send),
                "published",
            )
            self.assertEqual(len(calls), 1)
            self.assertIn("сегодня списание", calls[0])
            self.assertIn("завтра, 2 октября", calls[0])


if __name__ == "__main__":
    unittest.main()
