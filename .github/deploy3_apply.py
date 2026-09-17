from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


PINNED = "src/telegrambot/pinned.py"
GUIDE = "src/telegrambot/guide.py"
TEST_GUIDE = "tests/test_guide.py"

# pinned.py imports + explicit metadata.
replace_once(
    PINNED,
    "from .branding import FOOTER, with_footer\nfrom .sporttia import (",
    "from .branding import FOOTER, with_footer\n"
    "from .music_school import (\n"
    "    SCHOOL_ADDRESS,\n"
    "    SCHOOL_EMAIL,\n"
    "    SCHOOL_MAP_URL,\n"
    "    SCHOOL_PHONE,\n"
    "    SCHOOL_SITE_URL,\n"
    "    registration_is_open as music_registration_is_open,\n"
    ")\n"
    "from .sporttia import (",
)
replace_once(
    PINNED,
    '    "psychomotricity": ("🧒", "Психомоторика"),\n}\n\nSend =',
    '    "psychomotricity": ("🧒", "Психомоторика"),\n}\n'
    'MUSIC_ACTIVITY_KEYS = (\n'
    '    "music_basics",\n'
    '    "music_vocal",\n'
    '    "music_instruments",\n'
    ')\n'
    'MUSIC_ACTIVITY_META = {\n'
    '    "music_basics": ("🎶", "Музыкальное развитие и грамота"),\n'
    '    "music_vocal": ("🎤", "Вокал и хор"),\n'
    '    "music_instruments": ("🎷", "Музыкальные инструменты"),\n'
    '}\n\nSend =',
)
replace_once(
    PINNED,
    '    "les_raboses",\n    "molivent",\n    "youth_centre",',
    '    "les_raboses",\n    "molivent",\n    "music_school",\n    "youth_centre",',
)
replace_once(
    PINNED,
    '    "les_raboses": "places",\n    "molivent": "places",\n    "youth_centre": "places",',
    '    "les_raboses": "places",\n    "molivent": "places",\n    "music_school": "places",\n    "youth_centre": "places",',
)
replace_once(
    PINNED,
    '    "swimming": "activities",\n    "football": "activities",\n}',
    '    "swimming": "activities",\n    "football": "activities",\n'
    '    **{key: "activities" for key in MUSIC_ACTIVITY_KEYS},\n}',
)

# Places index and durable school card.
replace_once(
    PINNED,
    "    youth_centre_link: Optional[str] = None,\n"
    "    les_raboses_link: Optional[str] = None,\n"
    "    molivent_link: Optional[str] = None,\n"
    ") -> str:",
    "    youth_centre_link: Optional[str] = None,\n"
    "    les_raboses_link: Optional[str] = None,\n"
    "    molivent_link: Optional[str] = None,\n"
    "    music_school_link: Optional[str] = None,\n"
    ") -> str:",
)
replace_once(
    PINNED,
    "            f\"🏫 {_direct_link('CEIP Molivent', molivent_link)}\\n\"\n"
    "            \"Здесь проходят муниципальные занятия для детей.\\n\\n\"\n"
    "            f\"👥 {_direct_link('Centro Social Juvenil', youth_centre_link)}\\n\"",
    "            f\"🏫 {_direct_link('CEIP Molivent', molivent_link)}\\n\"\n"
    "            \"Здесь проходят муниципальные занятия для детей.\\n\\n\"\n"
    "            f\"🎼 {_direct_link('Escuela de Música', music_school_link)}\\n\"\n"
    "            \"Музыкальная школа Agrupación Musical de Guardamar.\\n\\n\"\n"
    "            f\"👥 {_direct_link('Centro Social Juvenil', youth_centre_link)}\\n\"",
)

