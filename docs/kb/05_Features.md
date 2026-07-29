# Features

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
The user-facing message is fully Russian and contains no source footer.

### Canonical layout

This exact visual structure is the product contract:

```text
🌅 Доброе утро, Гуардамар!

{значок} Погода: 24° → 31°
🌧 Дождь: 80% • 12:00–18:00
🌊 Море: 29° • слабые → умеренные
💨 Ветер: СВ 5 → 7 м/с
🏖 Флаги на пляжах:
   🟡 Roqueta
   🟢 Centre / Babilònia, Vivers
🪼 Медузы: Roqueta

⚠️ Внимание
Жёлтое предупреждение о жаре до 20:00.

🚧 Движение ограничено
С 19:30 перекрыта Calle Mayor.

📅 События
• 07:00–13:30 — рынок, парковка La Redonda
• 21:00 — концерт в замке, Castillo
```

The order never changes:

1. Greeting
2. Weather
3. Rain probability and period, only at 75% or above
4. AEMET sea temperature and optional sea-state forecast
5. Current wind with optional inline forecast
6. Available flags for Centre / Babilònia, Roqueta, and Vivers, grouped by color
7. Jellyfish beaches, only when explicitly reported
8. Warning
9. Traffic or closure
10. Today's events

The greeting must be exactly `🌅 Доброе утро, Гуардамар!`. The word
`дайджест` must not appear in the user-facing message.

Compact condition labels end with `:` and use one following space. Do not
align columns with runs of spaces. The sea row keeps the user-facing label
`Море`.

Weather, sea, and wind are mandatory compact rows. Rain is one optional compact
row. It uses the highest AEMET probability for an eligible remaining period
and appears only at `75%` or above; otherwise it is omitted. SafeBeach
operational rows are considered only from 20 June through 14 September,
inclusive. The flag row is shown only
when SafeBeach has at least one active nearby record. It names each available
beach and never averages flags. Groups use the fixed safety order red, yellow,
then green. Within every beach-name list use the product order `Centre /
Babilònia`, `Roqueta`, `Vivers`, so the central zone is first whenever
represented. When at least one selected flag is current, unavailable selected
beaches are omitted rather than assigned a reassuring default. The sea
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

The weather icon is dynamic from the existing AEMET daily sky forecast:
`☀️` clear, `🌤` partly cloudy, `☁️` cloudy, `🌫️` fog, `🌧️` rain,
`🌨️` snow, and `⛈️` storm. When several periods differ, use the most
significant condition for the day. Unknown or missing conditions use `🌤`.
The icon adds no text, AI, or new source.

Warning, traffic, and event sections are optional. Omit an entire optional
section when it has no verified, useful items. Do not render empty headings.
The event section contains at most two official Agenda Guardamar events whose
structured start date is today.

Each event uses the compact order `{time or range} — {type and title}, {place}`.
When the official source has no time, omit only the time prefix and keep the
event. Preserve an explicit activity type or medium such as painting,
sculpture, concert, workshop, guided tour, or night route. Include the
official place when available. Never invent missing time, type, or place.

The message has no source footer, links, report-style title, explanatory prose,
or separate weather section. It must fit on one phone screen and be scannable
in under five seconds.

### Implemented vertical slice

The first MVP slice covers Guardamar weather and AEMET warnings:

- current temperature and wind from AEMET's nearby Rojales observation
  station;
- today's minimum and maximum temperature from AEMET's Guardamar municipal
  forecast;
- the highest eligible remaining precipitation probability and its period
  when it is at least 75%;
- active or upcoming-today CAP warnings for Guardamar's warning zone;
- deterministic formatting with no runtime AI.

The canonical visual layout and inline later-day wind comparison are
implemented. ADR 0013 adds the dynamic AEMET weather icon without changing the
row layout.

The beach-status slice adds:

- separate active SafeBeach flags for `Platja Centre / Babilònia`,
  `Platja La Roqueta`, and `Platja dels Vivers`;
- today's AEMET water temperature and sea-state forecast for
  `Centro / La Roqueta`;
- Centre water temperature and sea state as SafeBeach fallbacks;
- omission of individual unavailable flags and sea state without blocking
  weather delivery or inventing a normal status.

Neither AEMET nor fallback logic supplies or infers a beach flag.

The event slice adds today's official ticketed Agenda Guardamar events. It
reads the title, local time range, and place, sorts chronologically, removes
duplicates, and shows at most two items. Source failure or no event today
omits the complete section.

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

ADR 0012 implements an expansion using the Ayuntamiento monthly poster linked
from the official Turismo Guardamar agenda page. A poster with a new URL is
processed once with Gemini Vision and stored as a bounded structured monthly
event snapshot. The snapshot may supply today's events during a temporary
source outage. Extraction preserves explicit event type, medium, time range,
and place. Russian translations are not stored. Poster and Agenda
Guardamar records are merged and deduplicated; routine opening hours and
municipal services such as the mobile ecopark are excluded from `📅 События`.

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
- Accept one or more active, non-ended, timestamped selected beach flags
- Before completeness, exit without checking or collecting other sources
- After completeness, or after the final failed check, inspect the Mayor
  channel once for a new explicit bathing-status transition since 07:30
- If neither source has an update, retain the 07:30 message and exit
- If either has an update, recollect all other sources once, send one full
  replacement with a normal notification, then delete the 07:30 message
- For every digest collection, try AEMET once plus two retries two minutes
  apart; 07:30, replacement, CLI preview, and private preview share this rule
- If all three AEMET attempts fail, preserve every unchanged line from the
  published 07:30 message and add only verified SafeBeach/Mayor blocks
- At most three bounded Telegram HTTP attempts within that run
- One small atomic JSON state with the date, rendered morning copy, morning
  time, message IDs, and deletion result
- Concise process output for success, duplicate, skip, and failure

The replacement ID is stored before deleting the earlier message. If deletion
fails, the next invocation retries cleanup without sending another replacement.
The CLI `preview` command remains available for local inspection. An optional
`listen` process accepts only a fresh `/preview` command in a private chat from
a user ID listed in `TELEGRAM_ALLOWED_USER_IDS`. It replies privately with
freshly collected data. Group commands, unauthorized users, stale updates, and
other commands are ignored. Neither preview path changes publication state or
publishes to the configured group. If preview generation fails, the private
reply includes a short safe cause category; raw URLs, credentials, transport
details, and tracebacks are never returned.

### Boundaries

- Not a complete news feed
- Not a substitute for emergency services or official warning channels
- Not continuous real-time monitoring
- No unsupported predictions or invented summaries
- Missing low-value or optional-source sections may be omitted

## Future Feature

### Purpose

Reserve room for one later feature supported by a validated user need.

### User value

Unknown until the feature is defined.

### Inputs and output

Not defined.

### Boundaries

- Must not be implemented speculatively
- Must remain compatible with the documented runtime constraints
- Must not weaken the Morning Digest
- Requires an explicit scope and decision record before implementation
