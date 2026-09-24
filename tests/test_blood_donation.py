import asyncio
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.blood_donation import (
    BloodDonationDeliveryUncertain,
    BloodDonationSession,
    BloodDonationState,
    MAP_URL,
    _is_allowed_url,
    build_alert_message,
    fetch_today_blood_donation_events,
    monitor_blood_donation_alert,
    parse_schedule,
    refresh_blood_donation_catalog,
)
from telegrambot.digest import build_event_section


MADRID = ZoneInfo("Europe/Madrid")


HTML = b"""
<html><body>
<h1>Alicante</h1>
<div>Programaci&oacute;n de las Donaciones</div>

<h3>martes, 13 de octubre</h3>
<table>
<tr><th>Poblaci&oacute;n</th><th>Ubicaci&oacute;n</th><th>Horario</th></tr>
<tr><td>TORREVIEJA</td><td>TORREVIEJA-CENTRO DE SALUD ACEQUION, CONSULTAS PEDIATRIA, C/ URBANO ARREGUI, 6</td><td>17:00-20:30</td></tr>
</table>

<h3>mi&eacute;rcoles, 14 de octubre</h3>
<table>
<tr><th>Poblaci&oacute;n</th><th>Ubicaci&oacute;n</th><th>Horario</th></tr>
<tr>
<td>GUARDAMAR DEL SEGURA</td>
<td>GUARDAMAR DEL SEGURA-CENTRO SANITARIO INTEGRADO, ZONA DE PEDIATRIA, C/ MOLIVENT, S/N</td>
<td>16:45-20:30</td>
</tr>
</table>

<h3>jueves, 15 de octubre</h3>
<table>
<tr><th>Poblaci&oacute;n</th><th>Ubicaci&oacute;n</th><th>Horario</th></tr>
<tr><td>ALMORADI</td><td>ALMORADI-CENTRO DE SALUD, C/ MAYOR, 110</td><td>16:45-20:30</td></tr>
</table>
</body></html>
"""


class BloodDonationSourceTests(unittest.TestCase):
    def test_parses_guardamar_row_without_address(self):
        sessions = parse_schedule(HTML, date(2026, 9, 24))

        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.day, date(2026, 10, 14))
        self.assertEqual(session.starts_at.strftime("%H:%M"), "16:45")
        self.assertEqual(session.ends_at.strftime("%H:%M"), "20:30")
        self.assertEqual(
            session.place,
            "Centro Sanitario Integrado (зона педиатрии)",
        )

    def test_suspended_guardamar_row_is_not_published(self):
        suspended = HTML.replace(
            b"GUARDAMAR DEL SEGURA-CENTRO SANITARIO INTEGRADO",
            b"SUSPENDIDA-CENTRO SANITARIO INTEGRADO",
        )

        self.assertEqual(
            parse_schedule(suspended, date(2026, 9, 24)),
            (),
        )

    def test_suspended_city_label_is_not_treated_as_guardamar(self):
        suspended = HTML.replace(
            b"<td>GUARDAMAR DEL SEGURA</td>",
            b"<td>GUARDAMAR DEL SEGURA (SUSPENDIDA)</td>",
        )
        self.assertEqual(
            parse_schedule(suspended, date(2026, 9, 24)),
            (),
        )

    def test_source_url_policy_is_exact(self):
        self.assertTrue(_is_allowed_url(
            "https://oficina20.san.gva.es/gportal-ctcvcol-portlet/"
            "listaColectas.jsp?provincia=0007"
        ))
        self.assertFalse(_is_allowed_url(
            "https://oficina20.san.gva.es/gportal-ctcvcol-portlet/"
            "listaColectas.jsp?provincia=0006"
        ))
        self.assertFalse(_is_allowed_url(
            "http://oficina20.san.gva.es/gportal-ctcvcol-portlet/"
            "listaColectas.jsp?provincia=0007"
        ))
        self.assertFalse(_is_allowed_url(
            "https://oficina20.san.gva.es:bad/gportal-ctcvcol-portlet/"
            "listaColectas.jsp?provincia=0007"
        ))

    def test_alert_copy_matches_reviewed_message(self):
        message = build_alert_message(parse_schedule(
            HTML, date(2026, 9, 24)
        ))

        self.assertIn("🩸 <b>Завтра в Гуардамаре можно сдать кровь</b>", message)
        self.assertIn(
            "Если вы планировали стать донором — завтра, <b>14 октября</b>",
            message,
        )
        self.assertIn("🕒 <b>16:45–20:30</b>", message)
        self.assertIn(
            f'<a href="{MAP_URL}">Centro Sanitario Integrado</a> '
            "(зона педиатрии)",
            message,
        )
        self.assertNotIn("Molivent", message)
        self.assertNotIn("Источник", message)

    def test_refresh_is_one_bounded_get_and_stores_only_guardamar_rows(self):
        now = datetime(2026, 9, 24, 7, 30, tzinfo=MADRID)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "blood.json"
            with patch(
                "telegrambot.blood_donation.fetch_bounded",
                return_value=(HTML, "https://oficina20.san.gva.es/gportal-ctcvcol-portlet/listaColectas.jsp?provincia=0007", "text/html"),
            ) as fetch:
                sessions = asyncio.run(
                    refresh_blood_donation_catalog(now, state_path)
                )

            self.assertEqual(len(sessions), 1)
            fetch.assert_called_once()
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["sessions"]), 1)
            self.assertNotIn("TORREVIEJA", state_path.read_text(encoding="utf-8"))


