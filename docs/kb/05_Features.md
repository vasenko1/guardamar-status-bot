# Features

## Next-day electricity prices

An evening message shows tomorrow's official PVPC 2.0TD hourly energy term for
Península in €/kWh. The fixed layout contains a two-column monospace 24-hour
table followed by the cheapest and most expensive period and a practical-use
recommendation. A concise persistent explanation defines PVPC as a
regulated Spanish tariff, tells readers to check `PVPC` in the contract type
on their bill, says the table covers the hourly consumed-energy component
rather than the whole bill, and makes clear that the prices do not apply to a
fixed tariff.

The header must say `завтра` and include the target date. The 24 prices are
ranked within that local day: the cheapest third is green, the middle third is
yellow, and the most expensive third is red. Equal boundary prices keep one
color rather than being split by hour. Ranking and extrema use the same
three-decimal price displayed to the reader. Every continuous run sharing the
visible minimum or maximum is shown, and adjacent equal hours form one range.
If all displayed prices are equal, one neutral all-day block replaces the two
extreme blocks. The main message ends with the longest
continuous run of green hours; equal-length runs prefer the lower total and
then the earlier start. If no hours are green, the recommendation is omitted.
The separate explanation carries the PVPC
scope, fixed-tariff limitation, and `ESIOS / Red Eléctrica` attribution.
Incomplete days are not published.

When that persistent explanation wording changes, the operator command
`electricity-update-explanation` edits the saved Telegram message in place.
It uses the message ID in the local publication state and neither publishes a
second explanation nor requests electricity data again.

Before public delivery, one complete response is normalized into a private
local snapshot for the target date. After that snapshot exists, the first
publication creates one explanation anchor and sends the table as its reply.
Later attempts do not repeat the ESIOS request; a
confirmed publication exits before any source access.

## Morning Digest

### Purpose

Keep one concise current overview of conditions and notable city information.

### User value

Reduce the effort needed to plan the day and notice important changes.

### Inputs

- Weather conditions and forecast
- Sea conditions
- Beach flag status
- Official warnings
- Important municipal updates
- Events relevant today

### Output

One compact Telegram message containing only current, reliable, useful items.
The user-facing message is fully Russian. AEMET attribution appears in the
weather heading rather than as a source footer.

### Canonical layout

This exact visual structure is the product contract:

```text
🌅 Доброе утро, Гуардамар!

🌤 **Погода от AEMET:**
**Воздух:** 24° → 31° • ясно → облачно
**Дождь:** 80% • 12:00–18:00
**Ветер:** СВ 5 → 7 м/с
**Море:** 29° • слабые → умеренные

⚠️ **Предупреждения AEMET:**
Зона: южное побережье Аликанте
🟠 **Опасные прибрежные явления**
   Завтра · 08:00–18:00 · вероятность 40–70%
🟡 **Высокая температура**
   Сегодня и завтра · 13:00–20:59 · вероятность 40–70%

🏖 **Флаги на пляжах:**
   🟡 Roqueta
   🟢 Centre / Babilònia, Vivers
🪼 Медузы: Roqueta

🚧 **Движение:**
• С 19:30 перекрыта Calle Mayor.
• Автобусы следуют по временному маршруту.

🎉 **Праздник сегодня:**
• Канун Дня святого Иакова — официальный городской праздник
  🏛️ Официальный выходной день.

📅 **События дня:**
• **07:00–13:30** — рынок
  📍 парковка La Redonda

• **21:00** — концерт в замке
  📍 Castillo
```

The order never changes:

1. Greeting
2. Weather heading with AEMET attribution, then air temperature and sky
3. Rain probability and period, only at 75% or above
4. Current wind with optional inline forecast
5. AEMET sea temperature and optional sea-state forecast
6. Warning
7. Available flags for all six known Guardamar beach zones, grouped by color
8. Jellyfish beaches, only when explicitly reported
9. Traffic or closure
10. Official holiday applicable in Guardamar today
11. Today's events

Each event is one bullet. Its official place, when available, is rendered on
the following indented `📍` line. Events are separated by one blank line;
unknown places do not create an empty location row.

The greeting must be exactly `🌅 Доброе утро, Гуардамар!`. The word
`дайджест` must not appear in the user-facing message.

Compact condition labels end with `:` and use one following space. Do not
align columns with runs of spaces. The sea row keeps the user-facing label
`Море`.

