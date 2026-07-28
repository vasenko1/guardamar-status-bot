# Features

## Morning Digest

### Purpose

Provide one concise daily overview of conditions and notable city information.

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

{значок} Погода   24° → 31°
🌊 Centre    28° • волнение умеренное
🏖 Флаги    🟡 Roqueta • 🟢 Vivers, Centre
🪼 Медузы    Roqueta
💨 Ветер    СВ 5 → 7 м/с

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
3. Sea temperature and optional Centre sea state
4. Available flags for Centre, Roqueta, and Vivers, grouped by color
5. Jellyfish beaches, only when explicitly reported
6. Current wind with optional inline forecast
7. Warning
8. Traffic or closure
9. Today's events

The greeting must be exactly `🌅 Доброе утро, Гуардамар!`. The word
`дайджест` must not appear in the user-facing message.

Weather, sea, and wind are mandatory compact rows. The flag row is shown only
when SafeBeach has at least one active nearby record. It names each available
beach and never averages flags. Groups use the fixed safety order red, yellow,
then green; beach names within each group use north-to-south order `Vivers`,
`Centre`, `Roqueta`. Missing beaches are omitted rather than assigned a
reassuring default. The sea temperature and sea-state text are the active
Centre values; sea state is omitted when unavailable. The jellyfish row is
shown only for beaches where SafeBeach explicitly reports presence. A negative,
missing, or unknown jellyfish field produces no row. The wind
forecast is appended to the wind row as `→ <speed>` and is omitted when
unavailable. It never creates another row.

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
- active or upcoming-today CAP warnings for Guardamar's warning zone;
- deterministic formatting with no runtime AI.

The canonical visual layout and inline later-day wind comparison are
implemented. ADR 0013 adds the dynamic AEMET weather icon without changing the
row layout.

The beach-status slice adds:

- separate active SafeBeach flags for `Platja Centre / Babilònia`,
  `Platja La Roqueta`, and `Platja dels Vivers`;
- sea temperature and sea state from the Centre record when present;
- today's AEMET water-temperature forecast for `Centro / La Roqueta` as a
  fallback when SafeBeach has no temperature;
- omission of individual unavailable flags and sea state without blocking
  weather delivery or inventing a normal status.

The fallback never supplies or infers a beach flag or sea state.

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

The traffic slice reads the explicit festival access restriction on the
official Policía Local Guardamar traffic page. It shows one compact
`🚧 Движение ограничено` line only from 15 through 29 July, while the page explicitly
states that the remaining approaches are closed and access to Centro de Salud
and the bus terminal is via C/ San Francisco. Missing, changed, ambiguous, or
out-of-window text omits the complete section. The linked historical PDF is
not used as current data.

An active multi-day traffic notice uses `До <end date>` after its first day.
On the first day it retains the full start–end range.

If the official traffic page changes to a previously unknown notice format,
the optional Gemini fallback may extract one exact Spanish evidence quotation
and propose one Russian line. Publication requires a current explicit date
range, at least one unchanged street or access-route name, traffic-restriction
language in the evidence, and a message no longer than 180 characters. All
facts are checked against the freshly fetched page. Missing key, quota,
request failure, invalid JSON, invented facts, or ambiguity omits the traffic
section. Known notices never consume Gemini quota.

AEMET lists no observation station inside Guardamar, so the current observation
comes from nearby Rojales. Its location is documented but omitted from the
compact user-facing message. Warning status is reported as unavailable when the
warning product cannot be retrieved or interpreted; absence of data is never
presented as absence of warnings.

### Delivery and schedule

- One configured Telegram chat or channel
- One external invocation at `10:00` in `Europe/Madrid`
- One direct source-collection pass, followed by delivery and process exit
- Use an active SafeBeach flag when it is available at collection time; an
  unavailable flag does not block publication
- Skip when the current local date already has a confirmed publication
- At most three bounded Telegram HTTP attempts within that run
- One atomic state value: `last_successful_date`
- Concise process output for success, duplicate, skip, and failure

The success date is written only after Telegram confirms delivery. Collection
or delivery failure writes no state, so a later external invocation may retry.
The CLI `preview` command remains available for local inspection. An optional
`listen` process accepts only a fresh `/preview` command in a private chat from
a user ID listed in `TELEGRAM_ALLOWED_USER_IDS`. It replies privately with
freshly collected data. Group commands, unauthorized users, stale updates, and
other commands are ignored. Neither preview path changes publication state or
publishes to the configured group.

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
