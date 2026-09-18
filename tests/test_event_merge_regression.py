import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.digest import build_event_section
from telegrambot.event_translations import reviewed_translation
from telegrambot.models import Event
from telegrambot.morning import _merge_events, _prefer_agenda_guardamar_venues
from telegrambot.municipal_agenda import (
    SourceEvent,
    _display_ticket_price_cents,
    _enrich_admissions,
)
from telegrambot.todo_cultura import TodoCulturaAdmission


MADRID = ZoneInfo("Europe/Madrid")
START = datetime(2026, 9, 18, 19, 0, tzinfo=MADRID)
AGENDA_URL = (
    "https://www.agendaguardamar.com/entradas/2/"
    "todos-nos-llamamos-ali-de-rainer-werner-fassbinder-1973.html"
    "?webfecha=18/09/2026&webhora=19:00&websala=2&webfuncion=181"
)


class MunicipalAdmissionRegressionTests(unittest.TestCase):
    def test_free_admission_matches_short_mupi_title_by_date_time_and_title(self):
        event = SourceEvent(
            title_es="Todos nos llamamos Alí",
            start_date=date(2026, 9, 18),
            end_date=date(2026, 9, 18),
            start_time="19:00",
            end_time=None,
            place="Casa de Cultura",
            category="event",
            sources=("mupi",),
        )
        admission = TodoCulturaAdmission(
            title_hint=(
                "19 h.: Sesión de cine en la Escola de Música con la "
                "película alemana titulada ‘Todos nos llamamos Ali’ "
                "(‘Angst essen Seele auf’, 1974)"
            ),
            price_cents=0,
            evidence=(
                "19 h.: Sesión de cine en la Escola de Música con la "
                "película alemana titulada ‘Todos nos llamamos Ali’. "
                "La entrada es gratuita con invitación. "
                "Las reservas se realizarán a través de Agenda de Guardamar."
            ),
            event_date=date(2026, 9, 18),
            start_time="19:00",
            event_dates=(date(2026, 9, 18),),
        )

        enriched = _enrich_admissions((event,), (admission,))

        self.assertEqual(enriched[0].ticket_price_cents, 0)
        self.assertIn("entrada es gratuita", enriched[0].admission_evidence)
        self.assertIn("todo_cultura_detail", enriched[0].sources)

    def test_multiple_explicit_tariffs_are_not_rendered_as_one_price(self):
        source = SourceEvent(
            title_es="Visita guiada Memoria de arena",
            start_date=date(2026, 9, 18),
            end_date=date(2026, 9, 18),
            start_time="10:00",
            end_time=None,
            place="Castillo de Guardamar",
            category="event",
            sources=("todo_cultura", "todo_cultura_detail"),
            ticket_price_cents=400,
            admission_evidence=(
                "El precio de las entradas es de 4 euros para niños, "
                "estudiantes y jubilados; y de 5 euros para el resto."
            ),
        )

        self.assertIsNone(_display_ticket_price_cents(source))

    def test_free_admission_remains_free_without_competing_tariffs(self):
        source = SourceEvent(
            title_es="Todos nos llamamos Alí",
            start_date=date(2026, 9, 18),
            end_date=date(2026, 9, 18),
            start_time="19:00",
            end_time=None,
            place="Escola de Música",
            category="event",
            ticket_price_cents=0,
            admission_evidence="La entrada es gratuita con invitación.",
        )

        self.assertEqual(_display_ticket_price_cents(source), 0)


class ReviewedTranslationRegressionTests(unittest.TestCase):
    def test_generic_memoria_title_does_not_invent_molino_route(self):
        self.assertEqual(
            reviewed_translation("Visita guiada Memoria de arena"),
            "Экскурсия «Memoria de Arena»",
        )
        self.assertIn(
            "мельнице Сан-Антонио",
            reviewed_translation(
                "Visita guiada combinada Memoria de arena: "
                "Castillo y Molino de San Antonio"
            ),
        )