The weather heading uses the dynamic sky icon followed by
`Погода от AEMET:`. Internal weather rows have bold labels and no icons. Its
mandatory air row combines the temperature range and at most two remaining
AEMET sky states. Equal
adjacent states are collapsed; a change renders as `ясно → облачно`.
Sea and wind remain mandatory compact rows inside the same weather block.
Rain is one optional compact row. It uses the highest AEMET probability for an eligible remaining period
and appears only at `75%` or above; otherwise it is omitted. SafeBeach
operational rows are considered only from 20 June through 14 September,
inclusive. The flag row is shown only
when SafeBeach has at least one active nearby record. It names each available
beach and never averages flags. Groups use the fixed safety order red, yellow,
then green. Beach ordering is fixed as `Centre / Babilònia`, `Roqueta`,
`Vivers`, `Montcaio`, `Camp`, `Ortigues`. Within every color, split names into
semantic rows of at most three and let Telegram wrap naturally. When all six
current flags are green and no active municipal bathing prohibition conflicts,
render the compact `На всех пляжах`; otherwise list every verified name.
When at least one flag is current, unavailable beaches are omitted rather than
assigned a reassuring default. The sea
temperature and sea-state text use the AEMET
Centro / La Roqueta forecast. Equal sea-state periods render once as
`умеренные волны`; a change renders compactly as
`слабые → умеренные`, without repeating `волны`. SafeBeach Centre values are fallbacks when the
AEMET beach values are unavailable. The jellyfish row is
shown only for beaches where SafeBeach explicitly reports presence. A negative,
missing, or unknown jellyfish field produces no row. The wind
forecast is appended to the wind row as `→ <speed>` and is omitted when
unavailable. It never creates another row.

SafeBeach flag lines contain only the color and beach names. The generic
SafeBeach flag description is not repeated. Update times are used only for
internal freshness validation and are never shown in the user-facing digest.

The sky-row icon is dynamic from the existing AEMET daily sky forecast:
`☀️` clear, `🌤` partly cloudy, `☁️` cloudy, `🌫️` fog, `🌧️` rain,
`🌨️` snow, and `⛈️` storm. Keep at most the first and last distinct remaining
conditions, with one arrow. A transition uses `🌤`; a single state uses its
matching icon. Unknown or missing conditions use `🌤`.
The icon adds no text, AI, or new source.

Warning, traffic, and event sections are optional. Omit an entire optional
section when it has no verified, useful items. Do not render empty headings.
Every displayed section heading and every event time is bold through Telegram
HTML. Sections are separated by exactly one empty line. Warning hazards use
their severity dot and a bold Russian name; traffic items use `•` when more
than one is displayed.
The event section contains every deduplicated, verified official event relevant
today. There is no product count limit; bounded source reads and Telegram's
message limit remain technical safety boundaries.

The holiday section appears immediately before `📅 События дня:` and only on
an official paid, non-recoverable holiday applicable in Guardamar on that
Madrid local date. It uses the reviewed annual BOE/DOGV calendar already used
by the Wednesday-market rule; the bot never calculates transfers or carries
local dates into an unreviewed year. Entries use the fixed order national,
regional, then local. Labels are `национальный праздник`, `региональный
праздник`, and `официальный городской праздник`. The heading is singular or
plural according to the number of distinct holidays. On Monday through Friday
append `🏛️ Официальный выходной день.` directly below the holiday;
omit that explanatory line on
Saturday and Sunday. Never render `Сегодня рабочий день`. Ordinary festivals
and multi-day programmes remain events and do not enter this section merely
because they are celebrations.

Each event uses the compact order `{time or range} — {type and title}, {place}`.
When the official source has no time, omit only the time prefix and keep the
event. Preserve an explicit activity type or medium such as painting,
sculpture, concert, workshop, guided tour, or night route. Include the
official place when available. Never invent missing time, type, or place.
One short verified practical note, such as age, distance, language, or required
equipment, may follow the title in parentheses. Admission and participation
use one `🎟` row. The row may contain the regular price, a concrete registration
phone, WhatsApp, email, or official URL, and an explicit limited-capacity note.
Never say that registration is required without also giving its verified
action point. A generic organizer contact or a contact copied from another
event is not a registration point.

The message has no source footer, links, report-style title, explanatory prose,
or separate weather section. A routine day should fit on one phone screen and
be scannable in seconds. On an unusually busy day, verified events are not
discarded solely to preserve that visual limit.

### Implemented vertical slice

The first MVP slice covers Guardamar weather and AEMET warnings:

- current temperature and wind from AEMET's nearby Rojales observation
  station;
- today's minimum and maximum temperature from AEMET's Guardamar municipal
  forecast;
- the highest eligible remaining precipitation probability and its period
  when it is at least 75%;
- active and already published CAP warnings starting no later than tomorrow
  for Guardamar's warning zone, with exact start and end dates/times,
  probability, and a compact
  deterministic Russian rendering of recognized official hazard details;
- deterministic formatting with no runtime AI.

The canonical visual layout and inline later-day wind comparison are
implemented. ADR 0013 adds the dynamic AEMET weather icon without changing the
row layout.

