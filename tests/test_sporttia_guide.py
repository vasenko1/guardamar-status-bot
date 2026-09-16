import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.guide import GuideState
from telegrambot.pinned import (
    PinnedGuideState,
    build_activities,
    build_sport_activity,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.sporttia import (
    SPORTTIA_CENTER_URL,
    SPORT_ACTIVITY_KEYS,
    SporttiaSourceError,
    _allowed_sporttia_url,
    _extract_sporttia_catalog,
    fetch_sporttia_catalog,
    merge_sporttia_catalog,
    select_sport_groups,
    valid_sporttia_snapshot,
)


MADRID = ZoneInfo("Europe/Madrid")


def sporttia_html():
    rows = [
        (
            85509,
            "7. JUDO. Primer turno. Nacidos entre 2011-2020. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Miércoles y viernes de 17:00 a 18:30 horas.",
                "Clases en Palau Sant Jaume.",
                "La distribución de los grupos puede haber variaciones según criterios del Club.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85510,
            "8. JUDO. Segundo turno. Nacidos entre 2011 y 2020. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Miércoles y viernes de 18:30 a 20:00 horas.",
                "Clases en Palau Sant Jaume.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85516,
            "5. GIMNASIA RÍTMICA. Primer turno. Nacidos entre 2011-2015. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Lunes y miércoles de 16:15 a 17:15 horas.",
                "Clases en Palau Sant Jaume.",
                "Los turnos puede sufrir variaciones según criterios técnicos.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85518,
            "11. MULTIDEPORTE PRIMER TURNO. Nacidos en 2019 Y 2020. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Lunes, miércoles y viernes de 16:30 a 17:30 horas.",
                "Clases en Palau Sant Jaume.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85522,
            "MULTIDEPORTE INCLUSIVO. PRIMER TURNO. ALUMNO CON AUTONOMIA. (Temp. 2026/2027) - Mayores de 6 años",
            [
                "NUEVAS INSCRIPCIONES: 01/10/26 al 31/05/27 (o hasta completar inscripciones)",
                "Sábado de 10 a 11 horas.",
                "Clases en Palau Sant Jaume. Sala Polivalente nº1",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85514,
            "4. GIMNASIA MAYORES. PRIMER TURNO (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Lunes y miércoles de 09:30 a 11:00 horas y viernes de 09:00 a 10:00 horas.",
                "Clases en Palau Sant Jaume.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 30 jun 2027",
        ),
        (
            85513,
            "2. GIMNASIA ASOCIACIÓN MUJERES DE GUARDAMAR. TURNO ÚNICO (temp 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Lunes y miércoles de 17:30 a 19:00 horas.",
                "Clases en Palau Sant Jaume.",
                "Se deberá aportar certificado médico correspondiente.",
                "Además se deberá aportar justificante o recibo de la cuota de socia de la asociación.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85508,
            "DEPORTE +. Nacidos entre 2011 y 2017. (temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Martes y jueves de 19:30 a 21:00 horas.",
                "Clases en Complejo Deportivo Les Raboses. Pista de atletismo y campo de césped natural nº2",
                "Rugby flag, circuito de obstáculos y atletismo.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85524,
            "9. PSICOMOTRICIDAD. Primer turno. Nacidos en 2022 Y 2023. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Martes y jueves de 17:15 a 18:15 horas.",
                "Clases en CEIP MOLIVENT.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85525,
            "10. PSICOMOTRICIDAD. Segundo turno. Nacidos en 2021 y 2022. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Martes y jueves de 18:15 a 19:15 horas.",
                "Clases en CEIP MOLIVENT.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
    ]
    bodies = []
    for index, (activity_id, title, paragraphs, season) in enumerate(rows, 1):
        details = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        bodies.append(
            f'<tbody id="oferta-1509-test-{index}"><tr>'
            f'<td><a href="https://play.sporttia.com/activities/{activity_id}">{title}</a>'
            f'<details>{details}</details></td>'
            f'<td>{season}</td><td><span>Abierta</span></td>'
            '</tr></tbody>'
        )
    return (
        '<html><body><div data-offer-blocks data-center-ids="1509">'
        + "".join(bodies)
        + '</div></body></html>'
    ).encode("utf-8")


def sample_catalog(moment):
    return _extract_sporttia_catalog(sporttia_html(), moment)


class SporttiaSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_url_policy_is_one_exact_https_page(self):
        self.assertTrue(_allowed_sporttia_url(SPORTTIA_CENTER_URL))
        for invalid in (
            "http://sporttia.com/centros/ayuntamiento-guardamar-del-segura",
            "https://www.sporttia.com/centros/ayuntamiento-guardamar-del-segura",
            "https://sporttia.com/centros/other",
            "https://sporttia.com/centros/ayuntamiento-guardamar-del-segura?x=1",
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(_allowed_sporttia_url(invalid))

    async def test_fetch_is_exactly_one_bounded_non_redirecting_get(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        with patch(
            "telegrambot.sporttia.fetch_bounded",
            return_value=(sporttia_html(), SPORTTIA_CENTER_URL, "text/html"),
        ) as fetch:
            result = await fetch_sporttia_catalog(moment)
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(fetch.call_args.kwargs["follow_redirects"])
        self.assertEqual(fetch.call_args.args[0], SPORTTIA_CENTER_URL)
        self.assertTrue(valid_sporttia_snapshot(result))

    def test_parser_keeps_only_target_facts_and_ignores_abierta(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        result = sample_catalog(moment)
        keys = {item["key"] for item in result["activities"]}
        self.assertEqual(keys, set(SPORT_ACTIVITY_KEYS))
        self.assertEqual(
            len([item for item in result["activities"] if item["key"] == "judo"]),
            2,
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in result["activities"]
                    if item["key"] == "psychomotricity"
                ]
            ),
            2,
        )
        judo = next(item for item in result["activities"] if item["source_id"] == 85509)
        self.assertEqual(judo["schedule"], "Ср и Пт · 17:00–18:30")
        self.assertEqual(judo["venue"], "Palau Sant Jaume")
        self.assertEqual(judo["audience"], "2011–2020 г.р.")
        deporte = next(
            item for item in result["activities"] if item["key"] == "deporte_plus"
        )
        self.assertEqual(deporte["group_order"], 1)
        self.assertEqual(deporte["audience"], "2011–2017 г.р.")
        self.assertIn("Pista de atletismo", deporte["venue"])
        serialized = str(result)
        self.assertNotIn("Abierta", serialized)
        self.assertNotIn("€", serialized)

    def test_missing_offer_structure_is_rejected(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        with self.assertRaises(SporttiaSourceError):
            _extract_sporttia_catalog(b"<html></html>", moment)

    def test_last_good_survives_closed_registration_until_season_end(self):
        previous_moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        current_moment = datetime(2026, 10, 2, 16, 30, tzinfo=MADRID)
        previous = sample_catalog(previous_moment)
        current = {
            "observed_at": current_moment.isoformat(),
            "activities": [],
        }
        merged = merge_sporttia_catalog(previous, current, date(2026, 10, 2))
        self.assertEqual(len(merged["activities"]), len(previous["activities"]))
        expired = merge_sporttia_catalog(previous, current, date(2027, 7, 1))
        self.assertEqual(expired["activities"], [])

    def test_current_or_nearest_future_season_is_selected(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        catalog = sample_catalog(moment)
        future = select_sport_groups(catalog, "judo", date(2026, 9, 16))
        current = select_sport_groups(catalog, "judo", date(2026, 10, 2))
        self.assertEqual(len(future), 2)
        self.assertEqual(len(current), 2)
        psychomotricity = select_sport_groups(
            catalog, "psychomotricity", date(2026, 9, 16)
        )
        self.assertEqual(len(psychomotricity), 2)
        self.assertEqual(
            [group["audience"] for group in psychomotricity],
            ["2022–2023 г.р.", "2021–2022 г.р."],
        )


class SporttiaPinnedTests(unittest.IsolatedAsyncioTestCase):
    def test_activity_card_is_source_driven_compact_and_price_free(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        catalog = sample_catalog(moment)
        card = build_sport_activity(
            "judo",
            catalog,
            date(2026, 9, 16),
            "https://t.me/c/123/50",
        )
        self.assertIn("🥋 <b>Дзюдо</b>", card)
        self.assertIn("Ср и Пт · 17:00–18:30", card)
        self.assertIn("Ср и Пт · 18:30–20:00", card)
        self.assertIn("Palau Sant Jaume", card)
        self.assertIn("https://maps.app.goo.gl/Jp7EA9RqrZQPcVq17", card)
        self.assertIn("Запись:</b> до 30 сентября 2026", card)
        self.assertIn("спортивная медсправка", card)
        self.assertIn("https://t.me/c/123/50", card)
        self.assertNotIn("Abierta", card)
        self.assertNotIn("€", card)

    def test_deporte_plus_and_psychomotricity_use_their_internal_places(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        catalog = sample_catalog(moment)
        deporte = build_sport_activity(
            "deporte_plus",
            catalog,
            date(2026, 9, 16),
            "https://t.me/c/123/50",
            None,
            "https://t.me/c/123/71",
            "https://t.me/c/123/72",
        )
        self.assertIn("🏃 <b>DEPORTE +</b>", deporte)
        self.assertIn("<b>Группа</b> · 2011–2017 г.р.", deporte)
        self.assertIn("Вт и Чт · 19:30–21:00", deporte)
        self.assertIn('href="https://t.me/c/123/71"', deporte)
        self.assertIn("Pista de atletismo", deporte)
        self.assertNotIn("https://maps.app.goo.gl/tGXyANAYgRREeajP8", deporte)

        psychomotricity = build_sport_activity(
            "psychomotricity",
            catalog,
            date(2026, 9, 16),
            "https://t.me/c/123/50",
            None,
            "https://t.me/c/123/71",
            "https://t.me/c/123/72",
        )
        self.assertIn("🧒 <b>Психомоторика</b>", psychomotricity)
        self.assertIn("<b>1-я группа</b> · 2022–2023 г.р.", psychomotricity)
        self.assertIn("<b>2-я группа</b> · 2021–2022 г.р.", psychomotricity)
        self.assertIn('href="https://t.me/c/123/72"', psychomotricity)
        self.assertNotIn("https://maps.app.goo.gl/kS2wM2V8x2twhuBCA", psychomotricity)

    def test_activities_index_hides_unpublished_sport_cards(self):
        message = build_activities(
            "https://t.me/c/123/59",
            "https://t.me/c/123/50",
        )
        self.assertIn("Плавание", message)
        for label in (
            "Художественная гимнастика",
            "Дзюдо",
            "Мультиспорт",
            "Инклюзивный мультиспорт",
            "Психомоторика",
            "DEPORTE +",
            "Футбол",
            "Гимнастика для старшего возраста",
            "Гимнастика Asociación Mujeres",
        ):
            with self.subTest(label=label):
                self.assertNotIn(label, message)

    def test_activities_index_can_link_each_independent_sport_card(self):
        links = {
            key: f"https://t.me/c/123/{index}"
            for index, key in enumerate(SPORT_ACTIVITY_KEYS, 60)
        }
        message = build_activities(
            "https://t.me/c/123/59",
            "https://t.me/c/123/50",
            links,
        )
        for link in links.values():
            self.assertIn(link, message)
        self.assertIn("Художественная гимнастика", message)
        self.assertIn("Инклюзивный мультиспорт", message)
        self.assertIn("Психомоторика", message)
        self.assertIn("DEPORTE +", message)

    async def test_source_managed_cards_get_stable_ids_and_relink_index(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        catalog = sample_catalog(moment)
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            sent = []

            async def send(message):
                sent.append(message)
                return len(sent)

            edit = AsyncMock()
            pin = AsyncMock()
            result = await publish_pinned_guide(
                "-100123",
                state,
                send,
                edit,
                pin,
                sporttia_catalog=catalog,
                local_day=date(2026, 9, 16),
            )
            for key in SPORT_ACTIVITY_KEYS:
                self.assertIn(key, result)
            saved = state.read("-100123")
            for key in SPORT_ACTIVITY_KEYS:
                self.assertEqual(saved[key], result[key])
            activity_edits = [
                call.args[1]
                for call in edit.await_args_list
                if call.args[0] == result["activities"]
            ]
            for key in SPORT_ACTIVITY_KEYS:
                self.assertIn(
                    telegram_message_link("-100123", result[key]),
                    activity_edits[-1],
                )

    async def test_new_source_key_without_current_groups_is_not_materialized(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        catalog = sample_catalog(moment)
        catalog = {
            **catalog,
            "activities": [
                item
                for item in catalog["activities"]
                if item["key"] != "deporte_plus"
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            sent = []

            async def send(message):
                sent.append(message)
                return len(sent)

            result = await publish_pinned_guide(
                "-100123",
                state,
                send,
                AsyncMock(),
                AsyncMock(),
                sporttia_catalog=catalog,
                local_day=date(2026, 9, 16),
            )
            self.assertNotIn("deporte_plus", result)
            self.assertIn("psychomotricity", result)


class SporttiaGuideStateTests(unittest.TestCase):
    def test_sporttia_snapshot_round_trips_inside_existing_guide_state(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        catalog = sample_catalog(moment)
        with tempfile.TemporaryDirectory() as directory:
            state = GuideState(Path(directory) / "guide.json")
            value = {"version": 1, "sporttia_catalog": catalog}
            state.write(value)
            self.assertEqual(state.read(), value)


if __name__ == "__main__":
    unittest.main()
