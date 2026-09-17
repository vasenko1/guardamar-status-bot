from pathlib import Path

PINNED = Path("src/telegrambot/pinned.py")
TEST = Path("tests/test_activity_index_ux.py")
MUSIC_TEST = Path("tests/test_music_pinned.py")
DOC = Path("docs/kb/11_Pinned_Message_Content.md")

text = PINNED.read_text(encoding="utf-8")

old_meta = '''MUSIC_ACTIVITY_META = {\n    "music_basics": ("🎶", "Музыкальное развитие и грамота"),\n    "music_vocal": ("🎤", "Вокал и хор"),\n    "music_instruments": ("🎷", "Музыкальные инструменты"),\n}\n'''
new_meta = old_meta + '''\nSPORT_ACTIVITY_INDEX_KEYS = (\n    "rhythmic_gymnastics",\n    "judo",\n    "multisport",\n    "psychomotricity",\n    "deporte_plus",\n    "inclusive_multisport",\n    "senior_gymnastics",\n    "women_gymnastics",\n)\nSPORT_ACTIVITY_INDEX_LABELS = {\n    "psychomotricity": "Психомоторика · 3–5 лет",\n    "inclusive_multisport": "Инклюзивный мультиспорт · 6+",\n    "senior_gymnastics": "Гимнастика для старших",\n    "women_gymnastics": "Гимнастика Mujeres",\n}\nMUSIC_ACTIVITY_INDEX_LABELS = {\n    "music_basics": "Музыкальная грамота",\n    "music_instruments": "Инструменты",\n}\n'''
if old_meta not in text:
    raise SystemExit("metadata anchor not found")
text = text.replace(old_meta, new_meta, 1)

old_build = '''    lines = [\n        "🎓 <b>Занятия и секции</b>",\n        "",\n        "🏃 <b>Спорт и движение</b>",\n        f"🏊 {_direct_link('Плавание', swimming_link)}",\n    ]\n    for key in SPORTTIA_ACTIVITY_KEYS:\n        link = sport_links.get(key)\n        if link is None:\n            continue\n        emoji, label = SPORT_ACTIVITY_META[key]\n        lines.append(f"{emoji} {_direct_link(label, link)}")\n    lines.append(f"⚽ {_direct_link('Футбол', football_link)}")\n'''
new_build = '''    lines = [\n        "🎓 <b>Занятия и секции</b>",\n        "",\n        "🏃 <b>Спорт и движение</b>",\n        f"⚽ {_direct_link('Футбол', football_link)}",\n        f"🏊 {_direct_link('Плавание', swimming_link)}",\n    ]\n    for key in SPORT_ACTIVITY_INDEX_KEYS:\n        link = sport_links.get(key)\n        if link is None:\n            continue\n        emoji, default_label = SPORT_ACTIVITY_META[key]\n        label = SPORT_ACTIVITY_INDEX_LABELS.get(key, default_label)\n        lines.append(f"{emoji} {_direct_link(label, link)}")\n'''
if old_build not in text:
    raise SystemExit("build_activities sports anchor not found")
text = text.replace(old_build, new_build, 1)

old_music = '''        for key, link in linked_music:\n            emoji, label = MUSIC_ACTIVITY_META[key]\n            lines.append(f"{emoji} {_direct_link(label, link)}")\n'''
new_music = '''        for key, link in linked_music:\n            emoji, default_label = MUSIC_ACTIVITY_META[key]\n            label = MUSIC_ACTIVITY_INDEX_LABELS.get(key, default_label)\n            lines.append(f"{emoji} {_direct_link(label, link)}")\n'''
if old_music not in text:
    raise SystemExit("build_activities music anchor not found")
text = text.replace(old_music, new_music, 1)
PINNED.write_text(text, encoding="utf-8")