All current, today, and tomorrow yellow, orange, and red warnings for the
Guardamar zone are shown; later warnings wait for a subsequent digest. Safety
warnings are not capped by a message-item limit. Matching level, hazard,
probability, and description may share one block; equal today/tomorrow hours
render as `Сегодня и завтра`. Different facts remain separate. The fixed zone
is named once, hazards are ordered red, orange, yellow, and each name is bold.
Hazards have no empty lines between them; their time and recognized detail
lines use one consistent indentation so the section reads as one list.
Spanish/English CAP duplicates and green `Minor` records are omitted. Unknown
description wording is never machine-translated or guessed: the warning,
validity period, and validated probability still remain visible.

The beach-status slice adds:

- every valid active flag among the six known Guardamar SafeBeach zones;
- today's AEMET water temperature and sea-state forecast for
  `Centro / La Roqueta`;
- Centre water temperature and sea state as SafeBeach fallbacks;
- omission of individual unavailable flags and sea state without blocking
  weather delivery or inventing a normal status.

Neither AEMET nor fallback logic supplies or infers a beach flag.

The event slice adds today's official ticketed Agenda Guardamar events from a
small catalog refreshed before the morning run. The refresh reads the title,
all explicitly dated sessions, local time range, and place, recovers the official calendar
venue when the site's JSON-LD contains only its publisher identifier,
translates titles to Russian, sorts chronologically, and removes duplicates.
When the official detail page publishes admission, the event adds one compact
`🎟 Билет …` link or `🎟 Бесплатно` row. A paid purchase URL is retained only
when its date and time match the occurrence. Reduced categories stay on the
official ticket page instead of expanding the morning digest.
Source failure or no event today omits that source's contribution.

The event section includes the recurring official Wednesday market.
Its official customer hours are `07:00–13:30` from June through September and
`08:00–13:30` during the rest of the year. This is a local calendar rule backed
by the Ayuntamiento ordinance; it requires no morning request, time inference,
or Gemini call. When Wednesday is an official holiday, the same ordinance
moves the market to the preceding Tuesday. A small annually reviewed Guardamar
holiday calendar applies this rule; an unreviewed year omits the market rather
than guessing.

On Sundays, the event section includes `Рынок Campo de Guardamar`,
`07:00–16:00`, at `Camino del Raso, 15`. This is a separate recurring rule
based on the market operator's published schedule. It is not passed through
the municipal Wednesday-market holiday calendar or Mayor-channel exception
check because no equivalent authoritative cancellation feed is available.

ADRs 0012 and 0028 implement a text-first expansion from the official Turismo
Guardamar agenda page. Changed official monthly HTML is the primary record and
is converted into source-language facts before the morning run. A poster with
a new URL is processed as a supplement using two blind Gemini Vision reads;
the second receives no first-pass candidates. Only their agreeing facts are
stored in the same bounded municipal catalog. A discovered OCR error may be
repaired only by a narrow correction tied to that exact reviewed official
poster. When the page publishes the
next poster early, still-relevant
facts from the prior snapshot remain available for the current day and the
following seven days. The snapshot may also supply today's events during a
temporary source outage. Extraction preserves explicit event type, medium,
time range, and place. Title-only translations are stored in the bounded
policy-versioned cache defined by ADR 0029; source facts remain Spanish in the
catalogs. Poster and Agenda
Guardamar records are merged and deduplicated; routine opening hours and
municipal services such as the mobile ecopark are excluded from `📅 События`.
The heading is rendered as `📅 События дня:` to make its daily scope explicit.
When an official text agenda publishes event-specific visiting hours, those
hours take precedence over missing poster OCR times. General venue opening
hours are never substituted for an event schedule.
For the verified `Sand Memories` guided tour, show the official meeting point
as `место встречи — Castillo de Guardamar`; do not substitute the organizer's
contact address.
On the confirmed end date of a multi-day event, prefix its title with
`Последний день:`. Do not apply the marker to one-day events or records without
an explicit end date.
For exhibitions, keep the medium or category outside the title and place an
explicit work name in Russian typographic quotes, for example:
`Выставка живописи и скульптуры «Средиземноморье, язык воды»`.
Render every non-empty event location as one linked `📍` row using a fixed
Google Maps HTTPS search URL. Append `Guardamar del Segura` to the search
query when the source place does not already name the city. Keep the visible
label concise and independent from the query; in particular, render the
reviewed exhibition venue as `Casa de Cultura (Sala de exposiciones)`.
The explicit operator command `refresh-current` may rebuild today's digest
and edit the one live morning or beach-replacement message in place. It must
refuse missing, stale, or internally inconsistent publication state and must
not create a new group message.

