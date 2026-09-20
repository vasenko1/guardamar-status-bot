import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.guide import GuideState
from telegrambot.pinned import (
    LES_RABOSES_MAP_URL,
    MOLIVENT_MAP_URL,
    PinnedGuideState,
    build_activities,
    build_football,
    build_les_raboses,
    build_molivent,
    build_sport_activity,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.sporttia import (
    SPORTTIA_ACTIVITY_KEYS,
    SPORTTIA_CENTER_URL,
    SporttiaSourceError,
    _allowed_sporttia_url,
    _extract_sporttia_catalog,
    _group_order,
    fetch_sporttia_catalog,
    merge_sporttia_catalog,
    select_sport_groups,
    valid_sporttia_snapshot,
)


MADRID = ZoneInfo("Europe/Madrid")


def _row(activity_id, title, schedule, venue, *, audience_details=(), medical=True):
    paragraphs = [
        "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
        schedule,
        f"Clases en {venue}.",
        *audience_details,
    ]
    if medical:
        paragraphs.append("Se deberá aportar certificado médico correspondiente.")
    return activity_id, title, paragraphs, "1 oct 2026 – 31 may 2027"


def sporttia_rows():
    # Fifteen rows mirror the complete current centre-page scope: the six
    # established activity families plus DEPORTE+ and two psychomotricity groups.
    return [
        _row(
            85516,
            "5. GIMNASIA RÍTMICA. Primer turno. Nacidos entre 2011-2015. (Temp. 2026/2027)",
            "Horario: Lunes y miércoles de 16:15 a 17:15 horas.",
            "Palau Sant Jaume",
            audience_details=("Los turnos puede sufrir variaciones según criterios técnicos.",),
        ),
        _row(
            85517,
            "6. GIMNASIA RÍTMICA. Segundo turno. Nacidos entre 2016-2020. (Temp. 2026/2027)",
            "Horario: Lunes y miércoles de 17:15 a 18:15 horas.",
            "Palau Sant Jaume",
        ),
        _row(
            85525,
            "GIMNASIA RÍTMICA. Tercer turno. Nacidos entre 2018-2021. (Temp. 2026/2027)",
            "Horario: Martes y jueves de 16:15 a 17:15 horas.",
            "Palau Sant Jaume",
        ),
        _row(
            85509,
            "7. JUDO. Primer turno. Nacidos entre 2011-2020. (Temp. 2026/2027)",
            "Horario: Miércoles y viernes de 17:00 a 18:30 horas.",
            "Palau Sant Jaume",
            audience_details=("La distribución de los grupos puede haber variaciones según criterios del Club.",),
        ),
        _row(
            85510,
            "8. JUDO. Segundo turno. Nacidos entre 2011 y 2020. (Temp. 2026/2027)",
            "Horario: Miércoles y viernes de 18:30 a 20:00 horas.",
            "Palau Sant Jaume",
        ),
        _row(
            85518,
            "11. MULTIDEPORTE PRIMER TURNO. Nacidos en 2019 Y 2020. (Temp. 2026/2027)",
            "Lunes, miércoles y viernes de 16:30 a 17:30 horas.",
            "Palau Sant Jaume",
        ),
        _row(
            85519,
            "12. MULTIDEPORTE SEGUNDO TURNO. Nacidos en 2017 Y 2018. (Temp. 2026/2027)",
            "Lunes, miércoles y viernes de 17:30 a 18:30 horas.",
            "Palau Sant Jaume",
        ),
        _row(
            85522,
            "MULTIDEPORTE INCLUSIVO. PRIMER TURNO. ALUMNO CON AUTONOMIA. (Temp. 2026/2027) - Mayores de 6 años",
            "Sábado de 10 a 11 horas.",
            "Palau Sant Jaume. Sala Polivalente nº1",
        ),
        _row(
            85523,
            "MULTIDEPORTE INCLUSIVO. SEGUNDO TURNO. ALUMNO SIN AUTONOMIA. (Temp. 2026/2027) - Mayores de 6 años",
            "Sábado de 11 a 12 horas.",
            "Palau Sant Jaume. Sala Polivalente nº1",
            audience_details=("Participación con acompañante adulto.",),
        ),
        _row(
            85514,
            "4. GIMNASIA MAYORES. PRIMER TURNO (Temp. 2026/2027)",
            "Horario: Lunes y miércoles de 09:30 a 11:00 horas y viernes de 09:00 a 10:00 horas.",
            "Palau Sant Jaume",
        ),
        _row(
            85524,
            "GIMNASIA MAYORES. SEGUNDO TURNO (Temp. 2026/2027)",
            "Horario: Martes y jueves de 09:30 a 11:00 horas.",
            "Palau Sant Jaume",
        ),
        _row(
            85513,
            "2. GIMNASIA ASOCIACIÓN MUJERES DE GUARDAMAR. TURNO ÚNICO (temp 2026/2027)",
            "Horario: Lunes y miércoles de 17:30 a 19:00 horas.",
            "Palau Sant Jaume",
            audience_details=("Además se deberá aportar justificante o recibo de la cuota de socia de la asociación.",),
        ),
        (
            85508,
            "DEPORTE +. Nacidos entre 2011 y 2017. (temp. 2026/2027)",
            [
                "RENOVACIONES: 01/04/26 al 31/05/26",
                "NUEVAS INSCRIPCIONES: 01/06/26 al 30/06/26 y 01/09/26 al 30/09/26",
                "Horario: Martes y jueves de 19:30 a 21:00 horas.",
                "Clases en Complejo Deportivo Les Raboses. Pista de atletismo y campo de césped natural nº2.",
                "Flag rugby, carrera de obstáculos y atletismo.",
                "Se deberá aportar certificado médico correspondiente.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85526,
            "PSICOMOTRICIDAD. PRIMER TURNO. Nacidos entre 2022-2023. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/09/26 al 30/09/26",
                "Horario: Martes y jueves de 17:15 a 18:15 horas.",
                "Clases en CEIP Molivent.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
        (
            85527,
            "PSICOMOTRICIDAD. SEGUNDO TURNO. Nacidos entre 2021-2022. (Temp. 2026/2027)",
            [
                "NUEVAS INSCRIPCIONES: 01/09/26 al 30/09/26",
                "Horario: Martes y jueves de 18:15 a 19:15 horas.",
                "Clases en CEIP Molivent.",
            ],
            "1 oct 2026 – 31 may 2027",
        ),
    ]


def sporttia_html(rows=None):
    rows = sporttia_rows() if rows is None else rows
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


def sample_catalog(moment, rows=None):
    return _extract_sporttia_catalog(sporttia_html(rows), moment)


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

    def test_one_centre_response_covers_all_current_fifteen_rows(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        result = sample_catalog(moment)
        self.assertEqual(len(result["activities"]), 15)
        self.assertEqual(
            {item["key"] for item in result["activities"]},
            set(SPORTTIA_ACTIVITY_KEYS),
        )
        self.assertNotIn("Abierta", str(result))

    def test_deporte_plus_has_narrow_unnumbered_group_path(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        result = sample_catalog(moment)
        group = next(
            item for item in result["activities"] if item["key"] == "deporte_plus"
        )
        self.assertEqual(group["source_id"], 85508)
        self.assertEqual(group["group_order"], 1)
        self.assertEqual(group["audience"], "2011–2017 г.р.")
        self.assertEqual(group["schedule"], "Вт и Чт · 19:30–21:00")
        self.assertTrue(group["venue"].startswith("Complejo Deportivo Les Raboses"))
        self.assertEqual(
            group["registrations"],
            [
                {"start": "2026-06-01", "end": "2026-06-30"},
                {"start": "2026-09-01", "end": "2026-09-30"},
            ],
        )
        with self.assertRaises(SporttiaSourceError):
            _group_order("DEPORTE +. Nacidos entre 2011 y 2017")

    def test_psychomotricity_preserves_both_overlapping_audiences(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        groups = select_sport_groups(
            sample_catalog(moment), "psychomotricity", date(2026, 9, 16)
        )
        self.assertEqual(
            [item["audience"] for item in groups],
            ["2022–2023 г.р.", "2021–2022 г.р."],
        )
        self.assertEqual(
            [item["schedule"] for item in groups],
            ["Вт и Чт · 17:15–18:15", "Вт и Чт · 18:15–19:15"],
        )
        self.assertTrue(all(item["venue"] == "CEIP Molivent" for item in groups))
        self.assertTrue(all(not item["medical_certificate"] for item in groups))

    def test_existing_activity_parsing_is_unchanged(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        result = sample_catalog(moment)
        judo = next(item for item in result["activities"] if item["source_id"] == 85509)
        self.assertEqual(judo["schedule"], "Ср и Пт · 17:00–18:30")
        self.assertEqual(judo["venue"], "Palau Sant Jaume")
        self.assertEqual(judo["audience"], "2011–2020 г.р.")

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
        self.assertEqual(merged["observed_source_ids"], [])
        expired = merge_sporttia_catalog(previous, current, date(2027, 7, 1))
        self.assertEqual(expired["activities"], [])


class SporttiaPinnedTests(unittest.IsolatedAsyncioTestCase):
    def test_deporte_plus_card_has_internal_venue_and_medical_actions(self):
        catalog = sample_catalog(datetime(2026, 9, 16, 16, 30, tzinfo=MADRID))
        card = build_sport_activity(
            "deporte_plus",
            catalog,
            date(2026, 9, 16),
            "https://t.me/c/123/50",
            les_raboses_link="https://t.me/c/123/70",
        )
        self.assertIn("🏃 <b>DEPORTE +</b>", card)
        self.assertIn("<b>Группа</b> · 2011–2017 г.р.", card)
        self.assertIn("Вт и Чт · 19:30–21:00", card)
        self.assertIn('href="https://t.me/c/123/70"><b>Complejo Deportivo Les Raboses</b>', card)
        self.assertIn("Pista de atletismo y campo de césped natural nº2", card)
        self.assertIn("flag rugby · полоса препятствий · лёгкая атлетика", card)
        self.assertIn("Запись:</b> до 30 сентября 2026", card)
        self.assertIn("спортивная медсправка", card)
        self.assertNotIn(LES_RABOSES_MAP_URL, card)

    def test_psychomotricity_card_has_two_groups_and_no_medical_text(self):
        catalog = sample_catalog(datetime(2026, 9, 16, 16, 30, tzinfo=MADRID))
        card = build_sport_activity(
            "psychomotricity",
            catalog,
            date(2026, 9, 16),
            "https://t.me/c/123/50",
            molivent_link="https://t.me/c/123/71",
        )
        self.assertIn("🧒 <b>Психомоторика</b>", card)
        self.assertIn("<b>1-я группа</b> · 2022–2023 г.р.", card)
        self.assertIn("<b>2-я группа</b> · 2021–2022 г.р.", card)
        self.assertIn('href="https://t.me/c/123/71"><b>CEIP Molivent</b>', card)
        self.assertNotIn("медсправка", card)
        self.assertNotIn(MOLIVENT_MAP_URL, card)

    def test_known_venues_fall_back_to_maps_without_internal_links(self):
        catalog = sample_catalog(datetime(2026, 9, 16, 16, 30, tzinfo=MADRID))
        deporte = build_sport_activity(
            "deporte_plus", catalog, date(2026, 9, 16)
        )
        psych = build_sport_activity(
            "psychomotricity", catalog, date(2026, 9, 16)
        )
        self.assertIn(LES_RABOSES_MAP_URL, deporte)
        self.assertIn(MOLIVENT_MAP_URL, psych)

    def test_place_and_static_football_cards_match_durable_guide_contract(self):
        les = build_les_raboses(
            "https://t.me/c/123/80",
            "https://t.me/c/123/81",
            "https://t.me/c/123/50",
        )
        molivent = build_molivent(
            "https://t.me/c/123/82",
            "https://t.me/c/123/50",
        )
        football = build_football(
            "https://t.me/c/123/60",
            "https://t.me/c/123/70",
        )
        self.assertIn("стадион José García Campillo", les)
        self.assertIn("2 футбольных поля", les)
        self.assertIn("поле для стрельбы из лука", les)
        self.assertNotIn("C/", les)
        self.assertIn("Здесь проходят муниципальные занятия для детей", molivent)
        self.assertIn("https://t.me/c/123/82", molivent)
        self.assertIn("Детско-юношеская школа Guardamar Soccer C.D.", football)
        self.assertIn("<code>698953390</code>", football)
        self.assertIn("<code>info@guardamarsoccercd.com</code>", football)
        self.assertIn("Онлайн-форма клуба", football)
        self.assertNotIn(">Записаться<", football)
        self.assertIn("https://t.me/c/123/70", football)

    def test_activity_index_keeps_one_message_and_hides_uncreated_source_cards(self):
        message = build_activities(
            "https://t.me/c/123/59",
            "https://t.me/c/123/50",
            {"judo": "https://t.me/c/123/61"},
            "https://t.me/c/123/90",
        )
        self.assertIn("🏃 <b>Спорт и движение</b>", message)
        self.assertIn("Дзюдо", message)
        self.assertIn("Футбол", message)
        self.assertNotIn("DEPORTE +", message)
        self.assertNotIn("Психомоторика", message)

    async def test_source_card_rollout_guard_skips_new_empty_cards(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
        legacy_rows = [
            row for row in sporttia_rows()
            if row[0] not in {85508, 85526, 85527}
        ]
        catalog = sample_catalog(moment, legacy_rows)
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            result = await publish_pinned_guide(
                "-100123",
                state,
                AsyncMock(side_effect=range(1, 1000)),
                AsyncMock(),
                AsyncMock(),
                sporttia_catalog=catalog,
                local_day=date(2026, 9, 16),
            )
        self.assertNotIn("deporte_plus", result)
        self.assertNotIn("psychomotricity", result)
        self.assertIn("football", result)
        self.assertIn("les_raboses", result)
        self.assertIn("molivent", result)

    async def test_source_managed_cards_get_stable_ids_and_relink_index(self):
        catalog = sample_catalog(datetime(2026, 9, 16, 16, 30, tzinfo=MADRID))
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            next_id = 0

            async def send(message):
                nonlocal next_id
                next_id += 1
                return next_id

            edit = AsyncMock()
            result = await publish_pinned_guide(
                "-100123",
                state,
                send,
                edit,
                AsyncMock(),
                sporttia_catalog=catalog,
                local_day=date(2026, 9, 16),
            )
            for key in SPORTTIA_ACTIVITY_KEYS:
                self.assertIn(key, result)
            activity_edits = [
                call.args[1]
                for call in edit.await_args_list
                if call.args[0] == result["activities"]
            ]
            for key in SPORTTIA_ACTIVITY_KEYS:
                self.assertIn(
                    telegram_message_link("-100123", result[key]),
                    activity_edits[-1],
                )


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
