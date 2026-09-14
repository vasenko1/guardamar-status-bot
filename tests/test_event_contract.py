"""One additive event contract for independent sources and programmes."""

import asyncio
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from telegrambot.agenda import _load_agenda_snapshot, _write_agenda_snapshot
from telegrambot.digest import build_event_section
from telegrambot.event_places import event_place_is_map_safe, same_event_place
from telegrambot.library_agenda import (
    _LibraryRecord, _load_snapshot as load_library, _write_snapshot as write_library,
)
from telegrambot.models import Event
from telegrambot.morning import _merge_events
from telegrambot.municipal_agenda import (
    SourceEvent, _load_snapshot as load_municipal, _snapshot_data,
    _write_snapshot as write_municipal, fetch_today_municipal_events,
)

TZ = ZoneInfo("Europe/Madrid")
WHEN = datetime(2026, 9, 14, 18, tzinfo=TZ)


def rendered(*events):
    return "\n".join(build_event_section(events, "События"))


class AdditiveContractTests(unittest.TestCase):
    def test_three_sources_union_without_promotional_title_upgrade(self):
        generic = Event("Кино по понедельникам", WHEN,
                        place="Biblioteca Municipal")
        film = Event("Кино по понедельникам: «Respect»", WHEN,
                     duration_minutes=144, audience_label="12+",
                     details=("Драма",), ticket_price_cents=0,
                     access_note="до заполнения зала")
        library = Event("Кино по понедельникам: Respect: её голос изменил всё",
                        WHEN, WHEN.replace(hour=20),
                        teaser="Фильм показывает её путь от госпела.")
        result = _merge_events((generic,), (film,), (library,))
        self.assertEqual(len(result), 1)
        event, = result
        self.assertEqual(event.title, "Кино по понедельникам: «Respect»")
        self.assertEqual(event.place, "Biblioteca Municipal")
        self.assertEqual(event.duration_minutes, 144)
        self.assertEqual(event.audience_label, "12+")
        self.assertEqual(event.details, ("Драма",))
        self.assertIn("госпела", event.teaser)
        text = rendered(event)
        self.assertIn("Драма • 144 мин • 12+", text)
        self.assertIn("Бесплатно · до заполнения зала", text)
        self.assertNotIn("18:00–20:00", text)
        self.assertNotIn("её голос изменил всё", text)

    def test_independent_fields_and_detail_union(self):
        first = Event("Экскурсия", WHEN, place="Yacimiento de La Fonteta",
                      details=("На испанском",))
        second = Event("Экскурсия «Память песка»", WHEN,
                       meeting_point="Oficina de Turismo",
                       place_query="Yacimiento de La Fonteta, Guardamar del Segura",
                       teaser="История археологического комплекса.",
                       details=("На испанском", "10 км"))
        third = Event("Экскурсия", WHEN, ticket_price_cents=500,
                      ticket_url="https://www.agendaguardamar.com/entradas/1",
                      registration_contact="Casa de Cultura",
                      access_note="билеты также в Casa de Cultura",
                      duration_minutes=120, audience_label="8+",
                      schedule_note="Продажа билетов: 17:30–19:30",
                      participation_note="С собой: вода.")
        event, = _merge_events((first,), (second,), (third,))
        self.assertEqual(event.title, "Экскурсия «Память песка»")
        self.assertEqual(event.details, ("На испанском", "10 км"))
        self.assertEqual(event.duration_minutes, 120)
        self.assertEqual(event.ticket_price_cents, 500)
        self.assertEqual(event.access_note, "билеты также в Casa de Cultura")
        text = unquote(rendered(event))
        for fragment in (
            "На испанском • 10 км • 120 мин • 8+",
            "История археологического комплекса.",
            "🕐 Продажа билетов: 17:30–19:30",
            "📍", "Yacimiento de La Fonteta",
            "👥 Место сбора: ", "Oficina de Turismo",
            "ℹ️ С собой: вода.", "Билет 5 €", "билеты также в Casa de Cultura",
            "регистрация: Casa de Cultura",
        ):
            self.assertIn(fragment, text)

    def test_venue_map_query_meeting_dedupe_and_instruction_safety(self):
        self.assertTrue(same_event_place("Castell de Guardamar",
                                         "Castillo de Guardamar"))
        self.assertFalse(same_event_place("Yacimiento de La Fonteta",
                                          "Oficina de Turismo"))
        same = rendered(Event("Экскурсия", WHEN, place="Castillo de Guardamar",
                              meeting_point="Castell de Guardamar"))
        self.assertNotIn("👥", same)
        csj = rendered(Event("Мероприятия Centro Social Juvenil", WHEN,
                             place="Centro Social Juvenil",
                             place_query="Calle Molivent (estación de autobuses)"))
        self.assertIn("📍 <a", csj)
        self.assertIn(">Centro Social Juvenil</a>", csj)
        self.assertIn("Calle+Molivent", csj)
        self.assertNotIn(">Calle Molivent", csj)
        self.assertFalse(event_place_is_map_safe("Место старта сообщит инструктор"))
        unsafe = rendered(Event("Поход", WHEN, place="Castillo de Guardamar",
                                place_query="Место старта сообщит инструктор"))
        self.assertIn("📍 Castillo de Guardamar", unsafe)
        self.assertNotIn("<a href=", unsafe)

    def test_exhibition_csj_hike_plain_and_ticket_rows(self):
        exhibition = rendered(Event(
            "Выставка рисунков «Друзья и знакомые»", None,
            place="Biblioteca Municipal (Hall)", category="exhibition",
            teaser="Портреты, выполненные углём и карандашом.",
            schedule_note="Будни: 09:00–13:30 и 17:00–20:00",
        ))
        self.assertIn("Портреты, выполненные углём и карандашом.", exhibition)
        self.assertIn("🕐 Будни: 09:00–13:30 и 17:00–20:00", exhibition)
        csj = rendered(Event("Мероприятия Centro Social Juvenil", WHEN,
                             place="Centro Social Juvenil",
                             place_query="Calle Molivent",
                             audience_label="для молодёжи 12–30 лет",
                             teaser="Доступны настольные игры и пинг-понг.",
                             registration_contact="WhatsApp 609 00 67 54 или email juventudguardamar@gmail.com"))
        self.assertIn("для молодёжи 12–30 лет", csj)
        self.assertIn("Доступны настольные игры", csj)
        self.assertIn("juventudguardamar@gmail.com", csj)
        hike = rendered(Event("Ночной поход", WHEN,
                              details=("8 км",),
                              participation_note="С собой: спортивная обувь, вода и фонарик",
                              meeting_point="Место старта сообщит инструктор",
                              ticket_price_cents=0,
                              access_note="регистрация обязательна",
                              registration_contact="633 14 57 75"))
        self.assertIn("👥 Место старта сообщит инструктор", hike)
        self.assertIn("ℹ️ С собой: спортивная обувь", hike)
        self.assertIn("Бесплатно · регистрация обязательна · 633 14 57 75", hike)
        self.assertNotIn("query=%D0%9C", hike)
        plain = rendered(Event("Концерт", WHEN, place="Plaza de la Constitución"))
        self.assertIn("• <b>18:00</b> — Концерт", plain)
        self.assertEqual(plain.count("📍"), 1)
        self.assertNotIn("🕐", plain)
        self.assertNotIn("🎟", plain)

    def test_three_programmes_share_rich_child_renderer(self):
        events = (
            Event("Entrada de bandas", WHEN, programme_title="Fiestas del Campo",
                  programme_order=20),
            Event("Disparo de cohetes", WHEN.replace(hour=13),
                  programme_title="Fiestas del Campo", programme_order=10),
            Event("Entrada Mora", WHEN.replace(hour=20),
                  programme_title="Moros y Cristianos 2026",
                  details=("На испанском",), duration_minutes=90,
                  teaser="Начало праздничного шествия.",
                  schedule_note="Сбор участников: 19:30",
                  place="Avenida País Valencià",
                  meeting_point="Oficina de Turismo",
                  participation_note="С собой: удобная обувь.",
                  ticket_price_cents=0,
                  access_note="по приглашениям",
                  registration_contact="Casa de Cultura"),
            Event("Мастер-класс", WHEN.replace(hour=17),
                  programme_title="Semana de la Juventud",
                  programme_order=1),
        )
        text = rendered(*events)
        for title in ("Fiestas del Campo", "Moros y Cristianos 2026",
                      "Semana de la Juventud"):
            self.assertEqual(text.count("🎉 " + title), 1)
        self.assertLess(text.index("Disparo de cohetes"),
                        text.index("Entrada de bandas"))
        for fact in ("На испанском • 90 мин", "Начало праздничного шествия.",
                     "🕐 Сбор участников: 19:30", "👥 Место сбора:",
                     "ℹ️ С собой: удобная обувь.",
                     "Бесплатно · по приглашениям · регистрация: Casa de Cultura"):
            self.assertIn(fact, text)
        self.assertEqual(rendered(events[2]).count("На испанском • 90 мин"), 1)

    def test_length_guard_omits_whole_event_or_programme(self):
        rich = Event("Экскурсия", WHEN, teaser="Описание", place="Castillo",
                     schedule_note="Продажа билетов: 17:30–19:30")
        self.assertEqual(build_event_section((rich,), "События",
                                             prefix_length=3890), [])
        first = Event("Концерт", WHEN)
        programme = Event("Праздник", WHEN, programme_title="Большая программа",
                          teaser="Описание" * 100)
        text = "\n".join(build_event_section((first, programme), "События",
                                             prefix_length=3740))
        self.assertIn("Концерт", text)
        self.assertNotIn("🎉 Большая программа", text)


