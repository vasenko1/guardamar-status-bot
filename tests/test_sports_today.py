import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.__main__ import _run_command
from telegrambot.dated_publication import DatedPublicationState
from telegrambot.models import Event
from telegrambot.sports_today import (
    SportsTodayPublication,
    produce_sports_today_publication,
)
from telegrambot.telegram import TelegramError


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 17, 8, 30, tzinfo=TZ)


def _paths(root):
    base = Path(root)
    return {
        "municipal_agenda_state_path": base / "municipal.json",
        "agenda_state_path": base / "agenda.json",
        "library_agenda_state_path": base / "library.json",
        "am_guardamar_state_path": base / "am.json",
        "facv_state_path": base / "facv.json",
        "pesca_cv_state_path": base / "pesca.json",
        "fepyc_authority_state_path": base / "fepyc.json",
        "pesca_cv_details_state_path": base / "pesca-details.json",
        "convega_state_path": base / "convega.json",
        "translation_cache_path": base / "translations.json",
    }


class SportsTodayPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_time_aware_current_day_rendering_and_ended_omission(self):
        events = (
            Event(
                "Open Dama",
                datetime(2026, 10, 17, 10, 0, tzinfo=TZ),
                place="Centro Social",
                sport="chess",
            ),
            Event(
                "Mar Costa",
                datetime(2026, 10, 17, 7, 0, tzinfo=TZ),
                ends_at=datetime(2026, 10, 17, 9, 0, tzinfo=TZ),
                place="Playas La Roqueta y Centro",
                sport="fishing",
            ),
            Event(
                "Torneo abierto",
                datetime(2026, 10, 17, 7, 30, tzinfo=TZ),
                place="Centro Social",
                sport="chess",
            ),
            Event(
                "Ya terminó",
                datetime(2026, 10, 17, 6, 0, tzinfo=TZ),
                ends_at=datetime(2026, 10, 17, 8, 0, tzinfo=TZ),
                sport="chess",
            ),
            Event(
                "Competición de jornada completa",
                None,
                active_from=NOW.date(),
                active_until=NOW.date(),
                sport="fishing",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            loader = AsyncMock(return_value=events)
            with patch(
                "telegrambot.sports_today.load_local_planning_events",
                new=loader,
            ):
                publication = await produce_sports_today_publication(
                    NOW,
                    **_paths(directory),
                )

        self.assertIsNotNone(publication)
        self.assertIn(
            "🏅 <b>Спортивные мероприятия сегодня — 17 октября</b>",
            publication.message,
        )
        self.assertIn("♟ Шахматы — Open Dama", publication.message)
        self.assertIn("Начало в 10:00", publication.message)
        self.assertIn("🎣 Спортивная рыбалка — Mar Costa", publication.message)
        self.assertIn("Идёт сейчас · до 09:00", publication.message)
        self.assertIn("Сегодня с 07:30", publication.message)
        self.assertIn("Competición de jornada completa", publication.message)
        self.assertNotIn("Ya terminó", publication.message)
        self.assertEqual(
            {event.sport for event in publication.events},
            {"chess", "fishing"},
        )
        self.assertEqual(
            loader.await_args.kwargs["required_snapshot_day"],
            NOW.date(),
        )
        self.assertFalse(loader.await_args.kwargs["include_recurring"])

    async def test_cancelled_event_is_explicit_correction_without_stale_access(self):
        cancelled = Event(
            "Провинциальные соревнования — Mar Costa",
            None,
            place="Guardamar · Playa",
            ticket_price_cents=2000,
            ticket_url="https://example.invalid/ticket",
            registration_url="https://example.invalid/register",
            access_note="регистрация открыта",
            teaser="Старое описание",
            occurrence_status="cancelled",
            sport="fishing",
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "telegrambot.sports_today.load_local_planning_events",
                new=AsyncMock(return_value=(cancelled,)),
            ):
                publication = await produce_sports_today_publication(
                    NOW,
                    **_paths(directory),
                )

        self.assertIsNotNone(publication)
        self.assertIn(
            "❌ 🎣 Спортивная рыбалка — Провинциальные соревнования — Mar Costa",
            publication.message,
        )
        self.assertIn("Событие отменено", publication.message)
        self.assertNotIn("регистрация открыта", publication.message)
        self.assertNotIn("Билет", publication.message)
        self.assertNotIn("Старое описание", publication.message)

    async def test_no_sport_returns_no_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "telegrambot.sports_today.load_local_planning_events",
                new=AsyncMock(return_value=(
                    Event(
                        "Концерт",
                        datetime(2026, 10, 17, 20, 0, tzinfo=TZ),
                    ),
                )),
            ):
                publication = await produce_sports_today_publication(
                    NOW,
                    **_paths(directory),
                )

        self.assertIsNone(publication)

    async def test_complete_renderer_fails_closed_instead_of_dropping_sport(self):
        events = tuple(
            Event(
                f"Турнир {index}",
                datetime(2026, 10, 17, 12, 0, tzinfo=TZ),
                details=(
                    "Регулярный чемпионат · "
                    + ("важный контекст " * 45),
                ),
                sport="chess",
            )
            for index in range(8)
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "telegrambot.sports_today.load_local_planning_events",
                new=AsyncMock(return_value=events),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "complete event section exceeds Telegram planning limit",
                ):
                    await produce_sports_today_publication(
                        NOW,
                        **_paths(directory),
                    )


class SportsTodayDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def _publication(self):
        event = Event(
            "♟ Шахматы — Open Dama",
            None,
            sport="chess",
        )
        return SportsTodayPublication(
            target_date=NOW.date(),
            message="🏅 Спортивные мероприятия сегодня",
            events=(event,),
        )

    async def test_confirmed_delivery_blocks_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sports.json"
            DatedPublicationState(
                state_path,
                label="sports-today",
            ).mark_sent(NOW.date(), 44)
            send = AsyncMock(return_value=55)

            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "chat",
                    "SPORTS_TODAY_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.produce_sports_today_publication",
                    new=AsyncMock(return_value=self._publication()),
                ),
                patch("telegrambot.__main__.send_message", new=send),
            ):
                clock.now.return_value = NOW
                result = await _run_command("sports-today")

        self.assertEqual(result, 0)
        send.assert_not_awaited()

    async def test_uncertain_delivery_blocks_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sports.json"
            DatedPublicationState(
                state_path,
                label="sports-today",
            ).mark_uncertain(NOW.date())
            send = AsyncMock(return_value=55)

            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "chat",
                    "SPORTS_TODAY_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.produce_sports_today_publication",
                    new=AsyncMock(return_value=self._publication()),
                ),
                patch("telegrambot.__main__.send_message", new=send),
            ):
                clock.now.return_value = NOW
                result = await _run_command("sports-today")

        self.assertEqual(result, 0)
        send.assert_not_awaited()

    async def test_success_marks_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sports.json"
            send = AsyncMock(return_value=55)

            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "chat",
                    "SPORTS_TODAY_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.produce_sports_today_publication",
                    new=AsyncMock(return_value=self._publication()),
                ),
                patch("telegrambot.__main__.send_message", new=send),
            ):
                clock.now.return_value = NOW
                result = await _run_command("sports-today")

            status = DatedPublicationState(
                state_path,
                label="sports-today",
            ).status(NOW.date())

        self.assertEqual(result, 0)
        self.assertEqual(status, "sent")
        send.assert_awaited_once()

    async def test_ambiguous_send_stays_uncertain_and_second_run_does_not_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sports.json"
            send = AsyncMock(
                side_effect=TelegramError(
                    "timeout",
                    retryable=True,
                    code="TIMEOUT",
                )
            )

            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "chat",
                    "SPORTS_TODAY_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.produce_sports_today_publication",
                    new=AsyncMock(return_value=self._publication()),
                ),
                patch("telegrambot.__main__.send_message", new=send),
            ):
                clock.now.return_value = NOW
                first = await _run_command("sports-today")
                second = await _run_command("sports-today")

            status = DatedPublicationState(
                state_path,
                label="sports-today",
            ).status(NOW.date())

        self.assertEqual((first, second), (0, 0))
        self.assertEqual(status, "uncertain")
        self.assertEqual(send.await_count, 1)

    async def test_no_sport_does_not_create_delivery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sports.json"
            with (
                patch.dict(os.environ, {
                    "SPORTS_TODAY_STATE_PATH": str(state_path),
                }),
                patch("telegrambot.__main__.datetime") as clock,
                patch(
                    "telegrambot.__main__.produce_sports_today_publication",
                    new=AsyncMock(return_value=None),
                ),
            ):
                clock.now.return_value = NOW
                result = await _run_command("sports-today")

        self.assertEqual(result, 0)
        self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