music_school_builder = '''

def build_music_school(
    music_links: Optional[Mapping[str, str]] = None,
    places_link: Optional[str] = None,
) -> str:
    """Build the durable school card shared by music activity cards."""

    lines = [
        "🎼 <b>Escuela de Música</b>",
        "",
        "Музыкальная школа Agrupación Musical de Guardamar.",
        "",
        f'<a href="{html.escape(SCHOOL_MAP_URL, quote=True)}">📍 <b>Открыть на карте</b></a>',
        html.escape(SCHOOL_ADDRESS),
        "",
        f"📞 <b>Телефон:</b> <code>{SCHOOL_PHONE}</code>",
        "✉️ <b>Email:</b>",
        f"<code>{SCHOOL_EMAIL}</code>",
        f'<a href="{html.escape(SCHOOL_SITE_URL, quote=True)}">🌐 <b>Сайт школы</b></a>',
    ]
    music_links = music_links or {}
    linked = [
        (key, music_links[key])
        for key in MUSIC_ACTIVITY_KEYS
        if key in music_links
    ]
    if linked:
        lines.extend(["", "🎓 <b>Занятия:</b>"])
        for key, link in linked:
            emoji, label = MUSIC_ACTIVITY_META[key]
            lines.append(f"{emoji} {_direct_link(label, link)}")
    return _with_back_link(
        with_footer("\\n".join(lines)),
        "К списку мест",
        places_link,
    )
'''
replace_once(PINNED, "\n\ndef build_pool_indoor(\n", music_school_builder + "\n\ndef build_pool_indoor(\n")

# Activities index: one visual music group, no extra navigator.
replace_once(
    PINNED,
    "    sport_links: Optional[Mapping[str, str]] = None,\n"
    "    football_link: Optional[str] = None,\n"
    ") -> str:",
    "    sport_links: Optional[Mapping[str, str]] = None,\n"
    "    football_link: Optional[str] = None,\n"
    "    music_links: Optional[Mapping[str, str]] = None,\n"
    ") -> str:",
)
replace_once(
    PINNED,
    "    lines.append(f\"⚽ {_direct_link('Футбол', football_link)}\")\n"
    "    return _with_back_link(",
    "    lines.append(f\"⚽ {_direct_link('Футбол', football_link)}\")\n"
    "    music_links = music_links or {}\n"
    "    linked_music = [\n"
    "        (key, music_links[key])\n"
    "        for key in MUSIC_ACTIVITY_KEYS\n"
    "        if key in music_links\n"
    "    ]\n"
    "    if linked_music:\n"
    "        lines.extend([\"\", \"🎵 <b>Музыка</b>\"])\n"
    "        for key, link in linked_music:\n"
    "            emoji, label = MUSIC_ACTIVITY_META[key]\n"
    "            lines.append(f\"{emoji} {_direct_link(label, link)}\")\n"
    "    return _with_back_link(",
)

