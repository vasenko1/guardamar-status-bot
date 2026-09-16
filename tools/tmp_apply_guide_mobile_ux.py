from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, found {count} for {old[:80]!r}"
        )
    p.write_text(text.replace(old, new), encoding="utf-8")


pinned = "src/telegrambot/pinned.py"

replace_once(
    pinned,
    '''    palau_target = palau_link or PALAU_SANT_JAUME_MAP_URL
    return _with_back_link(
        with_footer(
            f"🏟 <a href=\\"{POLIDEPORTIVO_MAP_URL}\\"><b>Polideportivo Municipal</b></a>\\n\\n"
            "Муниципальный спортивный комплекс Гуардамара.\\n\\n"
            f"🏊 {_direct_link('Крытый бассейн Manel Estiarte', indoor_link)}\\n"
            f"☀️ {_direct_link('Открытый муниципальный бассейн', outdoor_link)}\\n"
            f"🏟 {_direct_link('Palau Sant Jaume', palau_target)}\\n\\n"
            "<b>Также в комплексе:</b>\\n"
            f"🎾 <a href=\\"{TENNIS_COURT_MAP_URL}\\">теннис и падель</a>\\n"
            "💪 тренажёрный зал и калистеника\\n"
            "🥎 frontón"
        ),
''',
    '''    palau_target = palau_link or PALAU_SANT_JAUME_MAP_URL
    return _with_back_link(
        with_footer(
            "🏟 <b>Polideportivo Municipal</b>\\n\\n"
            "Муниципальный спортивный комплекс Гуардамара.\\n\\n"
            f'📍 <a href="{POLIDEPORTIVO_MAP_URL}"><b>Открыть на карте</b></a>\\n\\n'
            "<b>Объекты:</b>\\n"
            f"🏊 {_direct_link('Крытый бассейн Manel Estiarte', indoor_link)}\\n"
            f"☀️ {_direct_link('Открытый муниципальный бассейн', outdoor_link)}\\n"
            f"🏟 {_direct_link('Palau Sant Jaume', palau_target)}\\n\\n"
            "<b>Другие зоны:</b>\\n"
            f"🎾 <a href=\\"{TENNIS_COURT_MAP_URL}\\">теннис и падель</a>\\n"
            "💪 тренажёрный зал и калистеника\\n"
            "🥎 frontón"
        ),
''',
)

replace_once(
    pinned,
    '''        f'<a href="{PALAU_SANT_JAUME_MAP_URL}">📍 <b>Palau Sant Jaume</b></a>',
        "Av. Europa, s/n",
        "📞 <b>Телефон:</b> <code>965357693</code>",
        f"✉️ <b>Email:</b> <code>{SPORTS_CONTACT_EMAIL}</code>",
        "",
        "<b>Внутри:</b>",
        "🏟 центральная спортивная площадка",
        "🏀 баскетбол · футзал · волейбол · бадминтон",
        "🤸 2 многофункциональных зала",
        "🏋️ зал силовых тренировок",
''',
    '''        f'<a href="{PALAU_SANT_JAUME_MAP_URL}">📍 <b>Открыть на карте</b></a>',
        "📞 <b>Телефон:</b> <code>965357693</code>",
        "✉️ <b>Email:</b>",
        f"<code>{SPORTS_CONTACT_EMAIL}</code>",
        "",
        "<b>Внутри:</b>",
        "🏟 Центральная спортивная площадка",
        "🏀 баскетбол · футзал · волейбол · бадминтон",
        "🤸 2 многофункциональных зала",
        "🏋️ Зал силовых тренировок",
''',
)
replace_once(
    pinned,
    '        lines.extend(["", "🎓 <b>Занятия здесь:</b>"])',
    '        lines.extend(["", "🎓 <b>Занятия:</b>"])',
)

replace_once(
    pinned,
    '''            f"📍 <a href=\\"{POOL_INDOOR_MAP_URL}\\"><b>Piscina Climatizada Manel Estiarte</b></a>\\n"
            "Av. de Cervantes, s/n\\n"
            "📞 <b>Телефон:</b> <code>966726593</code>\\n\\n"
            f"🎓 Занятия и запись: {_direct_link('🏊 Плавание', swimming_link)}."
''',
    '''            f"📍 <a href=\\"{POOL_INDOOR_MAP_URL}\\"><b>Открыть на карте</b></a>\\n"
            "📞 <b>Телефон:</b> <code>966726593</code>\\n\\n"
            f"🎓 <b>Занятия:</b> {_direct_link('🏊 Плавание', swimming_link)}."
''',
)

replace_once(
    pinned,
    '''            f"📍 <a href=\\"{POOL_OUTDOOR_MAP_URL}\\"><b>Piscinas Descubiertas Municipales</b></a>\\n"
            "Av. Europa, 3\\n"
            "📞 <b>Телефон:</b> <code>966726335</code>\\n\\n"
            f"🎓 Занятия и запись: {_direct_link('🏊 Плавание', swimming_link)}."
''',
    '''            f"📍 <a href=\\"{POOL_OUTDOOR_MAP_URL}\\"><b>Открыть на карте</b></a>\\n"
            "📞 <b>Телефон:</b> <code>966726335</code>\\n\\n"
            f"🎓 <b>Занятия:</b> {_direct_link('🏊 Плавание', swimming_link)}."
''',
)

replace_once(
    pinned,
    '''            f"📍 <a href=\\"{YOUTH_CENTRE_MAP_URL}\\"><b>Calle Molivent, у автовокзала</b></a>\\n"
            "📱 <b>WhatsApp:</b> <code>609006754</code>\\n"
            "✉️ <b>Email:</b> <code>juventudguardamar@gmail.com</code>"
''',
    '''            f"📍 <a href=\\"{YOUTH_CENTRE_MAP_URL}\\"><b>Открыть на карте</b></a>\\n"
            "📱 <b>WhatsApp:</b> <code>609006754</code>\\n"
            "✉️ <b>Email:</b>\\n"
            "<code>juventudguardamar@gmail.com</code>"
''',
)