class BloodDonationDigestTests(unittest.TestCase):
    def _state(self, path: Path, observed: datetime) -> BloodDonationState:
        state = BloodDonationState(path)
        state.replace_sessions(
            observed,
            (
                BloodDonationSession(
                    date(2026, 10, 14),
                    datetime.strptime("16:45", "%H:%M").time(),
                    datetime.strptime("20:30", "%H:%M").time(),
                    "Centro Sanitario Integrado (зона педиатрии)",
                ),
            ),
        )
        return state

    def test_same_day_event_uses_reviewed_copy_and_exact_map(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blood.json"
            now = datetime(2026, 10, 14, 7, 30, tzinfo=MADRID)
            self._state(path, now)

            events = asyncio.run(
                fetch_today_blood_donation_events(now, path)
            )
            rendered = "\n".join(build_event_section(
                events, "📅 <b>События дня:</b>"
            ))

        self.assertIn(
            "<b>16:45–20:30</b> — Сегодня можно сдать кровь 🩸",
            rendered,
        )
        self.assertIn(
            f'📍 <a href="{MAP_URL}">'
            "Centro Sanitario Integrado (зона педиатрии)</a>",
            rendered,
        )

    def test_previous_day_snapshot_is_not_reused_in_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blood.json"
            self._state(
                path,
                datetime(2026, 10, 13, 7, 30, tzinfo=MADRID),
            )

            events = asyncio.run(fetch_today_blood_donation_events(
                datetime(2026, 10, 14, 7, 30, tzinfo=MADRID),
                path,
            ))

        self.assertEqual(events, ())


class BloodDonationAlertTests(unittest.IsolatedAsyncioTestCase):
    def _state(self, path: Path) -> BloodDonationState:
        state = BloodDonationState(path)
        state.replace_sessions(
            datetime(2026, 10, 13, 7, 30, tzinfo=MADRID),
            (
                BloodDonationSession(
                    date(2026, 10, 14),
                    datetime.strptime("16:45", "%H:%M").time(),
                    datetime.strptime("20:30", "%H:%M").time(),
                    "Centro Sanitario Integrado (зона педиатрии)",
                ),
            ),
        )
        return state

    async def test_alert_publishes_once_at_1645(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            send = AsyncMock(return_value=100)
            now = datetime(2026, 10, 13, 16, 45, tzinfo=MADRID)

            self.assertEqual(
                await monitor_blood_donation_alert(state, now, send),
                "published",
            )
            self.assertEqual(
                await monitor_blood_donation_alert(state, now, send),
                "duplicate",
            )

        send.assert_awaited_once()

    async def test_alert_does_not_publish_early_or_late(self):
        for hour, minute in ((16, 44), (18, 0)):
            with self.subTest(hour=hour, minute=minute):
                with tempfile.TemporaryDirectory() as directory:
                    state = self._state(Path(directory) / "blood.json")
                    send = AsyncMock()
                    result = await monitor_blood_donation_alert(
                        state,
                        datetime(2026, 10, 13, hour, minute, tzinfo=MADRID),
                        send,
                    )
                    self.assertEqual(result, "outside_window")
                    send.assert_not_awaited()

    async def test_definite_send_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            now = datetime(2026, 10, 13, 16, 45, tzinfo=MADRID)

            async def fail(message):
                raise RuntimeError("telegram unavailable")

            with self.assertRaises(RuntimeError):
                await monitor_blood_donation_alert(state, now, fail)

            send = AsyncMock(return_value=101)
            self.assertEqual(
                await monitor_blood_donation_alert(state, now, send),
                "published",
            )
            send.assert_awaited_once()

    async def test_uncertain_send_is_not_automatically_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            now = datetime(2026, 10, 13, 16, 45, tzinfo=MADRID)

            async def uncertain(message):
                raise BloodDonationDeliveryUncertain()

            with self.assertRaises(BloodDonationDeliveryUncertain):
                await monitor_blood_donation_alert(state, now, uncertain)

            send = AsyncMock()
            self.assertEqual(
                await monitor_blood_donation_alert(state, now, send),
                "duplicate",
            )
            send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