music_activity_builder = '''

def _music_place_line(school_link: Optional[str]) -> str:
    return "  📍 " + _direct_link(
        "Escuela de Música",
        school_link or SCHOOL_MAP_URL,
    )


def _append_music_schedule(
    lines: list,
    catalog: Mapping[str, object],
) -> None:
    url = catalog.get("schedule_url")
    season = catalog.get("season")
    if not isinstance(url, str) or not url:
        return
    label = "Расписание групп"
    if isinstance(season, str) and season:
        label += f" {html.escape(season)}"
    lines.append(
        f'  📅 <a href="{html.escape(url, quote=True)}">{label}</a>'
    )


def build_music_activity(
    key: str,
    catalog: Mapping[str, object],
    local_day: date,
    activities_link: Optional[str] = None,
    school_link: Optional[str] = None,
) -> str:
    """Build one compact music card; school contacts stay on the place card."""

    if key not in MUSIC_ACTIVITY_META:
        raise ValueError(f"unknown music activity key: {key}")
    emoji, title = MUSIC_ACTIVITY_META[key]
    lines = [f"{emoji} <b>{title}</b>", ""]

    if key == "music_basics":
        lines.extend([
            "• <b>Jardín Musical</b> · 3–6 лет",
            "  1 час в неделю · занятия Пн–Чт",
        ])
        if music_registration_is_open(
            catalog, "jardin_registration", local_day
        ):
            registration = catalog.get("jardin_registration")
            if isinstance(registration, Mapping):
                url = registration.get("url")
                if isinstance(url, str) and url:
                    lines.append(
                        f'  📝 <a href="{html.escape(url, quote=True)}">Записаться</a>'
                    )
        lines.append(_music_place_line(school_link))
        lines.extend([
            "",
            "• <b>Lenguaje Musical</b> · с 7 лет",
            "  2 часа в неделю",
        ])
        _append_music_schedule(lines, catalog)
        lines.append(_music_place_line(school_link))
        lines.extend([
            "",
            "• <b>Lenguaje Musical para Adultos</b> · 18+",
        ])
        _append_music_schedule(lines, catalog)
        lines.append(_music_place_line(school_link))
    elif key == "music_vocal":
        lines.append("• <b>Técnica Vocal / Coro</b>")
        _append_music_schedule(lines, catalog)
        lines.append(_music_place_line(school_link))
    else:
        lines.extend([
            "• <b>Духовые инструменты</b>",
            "  кларнет · саксофон · флейта · гобой · фагот",
            "  труба · тромбон · валторна · эуфониум · туба",
            _music_place_line(school_link),
            "",
            "• <b>Другие инструменты</b>",
            "  ударные · виолончель · дульсайна · гитара · фортепиано",
            _music_place_line(school_link),
        ])

    return _with_back_link(
        with_footer("\\n".join(lines)),
        "К занятиям и секциям",
        activities_link,
    )
'''
replace_once(PINNED, "\n\ndef build_football(\n", music_activity_builder + "\n\ndef build_football(\n")

# Static preview includes the place card; source-backed music cards stay dynamic.
replace_once(
    PINNED,
    "        build_molivent(),\n        build_youth_centre(),",
    "        build_molivent(),\n        build_music_school(),\n        build_youth_centre(),",
)

# Link graph rendering.
replace_once(
    PINNED,
    '    molivent_link = _known_link(chat_id, messages, "molivent")\n'
    '    youth_centre_link = _known_link(chat_id, messages, "youth_centre")',
    '    molivent_link = _known_link(chat_id, messages, "molivent")\n'
    '    music_school_link = _known_link(chat_id, messages, "music_school")\n'
    '    youth_centre_link = _known_link(chat_id, messages, "youth_centre")',
)
replace_once(
    PINNED,
    "    for key in SPORTTIA_ACTIVITY_KEYS:\n"
    "        link = _known_link(chat_id, messages, key)\n"
    "        if link is not None:\n"
    "            sport_links[key] = link\n"
    "    leaf_links = None",
    "    for key in SPORTTIA_ACTIVITY_KEYS:\n"
    "        link = _known_link(chat_id, messages, key)\n"
    "        if link is not None:\n"
    "            sport_links[key] = link\n"
    "    music_links = {}\n"
    "    for key in MUSIC_ACTIVITY_KEYS:\n"
    "        link = _known_link(chat_id, messages, key)\n"
    "        if link is not None:\n"
    "            music_links[key] = link\n"
    "    leaf_links = None",
)
replace_once(
    PINNED,
    "            youth_centre_link,\n"
    "            les_raboses_link,\n"
    "            molivent_link,\n"
    "        ),",
    "            youth_centre_link,\n"
    "            les_raboses_link,\n"
    "            molivent_link,\n"
    "            music_school_link,\n"
    "        ),",
)
replace_once(
    PINNED,
    "        \"molivent\": build_molivent(\n"
    "            sport_links.get(\"psychomotricity\"),\n"
    "            places_link,\n"
    "        ),\n"
    "        \"youth_centre\": build_youth_centre(places_link),",
    "        \"molivent\": build_molivent(\n"
    "            sport_links.get(\"psychomotricity\"),\n"
    "            places_link,\n"
    "        ),\n"
    "        \"music_school\": build_music_school(music_links, places_link),\n"
    "        \"youth_centre\": build_youth_centre(places_link),",
)
replace_once(
    PINNED,
    "            sport_links,\n"
    "            football_link,\n"
    "        ),",
    "            sport_links,\n"
    "            football_link,\n"
    "            music_links,\n"
    "        ),",
)