replace_once(
    pinned,
    '''    for index, group in enumerate(groups):
        if index:
            lines.append("")
''',
    '''    for group in groups:
''',
)

replace_once(
    pinned,
    '''        if _registration_is_open(group, local_day):
            lines.append(
                f'  📝 <a href="{activity_url}"><b>Запись в группу</b></a>'
            )
        else:
            lines.append(
                f'  🔎 <a href="{activity_url}"><b>Страница группы</b></a>'
            )
''',
    '''        if _registration_is_open(group, local_day):
            lines.append(
                f'  📝 <a href="{activity_url}">Записаться</a>'
            )
        else:
            lines.append(
                f'  🔎 <a href="{activity_url}">Страница группы</a>'
            )
''',
)

replace_once(
    pinned,
    '''        notes.append(
            "ℹ️ Распределение по группам может корректироваться организаторами."
        )
''',
    '''        notes.append("ℹ️ Группы могут корректироваться организаторами.")
''',
)

replace_once(
    pinned,
    '''                f'📎 <a href="{SPORT_MEDICAL_CERTIFICATE_URL}"><b>Скачать бланк</b></a>',
                f"✉️ <b>Отправить:</b> <code>{SPORTS_CONTACT_EMAIL}</code>",
''',
    '''                f'📎 <a href="{SPORT_MEDICAL_CERTIFICATE_URL}">Скачать бланк</a>',
                "✉️ <b>Отправить справку:</b>",
                f"<code>{SPORTS_CONTACT_EMAIL}</code>",
''',
)

# Existing test expectations.
tp = Path("tests/test_pinned.py")
text = tp.read_text(encoding="utf-8")
text = text.replace(
    '        self.assertIn("Piscina Climatizada Manel Estiarte", indoor)\n',
    '        self.assertIn("Открыть на карте", indoor)\n',
)
text = text.replace(
    '        self.assertIn("Av. de Cervantes, s/n", indoor)\n',
    '        self.assertNotIn("Av. de Cervantes, s/n", indoor)\n',
)
text = text.replace(
    '        self.assertIn("Piscinas Descubiertas Municipales", outdoor)\n',
    '        self.assertIn("Открыть на карте", outdoor)\n',
)
text = text.replace(
    '        self.assertIn("Av. Europa, 3", outdoor)\n',
    '        self.assertNotIn("Av. Europa, 3", outdoor)\n',
)
tp.write_text(text, encoding="utf-8")

ty = Path("tests/test_youth_centre_place.py")
text = ty.read_text(encoding="utf-8")
marker = '        self.assertIn(YOUTH_CENTRE_MAP_URL, message)\n'
if marker not in text:
    raise SystemExit("youth marker missing")
text = text.replace(
    marker,
    marker
    + '        self.assertIn("Открыть на карте", message)\n'
    + '        self.assertNotIn("Calle Molivent", message)\n',
)
ty.write_text(text, encoding="utf-8")

tpa = Path("tests/test_palau_activity_ux.py")
text = tpa.read_text(encoding="utf-8")
text = text.replace(
    '  \'📝 <a href="https://play.sporttia.com/activities/85509"><b>Запись в группу</b></a>\',',
    '  \'📝 <a href="https://play.sporttia.com/activities/85509">Записаться</a>\',',
)
text = text.replace(
    '        self.assertNotIn("<b>Запись в группу</b>", card)\n',
    '        self.assertNotIn(">Записаться</a>", card)\n',
)
text = text.replace(
    '  parent.index("Также в комплексе"),\n',
    '  parent.index("Другие зоны"),\n',
)
anchor = '        self.assertIn("<code>965357693</code>", card)\n'
if anchor not in text:
    raise SystemExit("palau anchor missing")
text = text.replace(
    anchor,
    anchor
    + '        self.assertIn("Открыть на карте", card)\n'
    + '        self.assertNotIn("Av. Europa, s/n", card)\n'
    + '        self.assertIn("✉️ <b>Email:</b>\\n<code>deportesguardamar@hotmail.com</code>", card)\n',
)
anchor2 = '        self.assertIn("<code>juventudguardamar@gmail.com</code>", youth)\n'
if anchor2 not in text:
    raise SystemExit("youth UX anchor missing")
text = text.replace(
    anchor2,
    anchor2
    + '        self.assertIn("Открыть на карте", youth)\n'
    + '        self.assertNotIn("Calle Molivent", youth)\n',
)
tpa.write_text(text, encoding="utf-8")

adr = Path("adr/0069-automated-sporttia-activity-cards.md")
text = adr.read_text(encoding="utf-8")
heading = "## Mobile guide UX and recovery invariant"
if heading not in text:
    addition = '''
## Mobile guide UX and recovery invariant

Place cards use one explicit `Открыть на карте` action and omit textual street
addresses. Contact values remain copyable; long email values are rendered on a
separate line. Sport group cards keep source `turno` identity but use compact
`Записаться` / `Страница группы` actions and avoid blank rows between groups.

The self-healing graph covers both durable guide cards and source-managed sport
cards. If a sport card is deleted, it is recreated and both the activities index
and Palau card are relinked. If Palau is deleted, Polideportivo and every sport
card are relinked to the replacement. This recovery must not add any source
requests.
'''
    adr.write_text(text.rstrip() + "\n\n" + addition.lstrip(), encoding="utf-8")
