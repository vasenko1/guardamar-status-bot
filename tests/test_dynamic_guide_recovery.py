import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from telegrambot.pinned import (
    PINNED_MESSAGE_KEYS,
    PinnedGuideState,
    SPORT_ACTIVITY_KEYS,
    publish_pinned_guide,
    telegram_message_link,
)
from telegrambot.sporttia import _extract_sporttia_catalog
from telegrambot.telegram import TelegramError

MADRID = ZoneInfo("Europe/Madrid")


def _catalog():
    rows = [
        (85516, "5. GIMNASIA RÍTMICA. Primer turno. Nacidos entre 2011-2015. (Temp. 2026/2027)", "Lunes y miércoles de 16:15 a 17:15 horas."),
        (85509, "7. JUDO. Primer turno. Nacidos entre 2011-2020. (Temp. 2026/2027)", "Horario: Miércoles y viernes de 17:00 a 18:30 horas."),
        (85518, "11. MULTIDEPORTE PRIMER TURNO. Nacidos en 2019 Y 2020. (Temp. 2026/2027)", "Lunes, miércoles y viernes de 16:30 a 17:30 horas."),
        (85522, "MULTIDEPORTE INCLUSIVO. PRIMER TURNO. ALUMNO CON AUTONOMIA. (Temp. 2026/2027) - Mayores de 6 años", "Sábado de 10 a 11 horas."),
        (85514, "4. GIMNASIA MAYORES. PRIMER TURNO (Temp. 2026/2027)", "Horario: Lunes y miércoles de 09:30 a 11:00 horas y viernes de 09:00 a 10:00 horas."),
        (85513, "2. GIMNASIA ASOCIACIÓN MUJERES DE GUARDAMAR. TURNO ÚNICO (temp 2026/2027)", "Horario: Lunes y miércoles de 17:30 a 19:00 horas."),
    ]
    bodies = []
    for index, (activity_id, title, schedule) in enumerate(rows, 1):
        bodies.append(
            f'<tbody id="oferta-1509-test-{index}"><tr><td>'
            f'<a href="https://play.sporttia.com/activities/{activity_id}">{title}</a>'
            '<details>'
            '<p>NUEVAS INSCRIPCIONES: 01/09/26 al 30/09/26</p>'
            f'<p>{schedule}</p>'
            '<p>Clases en Palau Sant Jaume.</p>'
            '<p>Se deberá aportar certificado médico correspondiente.</p>'
            '</details></td><td>1 oct 2026 – 31 may 2027</td>'
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
    for offset, key in enumerate(SPORT_ACTIVITY_KEYS):
        messages[key] = 200 + offset
    return messages


class DynamicGuideRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_sport_card_is_recreated_and_relinked_everywhere(self):
        chat_id = "-100123"
        messages = _messages()
        deleted_id = messages["multisport"]
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
                AsyncMock(return_value=999),
                edit_mock,
                AsyncMock(),
                sporttia_catalog=_catalog(),
                local_day=date(2026, 9, 16),
            )

        self.assertEqual(result["multisport"], 999)
        new_link = telegram_message_link(chat_id, 999)
        for owner in ("activities", "palau_sant_jaume"):
            edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == result[owner]
            ]
            self.assertIn(new_link, edits[-1])

    async def test_deleted_palau_is_recreated_and_all_sport_cards_relink_to_it(self):
        chat_id = "-100123"
        messages = _messages()
        old_palau = messages["palau_sant_jaume"]
        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write(chat_id, messages)

            async def edit(message_id, message):
                if message_id == old_palau:
                    raise TelegramError(
                        "missing", retryable=False,
                        code="MESSAGE-NOT-FOUND", status=400,
                    )

            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                chat_id,
                state,
                AsyncMock(return_value=998),
                edit_mock,
                AsyncMock(),
                sporttia_catalog=_catalog(),
                local_day=date(2026, 9, 16),
            )

        self.assertEqual(result["palau_sant_jaume"], 998)
        new_link = telegram_message_link(chat_id, 998)
        parent_edits = [
            call.args[1] for call in edit_mock.await_args_list
            if call.args[0] == result["polideportivo"]
        ]
        self.assertIn(new_link, parent_edits[-1])
        for key in SPORT_ACTIVITY_KEYS:
            sport_edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == result[key]
            ]
            self.assertIn(new_link, sport_edits[-1])

    async def test_all_source_managed_sport_cards_recover_as_one_relinked_graph(self):
        chat_id = "-100123"
        messages = _messages()
        deleted = {messages[key] for key in SPORT_ACTIVITY_KEYS}
        next_id = 300

        async def send(message):
            nonlocal next_id
            next_id += 1
            return next_id

        async def edit(message_id, message):
            if message_id in deleted:
                raise TelegramError(
                    "missing", retryable=False,
                    code="MESSAGE-NOT-FOUND", status=400,
                )

        with tempfile.TemporaryDirectory() as directory:
            state = PinnedGuideState(Path(directory) / "pinned.json")
            state.write(chat_id, messages)
            edit_mock = AsyncMock(side_effect=edit)
            result = await publish_pinned_guide(
                chat_id,
                state,
                send,
                edit_mock,
                AsyncMock(),
                sporttia_catalog=_catalog(),
                local_day=date(2026, 9, 16),
            )

        self.assertTrue(
            all(result[key] not in deleted for key in SPORT_ACTIVITY_KEYS)
        )
        for owner in ("activities", "palau_sant_jaume"):
            edits = [
                call.args[1] for call in edit_mock.await_args_list
                if call.args[0] == result[owner]
            ]
            final = edits[-1]
            for key in SPORT_ACTIVITY_KEYS:
                self.assertIn(
                    telegram_message_link(chat_id, result[key]), final
                )


if __name__ == '__main__':
    unittest.main()