# publish_pinned_guide accepts and reconciles the normalized music snapshot.
replace_once(
    PINNED,
    "    sporttia_catalog: Optional[Mapping[str, object]] = None,\n"
    "    local_day: Optional[date] = None,",
    "    sporttia_catalog: Optional[Mapping[str, object]] = None,\n"
    "    music_school_catalog: Optional[Mapping[str, object]] = None,\n"
    "    local_day: Optional[date] = None,",
)
replace_once(
    PINNED,
    "    if sporttia_catalog is not None and local_day is None:\n"
    "        raise ValueError(\"local_day is required with Sporttia catalogue\")",
    "    if sporttia_catalog is not None and local_day is None:\n"
    "        raise ValueError(\"local_day is required with Sporttia catalogue\")\n"
    "    if music_school_catalog is not None and local_day is None:\n"
    "        raise ValueError(\"local_day is required with music-school catalogue\")",
)
replace_once(
    PINNED,
    "        await _reconcile_messages(\n"
    "            chat_id, messages, state, send, edit, managed_elsewhere\n"
    "        )\n"
    "    try:\n"
    "        await pin(messages[\"root\"])",
    "        await _reconcile_messages(\n"
    "            chat_id, messages, state, send, edit, managed_elsewhere\n"
    "        )\n"
    "    if music_school_catalog is not None:\n"
    "        assert local_day is not None\n"
    "        activities_link = _known_link(chat_id, messages, \"activities\")\n"
    "        school_link = _known_link(chat_id, messages, \"music_school\")\n"
    "        for key in MUSIC_ACTIVITY_KEYS:\n"
    "            await _upsert(\n"
    "                key,\n"
    "                build_music_activity(\n"
    "                    key,\n"
    "                    music_school_catalog,\n"
    "                    local_day,\n"
    "                    activities_link,\n"
    "                    school_link,\n"
    "                ),\n"
    "                messages,\n"
    "                state,\n"
    "                chat_id,\n"
    "                send,\n"
    "                edit,\n"
    "            )\n"
    "        await _reconcile_messages(\n"
    "            chat_id, messages, state, send, edit, managed_elsewhere\n"
    "        )\n"
    "    try:\n"
    "        await pin(messages[\"root\"])",
)

# guide.py imports and state validation.
replace_once(
    GUIDE,
    "from .pinned import (\n",
    "from .music_school import (\n"
    "    MusicSchoolSourceError,\n"
    "    fetch_music_school_catalog,\n"
    "    merge_music_school_catalog,\n"
    "    valid_music_school_snapshot,\n"
    ")\n"
    "from .pinned import (\n",
)
replace_once(
    GUIDE,
    "        sporttia_attempt_day = value.get(\"sporttia_last_attempt_day\")\n",
    "        music_school = value.get(\"music_school_catalog\")\n"
    "        if music_school is not None and not valid_music_school_snapshot(music_school):\n"
    "            raise StateError(\"guide state has an invalid music-school snapshot\")\n"
    "        music_attempt_day = value.get(\"music_school_last_attempt_day\")\n"
    "        if music_attempt_day is not None:\n"
    "            if not isinstance(music_attempt_day, str):\n"
    "                raise StateError(\"guide state has an invalid music-school attempt day\")\n"
    "            try:\n"
    "                date.fromisoformat(music_attempt_day)\n"
    "            except ValueError as exc:\n"
    "                raise StateError(\n"
    "                    \"guide state has an invalid music-school attempt day\"\n"
    "                ) from exc\n"
    "        sporttia_attempt_day = value.get(\"sporttia_last_attempt_day\")\n",
)