Every public digest and electricity message ends with one compact linked
signature, `📣 обЪявления Гуардамар`. It is part of the message so forwarded
copies lead to the public group instead of only identifying the bot. Telegram
link previews are disabled globally to keep the footer to one phone-width row.

The official `@AlcaldeGuardamar` channel additionally supplies explicitly
dated `Fiestas de Barrio` entries through a narrow deterministic parser. It
does not turn the channel into a general news source. Preserve named
participating urbanizations and the complete published venue:
`Ubicación parque C/ Berlín` renders as `парк на улице Berlín`.

The traffic slice reads explicit restrictions from the official Policía Local
Guardamar page and its reviewed festival PDF. A document becomes independent
active measures, preserving location, dates, hours, affected users, exceptions,
alternative route and destinations only when stated. From 22 through 29 July,
the verified measure is:

`До 29 июля перекрыта улица Molivent. К поликлинике и автовокзалу — через La
Redonda; легковым авто также через San Francisco до 23:30.`

The PDF is accepted only while its SHA-256 matches the reviewed document.
Missing, changed, ambiguous, or out-of-window content omits the section.

An active multi-day traffic notice uses `До <end date>` after its first day.
On the first day it retains the full start–end range.

If the official traffic page changes to a previously unknown HTML notice,
the optional Gemini fallback may extract up to four independent measures with
exact Spanish evidence. Publication requires supported actions, current
explicit dates, unchanged street names, restriction language, and Russian
lines no longer than 180 characters. The application validates all measures
against the freshly fetched page and displays at most two. Any failure omits
the traffic section. Known notices never consume Gemini quota.

AEMET lists no observation station inside Guardamar, so the current observation
comes from nearby Rojales. Its location is documented but omitted from the
compact user-facing message. Warning status is reported as unavailable when the
warning product cannot be retrieved or interpreted; absence of data is never
presented as absence of warnings.

### Delivery and schedule

- One configured Telegram chat or channel
- Publish the full non-operational beach briefing at `07:30`
- Check SafeBeach at `10:10`, then every five minutes through `10:40`
- Before `10:40`, require active, non-ended, timestamped flags for all six
  known Guardamar zones
- Before that complete six-zone set is available, exit without checking or
  collecting other sources, but retain the most complete whole valid response
  in the small daily state; equal-size responses prefer the later observation
- At `10:40`, accept any non-empty valid set so one missing zone cannot
  suppress the whole update; prefer that current response and use the recent
  same-day candidate only if the final request has no valid data, without
  merging records from separate responses
- After completeness, or after the final failed check, inspect the Mayor
  channel once for a new explicit bathing-status transition since 07:30
- If neither source has an update, retain the 07:30 message and exit
- If either has an update, recollect all other sources once, send one full
  replacement with a normal notification, then delete the 07:30 message
- For every digest collection, use the AEMET adapter's bounded transient-only
  recovery policy; publication and preview do not add outer retries
- If all three AEMET attempts fail, preserve every unchanged line from the
  published 07:30 message and add only verified SafeBeach/Mayor blocks
- At most three bounded Telegram HTTP attempts within that run
- One small atomic JSON state with the date, rendered morning copy, morning
  time, message IDs, deletion result, and one temporary normalized SafeBeach
  candidate removed after successful replacement
- Concise process output for success, duplicate, skip, and failure

The replacement ID is stored before deleting the earlier message. If deletion
fails, the next invocation retries cleanup without sending another replacement.
The CLI `preview` command remains available for local inspection. An optional
`listen` process accepts only a fresh `/preview` command in a private chat from
a user ID listed in `TELEGRAM_ALLOWED_USER_IDS`. It replies privately with
freshly collected data. Group commands, unauthorized users, stale updates, and
other commands are ignored. Neither preview path changes publication state or
publishes to the configured group. If preview generation fails, the private
reply includes a stable source-and-stage code plus a concrete safe cause. A
successful private preview appends an operator-only diagnostics block for each
consulted optional source that failed or returned no active SafeBeach data.
Examples include `AEMET-DAY-HTTP-503`, `AEMET-WARN-INVALID-XML`,
`SB-NO-ACTIVE`, `POLICE-NETWORK`, and `MUNI-AGENDA-NO-POSTER`. Raw URLs,
credentials, response bodies, transport internals, and tracebacks are never
returned. Group publication never includes this diagnostics block.

### Boundaries

- Not a complete news feed
- Not a substitute for emergency services or official warning channels
- Not continuous real-time monitoring
- No unsupported predictions or invented summaries
- Missing low-value or optional-source sections may be omitted

## Feature boundary

The approved electricity table fills the former future-feature slot. Do not
add another product feature without a validated need and explicit decision.
The electricity workflow must remain independent of Morning Digest collection.