class MorningVenueMergeRegressionTests(unittest.TestCase):
    def test_agenda_booking_event_repairs_conflicting_venue_and_keeps_free_price(self):
        municipal = Event(
            title="Все мы зовемся Али",
            starts_at=START,
            place="Casa de Cultura",
            ticket_price_cents=0,
        )
        agenda = Event(
            title="Все мы зовемся Али, Райнер Вернер Фассбиндер, 1973",
            starts_at=START,
            place="Escola de Música",
            ticket_url=AGENDA_URL,
        )

        municipal_events = _prefer_agenda_guardamar_venues(
            (municipal,),
            (agenda,),
        )
        merged = _merge_events(municipal_events, (agenda,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].place, "Escola de Música")
        self.assertEqual(merged[0].ticket_price_cents, 0)
        self.assertEqual(merged[0].ticket_url, AGENDA_URL)

        rendered = "\n".join(build_event_section(
            merged,
            "🎭 <b>События</b>",
        ))
        self.assertIn("Escola de Música", rendered)
        self.assertNotIn("Casa de Cultura", rendered)
        self.assertIn(
            '<a href="https://www.agendaguardamar.com/entradas/',
            rendered,
        )
        self.assertIn(">Бесплатно · Получить билет</a>", rendered)

    def test_direct_booking_replaces_same_event_agenda_detail_page(self):
        municipal = Event(
            title="Все мы зовемся Али",
            starts_at=START,
            place="Escola de Música",
            ticket_price_cents=0,
            ticket_url=(
                "https://www.agendaguardamar.com/espectaculo/2/"
                "todos-nos-llamamos-ali-de-rainer-werner-fassbinder-1973.html"
            ),
        )
        agenda = Event(
            title="Все мы зовемся Али, Райнер Вернер Фассбиндер, 1973",
            starts_at=START,
            place="Escola de Música",
            ticket_url=AGENDA_URL,
        )

        corrected = _prefer_agenda_guardamar_venues(
            (municipal,),
            (agenda,),
        )

        self.assertEqual(corrected[0].place, "Escola de Música")
        self.assertEqual(corrected[0].ticket_price_cents, 0)
        self.assertEqual(corrected[0].ticket_url, AGENDA_URL)

    def test_same_agenda_id_upgrades_booking_even_with_different_route_title(self):
        start = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)
        detail_url = (
            "https://www.agendaguardamar.com/espectaculo/12/"
            "visita-guiada-castillo-parque-alfonso-xiii-fonteta-y-rabita.html"
        )
        booking_url = (
            "https://www.agendaguardamar.com/entradas/12/"
            "visita-guiada-castillo-parque-alfonso-xiii-fonteta-y-rabita.html"
            "?webfecha=18/09/2026&webhora=10:00&websala=12&webfuncion=3"
        )
        municipal = Event(
            title="Экскурсия «Memoria de Arena»",
            starts_at=start,
            place="Castillo de Guardamar",
            ticket_url=detail_url,
        )
        agenda = Event(
            title="Экскурсия: замок, парк Альфонсо XIII, Фонтета и Рабита",
            starts_at=start,
            place="Castell",
            ticket_url=booking_url,
        )

        corrected = _prefer_agenda_guardamar_venues((municipal,), (agenda,))
        merged = _merge_events(corrected, (agenda,))

        self.assertEqual(corrected[0].title, municipal.title)
        self.assertEqual(corrected[0].place, municipal.place)
        self.assertEqual(corrected[0].ticket_url, booking_url)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].ticket_url, booking_url)

    def test_different_agenda_id_does_not_bypass_title_matching(self):
        start = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)
        detail_url = (
            "https://www.agendaguardamar.com/espectaculo/12/"
            "visita-guiada-memoria-de-arena.html"
        )
        municipal = Event(
            title="Экскурсия «Memoria de Arena»",
            starts_at=start,
            place="Castillo de Guardamar",
            ticket_url=detail_url,
        )
        other = Event(
            title="Экскурсия: другой маршрут",
            starts_at=start,
            place="Castell",
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/49/"
                "visita-guiada-castillo-y-molino-de-san-antonio.html"
                "?webfecha=18/09/2026&webhora=10:00"
            ),
        )

        corrected = _prefer_agenda_guardamar_venues((municipal,), (other,))

        self.assertEqual(corrected[0].ticket_url, detail_url)

    def test_existing_direct_agenda_booking_is_not_replaced(self):
        existing = (
            "https://www.agendaguardamar.com/entradas/9/existing.html"
            "?webfecha=18/09/2026&webhora=19:00"
        )
        municipal = Event(
            title="Concierto Alpha",
            starts_at=START,
            place="Casa de Cultura",
            ticket_url=existing,
        )
        agenda = Event(
            title="Concierto Alpha",
            starts_at=START,
            place="Casa de Cultura",
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/2/alpha.html"
                "?webfecha=18/09/2026&webhora=19:00"
            ),
        )

        corrected = _prefer_agenda_guardamar_venues(
            (municipal,),
            (agenda,),
        )

        self.assertEqual(corrected[0].ticket_url, existing)

    def test_non_agenda_ticket_url_cannot_replace_existing_venue(self):
        municipal = Event(
            title="Концерт Alpha",
            starts_at=START,
            place="Casa de Cultura",
        )
        other = Event(
            title="Концерт Alpha",
            starts_at=START,
            place="Escola de Música",
            ticket_url="https://www.giglon.com/event/alpha",
        )

        corrected = _prefer_agenda_guardamar_venues(
            (municipal,),
            (other,),
        )

        self.assertEqual(corrected[0].place, "Casa de Cultura")

    def test_existing_municipal_ticket_url_blocks_venue_override(self):
        municipal = Event(
            title="Концерт Alpha",
            starts_at=START,
            place="Casa de Cultura",
            ticket_url="https://www.giglon.com/event/alpha",
        )
        agenda = Event(
            title="Концерт Alpha",
            starts_at=START,
            place="Escola de Música",
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/2/alpha.html"
                "?webfecha=18/09/2026&webhora=19:00"
            ),
        )

        corrected = _prefer_agenda_guardamar_venues(
            (municipal,),
            (agenda,),
        )

        self.assertEqual(corrected[0].place, "Casa de Cultura")
        self.assertEqual(
            corrected[0].ticket_url,
            "https://www.giglon.com/event/alpha",
        )

    def test_generic_agenda_place_cannot_replace_specific_existing_venue(self):
        municipal = Event(
            title="Concierto Alpha",
            starts_at=START,
            place="Casa de Cultura",
        )
        agenda = Event(
            title="Concierto Alpha",
            starts_at=START,
            place="Guardamar del Segura",
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/2/alpha.html"
                "?webfecha=18/09/2026&webhora=19:00"
            ),
        )

        corrected = _prefer_agenda_guardamar_venues(
            (municipal,),
            (agenda,),
        )

        self.assertEqual(corrected[0].place, "Casa de Cultura")

    def test_exhibition_opening_keeps_title_and_more_specific_library_hall(self):
        opening = Event(
            title="Открытие выставки «Благотворительный календарь ADIMAR 2027»",
            starts_at=datetime(2026, 9, 25, 20, 0, tzinfo=MADRID),
            place="Biblioteca Pública Municipal",
            category="exhibition_opening",
        )
        exhibition = Event(
            title="Выставка фотографий благотворительного календаря ADIMAR на 2027 год",
            starts_at=None,
            place="Hall de la Biblioteca Pública Municipal",
            active_until=date(2026, 10, 16),
            category="exhibition",
            active_from=date(2026, 9, 25),
        )

        merged = _merge_events((opening,), (exhibition,))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].category, "exhibition_opening")
        self.assertTrue(merged[0].title.startswith("Открытие выставки"))
        self.assertEqual(
            merged[0].place,
            "Hall de la Biblioteca Pública Municipal",
        )
        self.assertEqual(
            merged[0].starts_at.strftime("%H:%M"),
            "20:00",
        )
        rendered = "\n".join(build_event_section(
            merged,
            "🎭 <b>События</b>",
        ))
        self.assertIn("<b>20:00</b>", rendered)
        self.assertIn("Biblioteca Municipal (Hall)", rendered)
        self.assertNotIn("До 16 октября", rendered)

    def test_ambiguous_agenda_candidates_do_not_replace_existing_venue(self):
        municipal = Event(
            title="Concierto Alpha Beta",
            starts_at=START,
            place="Casa de Cultura",
        )
        first = Event(
            title="Concierto Alpha Beta",
            starts_at=START,
            place="Escola de Música",
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/2/alpha.html"
                "?webfecha=18/09/2026&webhora=19:00"
            ),
        )
        second = Event(
            title="Concierto Alpha Beta",
            starts_at=START,
            place="Parque Reina Sofía",
            ticket_url=(
                "https://www.agendaguardamar.com/entradas/3/beta.html"
                "?webfecha=18/09/2026&webhora=19:00"
            ),
        )

        corrected = _prefer_agenda_guardamar_venues(
            (municipal,),
            (first, second),
        )

        self.assertEqual(corrected[0].place, "Casa de Cultura")


if __name__ == "__main__":
    unittest.main()