TEST.write_text('''import unittest\n\nfrom telegrambot.pinned import build_activities\nfrom telegrambot.sporttia import SPORTTIA_ACTIVITY_KEYS\n\n\nclass ActivityIndexUxTests(unittest.TestCase):\n    def _render(self):\n        sport_links = {\n            key: f"https://t.me/c/123/{100 + index}"\n            for index, key in enumerate(SPORTTIA_ACTIVITY_KEYS)\n        }\n        music_links = {\n            "music_basics": "https://t.me/c/123/201",\n            "music_vocal": "https://t.me/c/123/202",\n            "music_instruments": "https://t.me/c/123/203",\n        }\n        return build_activities(\n            swimming_link="https://t.me/c/123/90",\n            sport_links=sport_links,\n            football_link="https://t.me/c/123/91",\n            music_links=music_links,\n        )\n\n    def test_sport_order_is_curated_for_mobile_scan(self):\n        text = self._render()\n        labels = [\n            "Футбол",\n            "Плавание",\n            "Художественная гимнастика",\n            "Дзюдо",\n            "Мультиспорт",\n            "Психомоторика · 3–5 лет",\n            "DEPORTE +",\n            "Инклюзивный мультиспорт · 6+",\n            "Гимнастика для старших",\n            "Гимнастика Mujeres",\n        ]\n        positions = [text.index(label) for label in labels]\n        self.assertEqual(positions, sorted(positions))\n\n    def test_index_uses_short_informative_labels_only(self):\n        text = self._render()\n        for expected in (\n            "Психомоторика · 3–5 лет",\n            "Инклюзивный мультиспорт · 6+",\n            "Гимнастика для старших",\n            "Гимнастика Mujeres",\n            "Музыкальная грамота",\n            "Вокал и хор",\n            "Инструменты",\n        ):\n            self.assertIn(expected, text)\n        for old in (\n            "Гимнастика для старшего возраста",\n            "Гимнастика Asociación Mujeres",\n            "Музыкальное развитие и грамота",\n            "Музыкальные инструменты",\n        ):\n            self.assertNotIn(old, text)\n\n    def test_detail_card_titles_are_not_changed_by_index_labels(self):\n        from telegrambot.pinned import MUSIC_ACTIVITY_META, SPORT_ACTIVITY_META\n\n        self.assertEqual(\n            SPORT_ACTIVITY_META["senior_gymnastics"][1],\n            "Гимнастика для старшего возраста",\n        )\n        self.assertEqual(\n            SPORT_ACTIVITY_META["women_gymnastics"][1],\n            "Гимнастика Asociación Mujeres",\n        )\n        self.assertEqual(\n            MUSIC_ACTIVITY_META["music_basics"][1],\n            "Музыкальное развитие и грамота",\n        )\n        self.assertEqual(\n            MUSIC_ACTIVITY_META["music_instruments"][1],\n            "Музыкальные инструменты",\n        )\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

music_test = MUSIC_TEST.read_text(encoding="utf-8")
old_music_test = '''        self.assertLess(text.index("Музыкальное развитие и грамота"), text.index("Вокал и хор"))\n        self.assertLess(text.index("Вокал и хор"), text.index("Музыкальные инструменты"))\n'''
new_music_test = '''        self.assertLess(text.index("Музыкальная грамота"), text.index("Вокал и хор"))\n        self.assertLess(text.index("Вокал и хор"), text.index("Инструменты"))\n'''
if old_music_test not in music_test:
    raise SystemExit("music index test anchor not found")
music_test = music_test.replace(old_music_test, new_music_test, 1)
MUSIC_TEST.write_text(music_test, encoding="utf-8")

doc = DOC.read_text(encoding="utf-8")
old_doc = '''`🎓 Занятия и секции` remains one message. Sports are visually grouped under\n`🏃 Спорт и движение`; music is visually grouped under `🎵 Музыка`. These are\npresentation only and do not create another Telegram navigation layer. The music\ngroup contains `Музыкальное развитие и грамота`, `Вокал и хор`, and\n`Музыкальные инструменты`. Source-managed and durable static activities share\nthe same index while retaining their different source/recovery semantics.\n'''
new_doc = '''`🎓 Занятия и секции` remains one message. Sports are visually grouped under\n`🏃 Спорт и движение`; music is visually grouped under `🎵 Музыка`. These are\npresentation only and do not create another Telegram navigation layer. The index\nis mobile-first: use a curated resident-facing order instead of source/insertion\norder, keep labels short where meaning is preserved, and surface age directly\nwhen it materially helps selection. Current compact labels include\n`Психомоторика · 3–5 лет`, `Инклюзивный мультиспорт · 6+`,\n`Гимнастика для старших`, `Гимнастика Mujeres`, `Музыкальная грамота`,\n`Вокал и хор`, and `Инструменты`. Detail-card titles remain explicit and may be\nlonger than their index labels. Source-managed and durable static activities\nshare the same index while retaining their different source/recovery semantics.\n'''
if old_doc not in doc:
    raise SystemExit("documentation anchor not found")
doc = doc.replace(old_doc, new_doc, 1)
DOC.write_text(doc, encoding="utf-8")
