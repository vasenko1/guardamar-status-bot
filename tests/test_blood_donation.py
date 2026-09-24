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
    BloodDonationError,
    BloodDonationSession,
    BloodDonationState,
    MAP_URL,
    _allowed_url,
    build_alert_message,
    fetch_today_blood_donation_events,
    monitor_blood_donation_alert,
    parse_schedule,
    refresh_blood_donation_catalog,
    refresh_blood_donation_catalog_if_due,
)
from telegrambot.digest import build_event_section


MADRID = ZoneInfo("Europe/Madrid")
SOURCE_URL = (
    "https://oficina20.san.gva.es/gportal-ctcvcol-portlet/"
    "listaColectas.jsp?provincia=0007"
)


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

CANCELLED_HTML = HTML.replace(
    b"GUARDAMAR DEL SEGURA-CENTRO SANITARIO INTEGRADO",
    b"SUSPENDIDA-CENTRO SANITARIO INTEGRADO",
)
UPDATED_HTML = HTML.replace(
    b"<td>16:45-20:30</td>\n</tr>\n</table>\n\n<h3>jueves",
    b"<td>17:15-20:00</td>\n</tr>\n</table>\n\n<h3>jueves",
)


def fetch_result(payload=HTML):
    return payload, SOURCE_URL, "text/html"


def donation_session(
    day=date(2026, 10, 14),
    start="16:45",
    end="20:30",
):
    return BloodDonationSession(
        day,
        datetime.strptime(start, "%H:%M").time(),
        datetime.strptime(end, "%H:%M").time(),
        "Centro Sanitario Integrado (зона педиатрии)",
    )


