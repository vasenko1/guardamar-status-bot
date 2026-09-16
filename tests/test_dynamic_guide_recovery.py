import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from telegrambot.pinned import (
    LES_RABOSES_SOURCE_ACTIVITY_KEYS,
    MOLIVENT_SOURCE_ACTIVITY_KEYS,
    PALAU_ACTIVITY_KEYS,
    PINNED_MESSAGE_KEYS,
    PinnedGuideState,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.sporttia import SPORTTIA_ACTIVITY_KEYS, _extract_sporttia_catalog
from telegrambot.telegram import TelegramError

MADRID = ZoneInfo("Europe/Madrid")


def _row(activity_id, title, schedule, venue, *, medical=True):
    paragraphs = [
        "NUEVAS INSCRIPCIONES: 01/09/26 al 30/09/26",
        schedule,
        f"Clases en {venue}.",
    ]
    if medical:
        paragraphs.append("Se deberá aportar certificado médico correspondiente.")
    return activity_id, title, paragraphs


def _catalog():
    rows = [
        _row(85516, "5. GIMNASIA RÍTMICA. Primer turno. Nacidos entre 2011-2015. (Temp. 2026/2027)", "Lunes y miércoles de 16:15 a 17:15 horas.", "Palau Sant Jaume"),
        _row(85509, "7. JUDO. Primer turno. Nacidos entre 2011-2020. (Temp. 2026/2027)", "Horario: Miércoles y viernes de 17:00 a 18:30 horas.", "Palau Sant Jaume"),
        _row(85518, "11. MULTIDEPORTE PRIMER TURNO. Nacidos en 2019 Y 2020. (Temp. 2026/2027)", "Lunes, miércoles y viernes de 16:30 a 17:30 horas.", "Palau Sant Jaume"),
        _row(85522, "MULTIDEPORTE INCLUSIVO. PRIMER TURNO. ALUMNO CON AUTONOMIA. (Temp. 2026/2027) - Mayores de 6 años", "Sábado de 10 a 11 horas.", "Palau Sant Jaume. Sala Polivalente nº1"),
        _row(85514, "4. GIMNASIA MAYORES. PRIMER TURNO (Temp. 2026/2027)", "Horario: Lunes y miércoles de 09:30 a 11:00 horas y viernes de 09:00 a 10:00 horas.", "Palau Sant Jaume"),
        _row(85513, "2. GIMNASIA ASOCIACIÓN MUJERES DE GUARDAMAR. TURNO ÚNICO (temp 2026/2027)", "Horario: Lunes y miércoles de 17:30 a 19:00 horas.", "Palau Sant Jaume"),
        _row(85508, "DEPORTE +. Nacidos entre 2011 y 2017. (temp. 2026/2027)", "Horario: Martes y jueves de 19:30 a 21:00 horas.", "Complejo Deportivo Les Raboses. Pista de atletismo y campo de césped natural nº2"),
        _row(85526, "PSICOMOTRICIDAD. PRIMER TURNO. Nacidos entre 2022-2023. (Temp. 2026/2027)", "Horario: Martes y jueves de 17:15 a 18:15 horas.", "CEIP Molivent", medical=False),
        _row(85527, "PSICOMOTRICIDAD. SEGUNDO TURNO. Nacidos entre 2021-2022. (Temp. 2026/2027)", "Horario: Martes y jueves de 18:15 a 19:15 horas.", "CEIP Molivent", medical=False),
    ]
    bodies = []
    for index, (activity_id, title, paragraphs) in enumerate(rows, 1):
        details = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        bodies.append(
            f'<tbody id="oferta-1509-test-{index}"><tr><td>'
            f'<a href="https://play.sporttia.com/activities/{activity_id}">{title}</a>'
            f'<details>{details}</details></td>'
            '<td>1 oct 2026 – 31 may 2027</td>'
            '<td><span>Abierta</span></td></tr></tbody>'
        )
    payload = (
        '<html><body><div data-offer-blocks data-center-ids="1509">'
        + ''.join(bodies)
        + '</div></body></html>'
    ).encode('utf-8')
    return _extract_sporttia_catalog(
        payload,
        datetime(2026, 9, 16, 16, 30, tzinfo=MADRID),
    )


def _messages():
    messages = {
        key: number
        for number, key in enumerate(PINNED_MESSAGE_KEYS, start=1)
    }
    for offset, key in enumerate(SPORTTIA_ACTIVITY_KEYS):
        messages[key] = 200 + offset
    return messages


async def _publish_with_deleted(key, replacement):
    chat_id = "-100123"
    messages = _messages()
    deleted_id = messages[key]
    with tempfile.TemporaryDirectory() as directory:
        state = PinnedGuideState(Path(directory) / "pinned.json")
        state.write(chat_id, messages)

        async def edit(message_id, message):
            if message_id == deleted_id:
                raise TelegramError(
                    "missing", retryable=False,
                    code="MESSAGE-NOT-FOUND", status=400,
                )

        edit_mock = AsyncMock(side_effect=edit)
        result = await publish_pinned_guide(
            chat_id,
            state,
            AsyncMock(return_value=replacement),
            edit_mock,
            AsyncMock(),
            sporttia_catalog=_catalog(),
            local_day=date(2026, 9, 16),
        )
    return chat_id, messages, result, edit_mock


def _last_edit(edit_mock, message_id):
    edits = [
        call.args[1]
        for call in edit_mock.await_args_list
        if call.args[0] == message_id
    ]
    return edits[-1]


class DynamicGuideRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_palau_activity_recreates_and_relinks_index_and_palau(self):
        chat_id, _, result, edit = await _publish_with_deleted("multisport", 999)
        link = telegram_message_link(chat_id, 999)
        self.assertEqual(result["multisport"], 999)
        self.assertIn(link, _last_edit(edit, result["activities"]))
        self.assertIn(link, _last_edit(edit, result["palau_sant_jaume"]))

    async def test_deleted_deporte_plus_relinks_only_its_place_and_index(self):
        chat_id, _, result, edit = await _publish_with_deleted("deporte_plus", 997)
        link = telegram_message_link(chat_id, 997)
        self.assertIn(link, _last_edit(edit, result["activities"]))
        self.assertIn(link, _last_edit(edit, result["les_raboses"]))
        self.assertNotIn(link, _last_edit(edit, result["palau_sant_jaume"]))
        self.assertNotIn(link, _last_edit(edit, result["molivent"]))

    async def test_deleted_psychomotricity_relinks_only_molivent_and_index(self):
        chat_id, _, result, edit = await _publish_with_deleted("psychomotricity", 996)
        link = telegram_message_link(chat_id, 996)
        self.assertIn(link, _last_edit(edit, result["activities"]))
        self.assertIn(link, _last_edit(edit, result["molivent"]))
        self.assertNotIn(link, _last_edit(edit, result["palau_sant_jaume"]))
        self.assertNotIn(link, _last_edit(edit, result["les_raboses"]))

    async def test_deleted_les_raboses_relinks_deporte_plus_and_football(self):
        chat_id, _, result, edit = await _publish_with_deleted("les_raboses", 995)
        link = telegram_message_link(chat_id, 995)
        self.assertEqual(result["les_raboses"], 995)
        self.assertIn(link, _last_edit(edit, result["deporte_plus"]))
        self.assertIn(link, _last_edit(edit, result["football"]))
        self.assertNotIn(link, _last_edit(edit, result["psychomotricity"]))
        for key in PALAU_ACTIVITY_KEYS:
            self.assertNotIn(link, _last_edit(edit, result[key]))

    async def test_deleted_molivent_relinks_psychomotricity_only(self):
        chat_id, _, result, edit = await _publish_with_deleted("molivent", 994)
        link = telegram_message_link(chat_id, 994)
        self.assertIn(link, _last_edit(edit, result["psychomotricity"]))
        self.assertNotIn(link, _last_edit(edit, result["deporte_plus"]))
        self.assertNotIn(link, _last_edit(edit, result["football"]))

    async def test_deleted_palau_does_not_reassign_other_venue_activities(self):
        chat_id, _, result, edit = await _publish_with_deleted("palau_sant_jaume", 993)
        palau_link = telegram_message_link(chat_id, 993)
        self.assertEqual(result["palau_sant_jaume"], 993)
        for key in PALAU_ACTIVITY_KEYS:
            self.assertIn(palau_link, _last_edit(edit, result[key]))
        self.assertNotIn(palau_link, _last_edit(edit, result["deporte_plus"]))
        self.assertNotIn(palau_link, _last_edit(edit, result["psychomotricity"]))
        self.assertIn(
            telegram_message_link(chat_id, result["les_raboses"]),
            _last_edit(edit, result["deporte_plus"]),
        )
        self.assertIn(
            telegram_message_link(chat_id, result["molivent"]),
            _last_edit(edit, result["psychomotricity"]),
        )

    async def test_deleted_football_recovers_as_static_durable_content(self):
        chat_id, _, result, edit = await _publish_with_deleted("football", 992)
        link = telegram_message_link(chat_id, 992)
        self.assertEqual(result["football"], 992)
        self.assertIn(link, _last_edit(edit, result["activities"]))
        self.assertIn(link, _last_edit(edit, result["les_raboses"]))

    def test_activity_sets_are_explicit_and_non_overlapping_by_venue(self):
        self.assertEqual(LES_RABOSES_SOURCE_ACTIVITY_KEYS, ("deporte_plus",))
        self.assertEqual(MOLIVENT_SOURCE_ACTIVITY_KEYS, ("psychomotricity",))
        self.assertTrue(set(PALAU_ACTIVITY_KEYS).isdisjoint(LES_RABOSES_SOURCE_ACTIVITY_KEYS))
        self.assertTrue(set(PALAU_ACTIVITY_KEYS).isdisjoint(MOLIVENT_SOURCE_ACTIVITY_KEYS))
        self.assertNotIn("football", SPORTTIA_ACTIVITY_KEYS)


if __name__ == '__main__':
    unittest.main()
