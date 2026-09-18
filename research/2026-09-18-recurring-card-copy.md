# Recurring activity Telegram card copy — 2026-09-18

Status: proposed exact resident-facing copy for the first implementation slice.
The wording follows the existing compact `pinned.py` activity-card style:
activity-first, only current source-backed facts, one back link, no provider
advertising.

## Activities index

Do not add a new navigation message/state layer. Extend the existing
`🎓 Занятия и секции` card with one visual section after Music:

```text
🧩 Другие занятия
♟️ Шахматы
✍️ Литературное творчество
🤝 Муниципальные занятия и мастерские
```

Each row is a normal Telegram link to its durable card.

Do not expose Creative Workshops, EPA/EOI/Cruz Roja language cards or
commercial providers in the index yet.

## Chess

Exact body before the standard footer/back link:

```text
♟️ <b>Шахматы</b>

Школа шахмат — от начинающего до продвинутого уровня.

🗓 <b>Вторник и четверг · 16:00–20:00</b>
Конкретное время зависит от уровня группы.

🔎 <a href="{source_url}"><b>Информация о занятиях</b></a>
```

Then the standard existing:

```text
← К занятиям и секциям
```

Source facts intentionally omitted from resident copy:

- provider branding is not the card title;
- no phone from the old 2023 Promochess article;
- no exact current age range because the 2026 source does not state one;
- no current venue claim unless a current source explicitly ties the school
  classes to a venue. The 2026 club page identifies the club headquarters at
  Escuela de Música but does not explicitly state that the Tuesday/Thursday
  school classes occur there.

## Tertulia Literaria

Exact body:

```text
✍️ <b>Литературное творчество</b>

<b>Tertulia Literaria de Guardamar</b>
Еженедельная литературная группа.

🗓 <b>Каждый вторник · 11:00–13:00</b>
📍 Актовый зал муниципальной библиотеки

🔎 <a href="{source_url}"><b>Подробнее</b></a>
```

Then the standard back link:

```text
← К занятиям и секциям
```

Do not invent price, registration requirement or vacancy status.

## Dinamización Social

Card title stays resident-facing rather than using the campaign name as the
primary title.

Exact body for the current accepted 2026/27 snapshot:

```text
🤝 <b>Муниципальные занятия и мастерские</b>

Программа Dinamización Social 2026/2027.

• <b>Осознанное движение</b>
  Пн/Ср · 11:15–12:15 или 12:15–13:15

• <b>Как пользоваться смартфоном</b>
  Вт/Чт · 09:30–10:30 или 10:30–11:30
  С 10 ноября

• <b>Творчество из переработанных материалов</b>
  Пн/Ср · 16:30–18:30

• <b>Роспись по ткани</b>
  Пт · 16:30–18:30

• <b>Прогулки для старшего возраста</b>
  Пн/Ср · 16:00–17:30 или 17:30–19:00

• <b>Тренировка памяти</b>
  Вт/Чт · 16:30–18:00 или 18:00–19:30

• <b>Компьютерная грамотность</b>
  Пн/Ср · 17:00–18:00 или 18:00–19:00

• <b>Школа эмоций</b>
  Ср · 09:30–11:00
  14 октября — 16 декабря

📝 Основной период записи завершился 16 сентября.
После него запись может продолжаться, пока остаются места.

🏠 Приоритет — жителям Guardamar.

📝 <a href="{form_url}"><b>Форма записи</b></a>
```

Then the standard back link:

```text
← К занятиям и секциям
```

Important wording invariant:

- never change `может продолжаться, пока остаются места` to `места есть`
  unless the source explicitly confirms current capacity;
- if the form explicitly closes, remove/replace the registration CTA according
  to the normalized source state instead of leaving a dead `Записаться`;
- source failure preserves the last-good card; it does not imply cancellation.

## Creative workshops

**Do not publish a card yet.**

The transport/parser shape is ready at zero additional network cost, but the
official September 2026 source still labels the block `TALLERES 2025/2026`.
Publishing a current recurring card would require deciding that the unlabeled
September registration dates override the stale season title. Fail closed
instead.

Once the official source becomes unambiguous, the intended compact card shape
is:

```text
🎨 <b>Творческие мастерские</b>

• Живопись
• Керамика
• Patchwork
• Кройка и шитьё
• Работа с нитью

📝 <b>Запись: {registration_dates}</b>
🕘 {registration_hours}
📍 Casa de Cultura
⚠️ Места ограничены
```

plus the standard back link. Never invent a season number.

## Language cards

Do not publish a `🌍 Языковые курсы` section yet.

Current reasons:

- EPA transport works, but the current public machine surface does not contain
  enough exact current Spanish/English/Valencian timetable/vacancy facts;
- EOI Guardamar is real, but the tested vacancy entry page does not expose
  Guardamar-specific current groups in its initial response;
- Cruz Roja has no stable current first-party timetable/enrollment surface;
- PANGEA/INTEGRA appear only when an explicit current campaign exists;
- commercial schools/academies are excluded by product rule;
- therefore there is no production-ready public/municipal French or German card
  either.

Do not create an empty language hierarchy merely to reserve navigation space.