class BloodDonationSourceTests(unittest.TestCase):
    def test_parses_guardamar_row_without_address(self):
        sessions = parse_schedule(HTML, date(2026, 9, 24))

        self.assertEqual(sessions, (donation_session(),))

    def test_suspended_guardamar_row_is_not_published(self):
        self.assertEqual(
            parse_schedule(CANCELLED_HTML, date(2026, 9, 24)),
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
        self.assertTrue(_allowed_url(SOURCE_URL))
        self.assertFalse(_allowed_url(
            "https://oficina20.san.gva.es/gportal-ctcvcol-portlet/"
            "listaColectas.jsp?provincia=0006"
        ))
        self.assertFalse(_allowed_url(SOURCE_URL.replace("https://", "http://")))
        self.assertFalse(_allowed_url(
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
                return_value=fetch_result(),
            ) as fetch:
                sessions = asyncio.run(
                    refresh_blood_donation_catalog(now, state_path)
                )

            self.assertEqual(sessions, (donation_session(),))
            fetch.assert_called_once()
            saved_text = state_path.read_text(encoding="utf-8")
            saved = json.loads(saved_text)
            self.assertEqual(len(saved["sessions"]), 1)
            self.assertNotIn("TORREVIEJA", saved_text)

    def test_weekly_refresh_skips_network_until_seven_days_elapsed(self):
        first = datetime(2026, 9, 24, 7, 30, tzinfo=MADRID)
        day_six = datetime(2026, 9, 30, 7, 30, tzinfo=MADRID)
        day_seven = datetime(2026, 10, 1, 7, 30, tzinfo=MADRID)

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "blood.json"
            with patch(
                "telegrambot.blood_donation.fetch_bounded",
                return_value=fetch_result(),
            ) as fetch:
                self.assertTrue(asyncio.run(
                    refresh_blood_donation_catalog_if_due(first, state_path)
                ))
                self.assertFalse(asyncio.run(
                    refresh_blood_donation_catalog_if_due(day_six, state_path)
                ))
                self.assertTrue(asyncio.run(
                    refresh_blood_donation_catalog_if_due(day_seven, state_path)
                ))

        self.assertEqual(fetch.call_count, 2)


class BloodDonationDigestTests(unittest.TestCase):
    def _state(
        self,
        path: Path,
        observed: datetime,
        session=donation_session(),
    ) -> BloodDonationState:
        state = BloodDonationState(path)
        state.replace_sessions(observed, (session,))
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

    def test_previous_afternoon_confirmation_is_used_next_morning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blood.json"
            self._state(
                path,
                datetime(2026, 10, 13, 16, 45, tzinfo=MADRID),
            )

            events = asyncio.run(fetch_today_blood_donation_events(
                datetime(2026, 10, 14, 7, 30, tzinfo=MADRID),
                path,
            ))

        self.assertEqual(events, (donation_session_to_event(donation_session()),))

    def test_two_day_old_weekly_snapshot_is_not_used_in_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blood.json"
            self._state(
                path,
                datetime(2026, 10, 12, 7, 30, tzinfo=MADRID),
            )

            events = asyncio.run(fetch_today_blood_donation_events(
                datetime(2026, 10, 14, 7, 30, tzinfo=MADRID),
                path,
            ))

        self.assertEqual(events, ())


def donation_session_to_event(session):
    from telegrambot.models import Event

    return Event(
        title="Сегодня можно сдать кровь 🩸",
        starts_at=datetime.combine(session.day, session.starts_at, tzinfo=MADRID),
        ends_at=datetime.combine(session.day, session.ends_at, tzinfo=MADRID),
        place=session.place,
    )


class BloodDonationAlertTests(unittest.IsolatedAsyncioTestCase):
    def _state(
        self,
        path: Path,
        *,
        observed=datetime(2026, 10, 8, 7, 30, tzinfo=MADRID),
        sessions=(donation_session(),),
    ) -> BloodDonationState:
        state = BloodDonationState(path)
        state.replace_sessions(observed, sessions)
        return state

    async def test_alert_control_get_publishes_once_at_1645(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            send = AsyncMock(return_value=100)
            now = datetime(2026, 10, 13, 16, 45, tzinfo=MADRID)

            with patch(
                "telegrambot.blood_donation.fetch_bounded",
                return_value=fetch_result(),
            ) as fetch:
                self.assertEqual(
                    await monitor_blood_donation_alert(state, now, send),
                    "published",
                )
                self.assertEqual(
                    await monitor_blood_donation_alert(state, now, send),
                    "duplicate",
                )

            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(
                state.read()[0].astimezone(MADRID),
                now,
            )

        send.assert_awaited_once()

    async def test_alert_does_not_publish_or_fetch_early_or_late(self):
        for hour, minute in ((16, 44), (18, 0)):
            with self.subTest(hour=hour, minute=minute):
                with tempfile.TemporaryDirectory() as directory:
                    state = self._state(Path(directory) / "blood.json")
                    send = AsyncMock()
                    with patch(
                        "telegrambot.blood_donation.fetch_bounded"
                    ) as fetch:
                        result = await monitor_blood_donation_alert(
                            state,
                            datetime(
                                2026, 10, 13, hour, minute, tzinfo=MADRID
                            ),
                            send,
                        )
                    self.assertEqual(result, "outside_window")
                    fetch.assert_not_called()
                    send.assert_not_awaited()

    async def test_no_known_tomorrow_session_skips_control_get(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(
                Path(directory) / "blood.json",
                sessions=(donation_session(day=date(2026, 10, 15)),),
            )
            send = AsyncMock()
            with patch("telegrambot.blood_donation.fetch_bounded") as fetch:
                result = await monitor_blood_donation_alert(
                    state,
                    datetime(2026, 10, 13, 16, 45, tzinfo=MADRID),
                    send,
                )

        self.assertEqual(result, "no_trigger")
        fetch.assert_not_called()
        send.assert_not_awaited()

    async def test_control_get_cancellation_suppresses_alert_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            send = AsyncMock()
            with patch(
                "telegrambot.blood_donation.fetch_bounded",
                return_value=fetch_result(CANCELLED_HTML),
            ) as fetch:
                result = await monitor_blood_donation_alert(
                    state,
                    datetime(2026, 10, 13, 16, 45, tzinfo=MADRID),
                    send,
                )

            self.assertEqual(result, "not_confirmed")
            fetch.assert_called_once()
            self.assertEqual(
                tuple(
                    item for item in state.known_sessions(
                        datetime(2026, 10, 13, 16, 45, tzinfo=MADRID)
                    )
                    if item.day == date(2026, 10, 14)
                ),
                (),
            )

        send.assert_not_awaited()

    async def test_control_get_uses_updated_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            send = AsyncMock(return_value=101)
            with patch(
                "telegrambot.blood_donation.fetch_bounded",
                return_value=fetch_result(UPDATED_HTML),
            ):
                result = await monitor_blood_donation_alert(
                    state,
                    datetime(2026, 10, 13, 16, 45, tzinfo=MADRID),
                    send,
                )

        self.assertEqual(result, "published")
        self.assertIn("🕒 <b>17:15–20:00</b>", send.await_args.args[0])

    async def test_control_failure_does_not_send_or_destroy_weekly_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            before = state.read()
            send = AsyncMock()
            with patch(
                "telegrambot.blood_donation.refresh_blood_donation_catalog",
                new=AsyncMock(side_effect=BloodDonationError(
                    "network failed", code="NETWORK"
                )),
            ):
                with self.assertRaises(BloodDonationError):
                    await monitor_blood_donation_alert(
                        state,
                        datetime(2026, 10, 13, 16, 45, tzinfo=MADRID),
                        send,
                    )

            self.assertEqual(state.read(), before)

        send.assert_not_awaited()

    async def test_definite_send_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            now = datetime(2026, 10, 13, 16, 45, tzinfo=MADRID)

            async def fail(message):
                raise RuntimeError("telegram unavailable")

            with patch(
                "telegrambot.blood_donation.fetch_bounded",
                return_value=fetch_result(),
            ) as fetch:
                with self.assertRaises(RuntimeError):
                    await monitor_blood_donation_alert(state, now, fail)

                send = AsyncMock(return_value=102)
                self.assertEqual(
                    await monitor_blood_donation_alert(state, now, send),
                    "published",
                )

            self.assertEqual(fetch.call_count, 2)
            send.assert_awaited_once()

    async def test_uncertain_send_is_not_automatically_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory) / "blood.json")
            now = datetime(2026, 10, 13, 16, 45, tzinfo=MADRID)

            async def uncertain(message):
                raise BloodDonationDeliveryUncertain()

            with patch(
                "telegrambot.blood_donation.fetch_bounded",
                return_value=fetch_result(),
            ) as fetch:
                with self.assertRaises(BloodDonationDeliveryUncertain):
                    await monitor_blood_donation_alert(state, now, uncertain)

                send = AsyncMock()
                self.assertEqual(
                    await monitor_blood_donation_alert(state, now, send),
                    "duplicate",
                )

            self.assertEqual(fetch.call_count, 1)
            send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
