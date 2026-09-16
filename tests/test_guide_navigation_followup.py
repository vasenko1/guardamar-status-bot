import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.airport_schedule import AirportSchedule, build_airport_message
from telegrambot.models import Event
from telegrambot.morning import _merge_events
from telegrambot.pinned import (
    AIRPORT_STOP_MAP_URL,
    PINNED_MESSAGE_KEYS,
    PINNED_PARENT_KEYS,
    _render_messages,
    build_leaf_message,
    telegram_message_link,
)


class GuideNavigationFollowupTests(unittest.TestCase):
    def test_every_non_root_managed_message_links_to_parent(self):
        chat_id = "-100123"
        messages = {
            key: number
            for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
        }
        rendered = _render_messages(chat_id, messages)

        self.assertEqual(
            set(PINNED_PARENT_KEYS),
            set(PINNED_MESSAGE_KEYS) - {"root"},
        )
        for child, parent in PINNED_PARENT_KEYS.items():
            with self.subTest(child=child, parent=parent):
                self.assertIn("⬅️", rendered[child])
                self.assertIn(
                    telegram_message_link(chat_id, messages[parent]),
                    rendered[child],
                )

    def test_static_and_dynamic_airport_cards_use_correct_stop_link(self):
        self.assertIn(AIRPORT_STOP_MAP_URL, build_leaf_message("airport"))

        schedule = AirportSchedule(
            service_date=date(2026, 9, 16),
            to_airport=("07:50",),
            from_airport=("08:45",),
            guardamar_coordinates="38.087834,-0.655759",
            airport_coordinates="38.282222222222,-0.55805555555556",
            fare=None,
        )
        message = build_airport_message(
            schedule,
            date(2026, 9, 16),
            "https://t.me/c/123/20",
        )

        self.assertIn(AIRPORT_STOP_MAP_URL, message)
        self.assertNotIn("38.282222222222%2C-0.55805555555556", message)

    def test_routine_youth_centre_hours_are_not_events_but_workshop_is(self):
        timezone = ZoneInfo("Europe/Madrid")
        routine_ru = Event(
            title="Мероприятия Центра социальной молодежи (CSJ)",
            starts_at=datetime(2026, 9, 16, 8, 30, tzinfo=timezone),
            ends_at=datetime(2026, 9, 16, 14, 0, tzinfo=timezone),
            place="Centro Social Juvenil",
        )
        routine_es = Event(
            title="Actividades del Centro Social Juvenil",
            starts_at=datetime(2026, 9, 16, 8, 30, tzinfo=timezone),
            ends_at=datetime(2026, 9, 16, 14, 0, tzinfo=timezone),
            place="Centro Social Juvenil",
        )
        workshop = Event(
            title="Мастер-класс по реалистичному рисунку для молодёжи",
            starts_at=datetime(2026, 9, 16, 18, 0, tzinfo=timezone),
            place="Centro Social Juvenil",
        )

        merged = _merge_events((routine_ru, routine_es, workshop))

        self.assertEqual(merged, (workshop,))


if __name__ == "__main__":
    unittest.main()
