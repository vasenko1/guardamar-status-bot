from pathlib import Path

replacements = {
    "src/telegrambot/pinned.py": [
        ('"psychomotricity": "Психомоторика · 3–5 лет"', '"psychomotricity": "Психомоторика · 2–6 лет"'),
        ('"inclusive_multisport": "Инклюзивный мультиспорт · 6+"', '"inclusive_multisport": "Инклюзивный мультиспорт · 7+"'),
    ],
    "tests/test_activity_index_ux.py": [
        ('Психомоторика · 3–5 лет', 'Психомоторика · 2–6 лет'),
        ('Инклюзивный мультиспорт · 6+', 'Инклюзивный мультиспорт · 7+'),
    ],
    "docs/kb/11_Pinned_Message_Content.md": [
        ('`Психомоторика · 3–5 лет`, `Инклюзивный мультиспорт · 6+`', '`Психомоторика · 2–6 лет`, `Инклюзивный мультиспорт · 7+`'),
    ],
}

for filename, pairs in replacements.items():
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"missing anchor in {filename}: {old}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
