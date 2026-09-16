import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegrambot.pinned import (
    PALAU_SANT_JAUME_MAP_URL,
    SPORT_MEDICAL_CERTIFICATE_URL,
    build_palau_sant_jaume,
    build_polideportivo,
    build_sport_activity,
    build_youth_centre,
)
from telegrambot.sporttia import _extract_sporttia_catalog


MADRID = ZoneInfo("Europe/Madrid")


def _catalog(rows):
    bodies = []
    for index, row in enumerate(rows, 1):
        activity_id, title, paragraphs, season = row
        details = "".join(f"<p>{value}</p>" for value in paragraphs)
        bodies.append(
  f'<tbody id="oferta-1509-test-{index}"><tr>'
  f'<td><a href="https://play.sporttia.com/activities/{activity_id}">{title}</a>'
  f'<details>{details}</details></td>'
  f'<td>{season}</td><td><span>Abierta</span></td>'
  '</tr></tbody>'
        )
    payload = (
        '<html><body><div data-offer-blocks data-center-ids="1509">'
        + "".join(bodies)
        + '</div></body></html>'
    ).encode("utf-8")
    return _extract_sporttia_catalog(
        payload,
        datetime(2026, 9, 16, 16, 30, tzinfo=MADRID),
    )


class PalauActivityUxTests(unittest.TestCase):
    def test_turnos_remain_visible_groups_but_action_link_is_explicit(self):
        catalog = _catalog(
  [
      (
85509,
"7. JUDO. Primer turno. Nacidos entre 2011-2020. (Temp. 2026/2027)",
[
    "NUEVAS INSCRIPCIONES: 01/09/26 al 30/09/26",
    "Horario: Miércoles y viernes de 17:00 a 18:30 horas.",
    "Clases en Palau Sant Jaume.",
    "Se deberá aportar certificado médico correspondiente.",
],
"1 oct 2026 – 31 may 2027",
      ),
      (
85510,
"8. JUDO. Segundo turno. Nacidos entre 2011 y 2020. (Temp. 2026/2027)",
[
    "NUEVAS INSCRIPCIONES: 01/09/26 al 30/09/26",
    "Horario: Miércoles y viernes de 18:30 a 20:00 horas.",
    "Clases en Palau Sant Jaume.",
    "Se deberá aportar certificado médico correspondiente.",
],
"1 oct 2026 – 31 may 2027",
      ),
  ]
        )
        card = build_sport_activity(
  "judo",
  catalog,
  date(2026, 9, 16),
  "https://t.me/c/123/50",
  "https://t.me/c/123/77",
        )
        self.assertIn("<b>1-я группа</b> · 2011–2020 г.р.", card)
        self.assertIn("<b>2-я группа</b> · 2011–2020 г.р.", card)
        self.assertNotIn(
  '<a href="https://play.sporttia.com/activities/85509"><b>1-я группа</b></a>',
  card,
        )
        self.assertIn(
  '📝 <a href="https://play.sporttia.com/activities/85509">Записаться</a>',
  card,
        )
        self.assertIn('href="https://t.me/c/123/77"><b>Palau Sant Jaume</b>', card)
        self.assertNotIn(PALAU_SANT_JAUME_MAP_URL, card)

    def test_future_registration_uses_neutral_group_page_action(self):
        catalog = _catalog(
  [
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
  ]
        )
        card = build_sport_activity(
  "inclusive_multisport",
  catalog,
  date(2026, 9, 16),
        )
        self.assertIn("<b>1-я группа</b> · от 6 лет", card)
        self.assertIn("👤 Самостоятельное участие", card)
        self.assertIn("Sala Polivalente nº1", card)
        self.assertIn("🔎", card)
        self.assertIn("Страница группы", card)
        self.assertNotIn(">Записаться</a>", card)

    def test_medical_certificate_is_actionable_and_email_is_copyable(self):
        catalog = _catalog(
  [
      (
85518,
"11. MULTIDEPORTE PRIMER TURNO. Nacidos en 2019 Y 2020. (Temp. 2026/2027)",
[
    "NUEVAS INSCRIPCIONES: 01/09/26 al 30/09/26",
    "Lunes, miércoles y viernes de 16:30 a 17:30 horas.",
    "Clases en Palau Sant Jaume.",
    "Se deberá aportar certificado médico correspondiente.",
],
"1 oct 2026 – 31 may 2027",
      ),
  ]
        )
        card = build_sport_activity("multisport", catalog, date(2026, 9, 16))
        self.assertIn("После записи нужна спортивная медсправка", card)
        self.assertIn(SPORT_MEDICAL_CERTIFICATE_URL, card)
        self.assertIn("Скачать бланк", card)
        self.assertIn(
  "<code>deportesguardamar@hotmail.com</code>",
  card,
        )

    def test_palau_is_child_of_polideportivo_and_links_back_to_sports(self):
        links = {
  "judo": "https://t.me/c/123/80",
  "multisport": "https://t.me/c/123/81",
        }
        card = build_palau_sant_jaume(
  links,
  "https://t.me/c/123/70",
        )
        self.assertIn(PALAU_SANT_JAUME_MAP_URL, card)
        self.assertIn("<code>965357693</code>", card)
        self.assertIn("Открыть на карте", card)
        self.assertNotIn("Av. Europa, s/n", card)
        self.assertIn("✉️ <b>Email:</b>\n<code>deportesguardamar@hotmail.com</code>", card)
        self.assertIn("<code>deportesguardamar@hotmail.com</code>", card)
        self.assertIn("2 многофункциональных зала", card)
        self.assertIn("https://t.me/c/123/80", card)
        self.assertIn("https://t.me/c/123/81", card)
        self.assertIn("https://t.me/c/123/70", card)

        parent = build_polideportivo(
  "https://t.me/c/123/71",
  "https://t.me/c/123/72",
  palau_link="https://t.me/c/123/73",
        )
        self.assertIn("https://t.me/c/123/73", parent)
        self.assertLess(
  parent.index("Palau Sant Jaume"),
  parent.index("Другие зоны"),
        )
        self.assertNotIn("🏀 баскетбол\n", parent)

    def test_existing_contact_style_uses_copyable_code(self):
        youth = build_youth_centre()
        self.assertIn("<code>609006754</code>", youth)
        self.assertIn("<code>juventudguardamar@gmail.com</code>", youth)
        self.assertIn("Открыть на карте", youth)
        self.assertNotIn("Calle Molivent", youth)


if __name__ == "__main__":
    unittest.main()