# Daily bounded observation after Sporttia, before Wi-Fi/reconciliation.
replace_once(
    GUIDE,
    "        await _check_wifi_source(bot_token, state, guide_state)\n",
    "        previous_music = state.get(\"music_school_catalog\")\n"
    "        if state.get(\"music_school_last_attempt_day\") != local_day.isoformat():\n"
    "            state[\"music_school_last_attempt_day\"] = local_day.isoformat()\n"
    "            guide_state.write(state)\n"
    "            try:\n"
    "                observed_music = await fetch_music_school_catalog(now)\n"
    "            except MusicSchoolSourceError as exc:\n"
    "                logging.warning(\n"
    "                    \"Music-school catalogue deferred [GUIDE-%s]\",\n"
    "                    exc.diagnostic_code,\n"
    "                )\n"
    "            else:\n"
    "                state[\"music_school_catalog\"] = merge_music_school_catalog(\n"
    "                    previous_music, observed_music\n"
    "                )\n"
    "                guide_state.write(state)\n\n"
    "        await _check_wifi_source(bot_token, state, guide_state)\n",
)
replace_once(
    GUIDE,
    "                sporttia_catalog=state.get(\"sporttia_catalog\"),\n"
    "                local_day=local_day,",
    "                sporttia_catalog=state.get(\"sporttia_catalog\"),\n"
    "                music_school_catalog=state.get(\"music_school_catalog\"),\n"
    "                local_day=local_day,",
)

# Existing guide tests must never hit the public music source.
replace_once(
    TEST_GUIDE,
    "        self.sporttia_patch.start()\n"
    "        self.addCleanup(self.sporttia_patch.stop)\n",
    "        self.sporttia_patch.start()\n"
    "        self.addCleanup(self.sporttia_patch.stop)\n"
    "        self.music_fetch = AsyncMock(\n"
    "            side_effect=lambda now: {\n"
    "                \"observed_at\": now.isoformat(),\n"
    "                \"season\": \"2026/27\",\n"
    "                \"schedule_url\": None,\n"
    "                \"jardin_registration\": None,\n"
    "                \"school_registration\": None,\n"
    "            }\n"
    "        )\n"
    "        self.music_patch = patch(\n"
    "            \"telegrambot.guide.fetch_music_school_catalog\",\n"
    "            new=self.music_fetch,\n"
    "        )\n"
    "        self.music_patch.start()\n"
    "        self.addCleanup(self.music_patch.stop)\n",
)

# Add one explicit once-per-day assertion for the new source.
anchor = "    async def test_sporttia_failure_is_not_retried_same_day(self):\n"
new_test = '''    async def test_music_school_is_attempted_at_most_once_per_local_day(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 16, 14, 0, tzinfo=MADRID)
            later = datetime(2026, 9, 16, 16, 30, tzinfo=MADRID)
            current = snapshot(moment)
            publish = AsyncMock(return_value=self._pinned_messages())
            with (
                patch.dict("os.environ", self._environment(directory), clear=False),
                patch(
                    "telegrambot.guide.fetch_aqualider_catalog",
                    new=AsyncMock(return_value=current),
                ),
                patch("telegrambot.guide.publish_pinned_guide", new=publish),
            ):
                await sync_guide(moment)
                await sync_guide(later)
            self.assertEqual(self.music_fetch.await_count, 1)
            saved = GuideState(Path(directory) / "guide.json").read()
            self.assertEqual(
                saved["music_school_last_attempt_day"], "2026-09-16"
            )
            self.assertEqual(saved["music_school_catalog"]["season"], "2026/27")

'''
replace_once(TEST_GUIDE, anchor, new_test + anchor)

print("Deploy 3 minimal integration patch applied")