class SnapshotContractTests(unittest.TestCase):
    def test_legacy_official_cinema_snapshot_restores_exact_access(self):
        day = date(2026, 9, 14)
        official = SourceEvent(
            "Cine de los Lunes: RESPECT", day, day, "18:00", None,
            "Biblioteca Municipal", "event", ("turismo_html", "turismo_cinema"),
            ticket_price_cents=0, capacity_limited=True,
        )
        unrelated = SourceEvent(
            "Concierto", day, day, "20:00", None, "Teatro", "event",
            ("agenda_guardamar",), ticket_price_cents=0,
            capacity_limited=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "municipal.json"
            write_municipal(path, _snapshot_data("", "", WHEN, (official, unrelated)))
            restored = load_municipal(path)["_events"]
        self.assertEqual(restored[0].access_note, "до заполнения зала")
        self.assertIsNone(restored[1].access_note)
        self.assertIn("Бесплатно · до заполнения зала", rendered(Event(
            "Кино по понедельникам: «Respect»", WHEN,
            ticket_price_cents=restored[0].ticket_price_cents,
            capacity_limited=restored[0].capacity_limited,
            access_note=restored[0].access_note,
        )))

    def test_municipal_old_and_new_optional_fields(self):
        source = SourceEvent(
            "Visita guiada", date(2026, 9, 14), date(2026, 9, 14),
            "18:00", None, "Castillo", "event", ("turismo_html",),
            place_query="Castillo de Guardamar", meeting_point="Oficina de Turismo",
            schedule_note="Venta: 17:30–19:30", access_note="по приглашениям",
            programme_title="Semana de la Juventud", programme_order=2,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "municipal.json"
            data = _snapshot_data("", "", WHEN, (source,))
            write_municipal(path, data)
            restored, = load_municipal(path)["_events"]
            self.assertEqual(restored.place_query, source.place_query)
            self.assertEqual(restored.meeting_point, source.meeting_point)
            self.assertEqual(restored.schedule_note, source.schedule_note)
            self.assertEqual(restored.access_note, source.access_note)
            self.assertEqual(restored.programme_title, source.programme_title)
            for field in ("place_query", "meeting_point", "schedule_note",
                          "access_note", "programme_title", "programme_order"):
                data["events"][0].pop(field)
            write_municipal(path, data)
            old, = load_municipal(path)["_events"]
            self.assertIsNone(old.place_query)
            self.assertIsNone(old.meeting_point)
            self.assertIsNone(old.schedule_note)
            self.assertIsNone(old.access_note)

    def test_agenda_and_library_optional_fields_round_trip(self):
        event = Event("Концерт", WHEN, place="Театр",
                      place_query="Teatro Municipal, Guardamar del Segura",
                      meeting_point="Oficina de Turismo",
                      schedule_note="Продажа: 17:30–19:30",
                      access_note="по приглашениям", duration_minutes=90,
                      audience_label="12+", details=("На испанском",))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agenda = root / "agenda.json"
            library = root / "library.json"
            _write_agenda_snapshot(agenda, WHEN, (event,))
            (a,) = _load_agenda_snapshot(agenda)
            write_library(library, WHEN, (_LibraryRecord(
                event,
                "https://www.bibliotecaspublicas.es/guardamardelsegura/"
                "actividades-programas/Agenda-de-actividades.html", True,
            ),))
            (b,) = load_library(library)
            for restored in (a, b.event):
                self.assertEqual(restored.place_query, event.place_query)
                self.assertEqual(restored.meeting_point, event.meeting_point)
                self.assertEqual(restored.schedule_note, event.schedule_note)
                self.assertEqual(restored.access_note, event.access_note)
                self.assertEqual(restored.duration_minutes, 90)
                self.assertEqual(restored.details, ("На испанском",))

    def test_existing_csj_snapshot_normalizes_venue_and_activity_facts(self):
        source = SourceEvent(
            "Actividades del Centro Social Juvenil (CSJ)",
            date(2026, 9, 14), date(2026, 9, 14), "08:30", "14:00",
            "calle Molivent (estación de autobuses)", "event", ("todo_cultura",),
            participation_note=(
                "для молодёжи 12–30 лет; доступны настольные игры, "
                "настольный футбол, пинг-понг, аэрохоккей, игровой автомат"
            ),
            registration_contact="WhatsApp 609 00 67 54 или email juventudguardamar@gmail.com",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "municipal.json"
            cache = Path(directory) / "translations.json"
            write_municipal(path, _snapshot_data("", "", WHEN, (source,)))
            normalized, = load_municipal(path)["_events"]
            self.assertEqual(normalized.place, "Centro Social Juvenil")
            self.assertEqual(normalized.place_query, source.place)
            events = asyncio.run(fetch_today_municipal_events(
                WHEN, "", path, translation_cache_path=cache,
            ))
        text = rendered(*events)
        self.assertIn(">Centro Social Juvenil</a>", text)
        self.assertIn("calle+Molivent", text)
        self.assertIn("для молодёжи 12–30 лет", text)
        self.assertIn("Доступны настольные игры", text)
        self.assertIn("juventudguardamar@gmail.com", text)


if __name__ == "__main__":
    unittest.main()
