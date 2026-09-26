# Features

## Local earthquake notices

Once per hour the bot reads the official IGN GeoRSS feed and looks only within
20 km of Guardamar. It publishes a standalone group message when all of the
following are true: the event is new, no more than six hours old, magnitude
1.8 or greater, and inside the radius. The first successful run records the
current feed without publishing old events. Each later event is delivered at
most once; a failed Telegram send is retried on the next hourly run rather
than marked successful.

The compact message contract is:

```text
📈 Землетрясение рядом

🕒 14:32 - зарегистрировано землетрясение магнитудой 2,8

📍 Эпицентр: примерно в 4 км к юго-западу от Гуардамара

📣 обЪявления Гуардамар
```

The epicenter row links the exact decimal coordinates in Google Maps. The
distance is rounded only for display; eligibility uses the unrounded
great-circle distance. Direction uses one of eight compass sectors. No IGN
link, generic advice, preliminary-data disclaimer, map screenshot, or raw
source location is added. The normal footer is separated by one blank line.

Several qualifying events observed within six hours use one Telegram message
headed `📈 Несколько толчков рядом`. New events and revised IGN parameters edit
that message in place. It shows at most the five latest events with individual
map links, a count of hidden earlier events, and the strongest magnitude.
`Афтершок` is never inferred. After six hours without another qualifying event,
the next event starts a new message.

The state retains the latest normalized parameters and delivery status rather
than ID alone. A fresh event initially below 1.8 remains eligible if IGN revises
it across the threshold. A corrupt state is replaced only after one bounded
`.invalid` copy is saved, then the current feed is seeded silently. A failed
explicit send remains eligible; an ambiguous result is marked uncertain to
avoid an automatic duplicate because Telegram provides no idempotency key for
`sendMessage`.

## SUMA tax-period reminders

Once per existing 07:30 daily lifecycle, the same short-lived Python process
performs a best-effort SUMA final step after the Morning Digest attempt. It
cross-checks the current Guardamar municipal tax rows against SUMA's general
voluntary-payment period and publishes at most
one standalone message only on these exact local dates:

- the payment-period opening date;
- seven days before the published direct-debit setup deadline;
- the published direct-debit charge date;
- one day before the voluntary payment period ends.

The first successful run is a silent baseline: trigger dates at or before that
day are recorded without publication, while future dates remain eligible. A
missed date is never replayed later. Concrete campaign dates and bootstrap
examples belong in the dated research/ADR record, not in this stable feature
contract.

The message uses only source-backed dates and the tax names found on the
Guardamar SUMA page. The state is a tiny atomic list of semantic date keys. A
future official date revision naturally creates a new future key; no history,
queue or generic notification framework is retained. Definite Telegram failure
rolls the key back for a same-day manual retry, while an ambiguous send keeps it
to avoid an automatic duplicate. Source failure or source disagreement is
silent.

## Blood-donation alert and same-day event

The existing morning lifecycle performs the official Alicante
blood-donation read only when no local snapshot exists or seven local calendar
days have elapsed since the last successful read. It retains only normalized
current or future Guardamar sessions.

A separate short-lived command runs at 16:45 Europe/Madrid. It first consults
that local discovery snapshot. With no known session tomorrow it exits without
network access. With a known session tomorrow it performs exactly one fresh
bounded control read and publishes only if the session is still present and not
`SUSPENDIDA`; current hours and venue come from that fresh response.

The successful 16:45 control read replaces the snapshot and resets the
seven-day discovery timer. The next Morning Digest may render today's donation
from a snapshot observed today, or from the previous local date only when that
observation was at/after 16:45. Therefore a previous-morning weekly discovery
snapshot cannot become a same-day public event by itself.

The state contains the current normalized sessions plus one `alerted_for`
date. A definite Telegram failure clears that date for retry; an ambiguous send
keeps it to prevent an automatic duplicate. No browser, PDF, AI, database,
daemon, queue or generic notification framework is involved.

## Weekend events digest

One optional Friday-evening message, «Афиша выходных», previews Saturday and
Sunday. It is built only from the existing normalized event catalogs and the
recurring market rules; no new source is introduced and the Mayor channel is
not checked. The primary Friday run first performs one best-effort refresh of
the same event catalogs so late announcements can enter before publication.
Each day renders under its own dated heading
(`📅 Суббота, 15 августа:`) using the same bounded event renderer, ticket
rows, and Google-Maps venue links as the Morning Digest. A day without
verified events omits its heading; a weekend with no verified events sends
no message. Missing weekend title translations are prepared inline through
the same bounded cache; a provider outage degrades titles to normalized
Spanish. Publication runs Friday at `19:15` after that best-effort refresh, with
one delivery-only retry at `20:15`, guarded by one atomic success marker in
`state/weekend.json` keyed to the target Saturday. A successful first send
makes the retry a no-op. Only the publishing command fills missing weekend
translations; `weekend-preview` reads the existing cache and prints
the message without
Telegram or state changes. See ADR 0035.

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
then the earlier start, using the same displayed precision. Rounded zero is
always rendered as `0,000`, without a negative sign. If no hours are green,
the recommendation is omitted.
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
- Official warnings
- Meteosalud heat- and cold-health risk
- One short static preventive tip beneath a medium or high Meteosalud risk;
  low risk remains one line and level zero remains silent
- Forecast air quality and pollen from the normalized CAMS subset
- Important municipal updates
- Events relevant today

### Output

One compact Telegram message containing only current, reliable, useful items.
The user-facing message is fully Russian. AEMET attribution appears in the
weather heading. When a CAMS-derived air-quality or pollen line is visible, a
compact modified-data attribution and responsibility disclaimer follows it.

### Canonical layout

This exact visual structure is the product contract:

```text
🌅 Доброе утро, Гуардамар!

🌤 **Погода от AEMET:**
**Воздух:** 24° → 31° • ясно → облачно
**Дождь:** 80% • 12:00–18:00
**Ветер:** СВ 5 → 7 м/с
**Море:** 29° • слабые → умеренные
**УФ:** 9 (очень высокий)
**Солнце:** 07:10 → 21:00

⚠️ **Предупреждения AEMET:**
Зона: южное побережье Аликанте
🟠 **Опасные прибрежные явления**
   Завтра · 08:00–18:00 · вероятность 40–70%
🟡 **Высокая температура**
   Сегодня и завтра · 13:00–20:59 · вероятность 40–70%

🚧 **Движение:**
• С 19:30 перекрыта Calle Mayor.
• Автобусы следуют по временному маршруту.

💊 **Дежурная аптека:**
**Planelles Mas, Asuncion, Guardamar del Segura**
Круглосуточное дежурство с 09:00 16 августа до 09:00 17 августа
📍 Av. Cervantes, 29

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
6. UV index, only at 6 or above, and the computed sunrise/sunset span
7. Warning
8. Standalone health, air-quality, and pollen lines not nested in today's
   matching warning; pollen is always standalone
9. On-call pharmacies for Guardamar's complete official service zone from the
   weekly-synced rota catalog
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
and appears only at `75%` or above; otherwise it is omitted. SafeBeach operational flags are deliberately excluded from the immutable
Morning Digest. The AEMET Centro / La Roqueta product remains the morning
source for sea temperature and sea state; no missing SafeBeach flag is inferred
or substituted into the morning message.

### Risk-message contract

The same normalized official risk state has two presentation modes.

The Morning Digest does not render Previfoc forest-fire or dry-thunderstorm
state because those values can be readjusted during the day and the morning
message is not kept synchronized with them. Their user-facing presentation is
standalone transition notification only.

Previfoc is treated as a daily prevention product rather than a midnight
breaking-news feed. Hourly collection continues unchanged, but a Previfoc delta
observed before 07:00 Europe/Madrid is stored silently and is not acknowledged
as published. The first hourly run at or after 07:00 may publish only the value
that is still current then. If an overnight change reverses before morning,
there is no resident-facing notice. This quiet-hours rule applies only to
Previfoc; CCE/hydrological transitions remain immediately eligible.

A fresh active CCE hydrological state may still add one compact morning line.
Do not add routine all-clear lines merely to show that a source was checked.

A standalone transition message may be longer and explain what changed, what
the official state means for people, any directly supported practical action,
and the authority source. Escalation, a material new high-risk state, and an
important downgrade/clearance may each justify one standalone transition.
When a prior dangerous standalone state was public, its official downgrade or
end must not leave that stale warning uncorrected.

### Daily beach root

From 1 June through 30 September, SafeBeach has one separate daily root titled
`🏖 Пляжи Гуардамара сегодня`. The Morning Digest never requests or renders
SafeBeach. During the 10:10–10:40 update cycle, the first valid current
SafeBeach response containing at least one known beach flag creates the root
immediately; every later valid response edits that same root. Each edit uses
one whole current source response and never merges records across requests.

Flag blocks are phone-first: the flag colour/type is on its own line, verified
beach names follow on rows of at most three names, and the bathing meaning is a
separate final line. Mixed states use the fixed safety order red, yellow, green.
When all six tracked beaches have the same verified colour, the names collapse
to `На всех пляжах ... флаги`. Missing beaches are omitted and never inferred.
After 10:40 the SafeBeach snapshot in an existing root is frozen; confirmed
later flag or jellyfish changes are separate replies to that root. If no root
was available by 10:40, the first later confirmed status may create one as a
recovery path. A newer explicit Mayor bathing restriction remains an
independent safety signal and may refresh the root. The Morning Digest is never
replaced.

The sky-row icon is dynamic from the existing AEMET daily sky forecast:
`☀️` clear, `🌤` partly cloudy, `☁️` cloudy, `🌫️` fog, `🌧️` rain,
`🌨️` snow, and `⛈️` storm. Keep at most the first and last distinct remaining
conditions, with one arrow. A transition uses `🌤`; a single state uses its
matching icon. Unknown or missing conditions use `🌤`.
The icon adds no text, AI, or new source.

### Weekly bathing-zone control

During the official bathing season, from 1 June through 15 September, a
separate short-lived 19:35 one-shot checks the published Guardamar index for a
new Generalitat Valenciana bathing-zone report. It never reruns the full guide
sync.

The public message is intentionally different from the operational SafeBeach
root. SafeBeach answers today's flag/jellyfish/bathing-status question;
bathing-zone control reports the Generalitat's laboratory and inspection
results from actual samples.

Phone-first copy uses:

- `🧪 Контроль зон купания`;
- `📅 Пробы:` followed by the actual unique sample dates extracted from the
  report rows;
- a primary `Лабораторный анализ воды` block;
- a `👁 Визуальный контроль` block containing only non-excellent water/sand
  exceptions;
- no more than two beach names per continuation line;
- `🏛 Данные: Servicio de Calidad de Aguas · Generalitat Valenciana`;
- the standard forwarding-safe group footer;
- no resident-facing report URL.

When every beach has the same laboratory rating, collapse the laboratory block
to one line such as `✅ Отлично — все 7 пляжей`. Never create a synthetic
overall beach score from water, water appearance and sand appearance. The first
parsed report is sent only if still fresh (no later than five days after its
covered period ends); otherwise it seeds a silent baseline.

Warning and event sections are optional. Omit an entire optional section when
it has no verified, useful items. Do not render empty headings. Every displayed
section heading and every event time is bold through Telegram HTML. Sections
are separated by exactly one empty line. Warning hazards use their severity dot
and a bold Russian name.
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
When a verified explicit duration exists, show the start time and a compact
`N мин` fact instead of treating a calendar end slot as an exact finish time.
Every event, including a child of a named programme, may show one optional
facts line, ordered as short details, duration, then audience. A short teaser,
supplementary schedule, visible venue, distinct meeting point, participation
note and access row appear only when verified. The visible venue may link to a
separate safe map query. An equivalent meeting point is not repeated. Exact
access wording wins over the generic limited-capacity fallback. Source facts
merge additively; a generic title may gain a specific identity after duplicate
matching, but a canonical title is not replaced by a promotional subtitle.
Programme grouping is independent of the programme's name.
When the official Turismo `CINE` row verifies a recurring Monday library
screening with a concrete film title, use the stable heading
`Кино по понедельникам: «<название фильма>»`. Keep the film title inside
Russian quotation marks; do not append a promotional subtitle from another
event record. If a prepared translation does not identify the Monday series
and film, fall back to the official film title. The same heading applies when
the merged event keeps a separate official Todo Cultura title while retaining
the verified Turismo cinema marker and its explicit film name.
When the official source has no time, omit only the time prefix and keep the
event. Preserve an explicit activity type or medium such as painting,
sculpture, concert, workshop, guided tour, or night route. Include the
official place when available. Never invent missing time, type, or place.
For text sources, keep the title self-contained: a named act must not displace
an explicitly stated format such as a concert, theatre performance, tribute or
benefit event. A short stated audience or cause may remain in the title when it
is needed to explain the event and has exact source evidence.
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

- a later AEMET change is one self-contained update: cancelled warnings are
  grouped first, and the complete remaining set follows under
  `Сейчас действует`;
- when a valid response contains no other active warning, the update says so
  explicitly; unknown labels remain fail-closed and cannot produce that
  conclusion;

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
probability, description, and local start day may share one block. Different
facts remain separate. The fixed zone is named once. Today's hazards precede
tomorrow's; within each day they are ordered red, orange, yellow, and each name
is bold.
Hazards have no empty lines between them; their time and recognized detail
lines use one consistent indentation so the section reads as one list.
Spanish/English CAP duplicates and green `Minor` records are omitted. Unknown
description wording is never machine-translated or guessed: the warning,
validity period, and validated probability still remain visible.

The beach-status slice is separate from the Morning Digest and adds:

- every valid active flag among the six known Guardamar SafeBeach zones;
- explicit jellyfish state only when tied to a current verified beach record;
- omission of unavailable beaches without inferring a normal flag or carrying
  a missing record forward as current.

The Morning Digest continues to use AEMET for its sea forecast independently.
Neither AEMET nor any fallback logic supplies or infers a beach flag.

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
Routine Centro Social Juvenil opening and generic activity rows remain
excluded; a separately named activity with a verified date, time and place is
eligible. A
deterministic fallback also preserves explicit exhibition titles, date ranges
and venues from the official Turismo text when structured extraction omits or
rejects that block.
The heading is rendered as `📅 События дня:` to make its daily scope explicit.
When an official text agenda publishes event-specific visiting hours, those
hours take precedence over missing poster OCR times. General venue opening
hours are never substituted for an event schedule.
The rolling Todo Cultura supplement treats distinct event pages for the same
date independently. Its bounded three-page selection first considers the
nearest unprocessed dates and then prioritizes metadata that advertises
actionable participation facts such as an audience or age, registration,
limited capacity, admission, a workshop, course, route, or guided visit. One
generic daily-programme page must not mark a separate event page for that date
as complete. Remaining candidates stay pending for a later scheduled refresh;
the request, text-size, and seven-day limits do not change. Explicit
registration contacts are accepted only when the event-local row contains a
phone, WhatsApp number, or email, and are matched conservatively to one
occurrence by explicit date and time before rendering. A missing time is
withheld when multiple same-title sessions are possible. Explicit beginner
suitability, skill improvement, and group practice become one short
deterministic participation note. Oversized dated text is processed in at most
three 12,000-character inputs per refresh with bounded resumable hash progress;
an overflowing page no longer discards accepted pages or blocks the queue.
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
The explicit operator command `refresh-current` may rebuild today's Morning
Digest and edit that one live morning message in place. It never collects
SafeBeach, must refuse missing, stale, or internally inconsistent publication
state, and must not create a new group message.

Every public digest and electricity message ends with one compact linked
signature, `📣 обЪявления Гуардамар`. It is part of the message so forwarded
copies lead to the public group instead of only identifying the bot. Telegram
link previews are disabled globally to keep the footer to one phone-width row.

The official `@AlcaldeGuardamar` channel additionally supplies explicitly
dated `Fiestas de Barrio` entries and narrowly validated late municipal event
announcements through deterministic parsers. A general announcement requires
an invitation, a quoted title, the current explicit date, a valid time and an
explicit place; retrospective reports and incomplete posts are omitted. This
does not turn the channel into a general news source. Preserve named
participating urbanizations and the complete published venue:
`Ubicación parque C/ Berlín` renders as `парк на улице Berlín`.

The former Policía Local traffic slice is retired. Its reviewed festival page
proved useful for one historical event but did not behave as a dependable live
traffic source across routine operation. The Morning Digest therefore performs
no Policía Local request and has no generic traffic/closure section or Gemini
traffic fallback. Historical research and superseded ADRs remain only as
evidence for that decision.

AEMET lists no observation station inside Guardamar, so the current observation
comes from nearby Rojales. Its location is documented but omitted from the
compact user-facing message. Warning status is reported as unavailable when the
warning product cannot be retrieved or interpreted; absence of data is never
presented as absence of warnings.

### Delivery and schedule

- Publish the immutable Morning Digest at `07:30`; it never collects
  SafeBeach.
- From 1 June through 30 September, check SafeBeach at `10:10` and every
  five minutes through `10:40`.
- Any valid current response with at least one known Guardamar flag is enough
  to create the separate beach root immediately.
- Every later valid response through `10:40` edits that same root. Do not
  merge records from separate responses; each edit represents one whole
  current source response.
- From 1 October through 31 May, make no scheduled SafeBeach requests.
- After `10:40`, do not silently rewrite the SafeBeach snapshot in an
  existing root. The bounded operational monitor confirms later flag/jellyfish
  changes and publishes them as replies to the root.
- If no root was created in the initial window, a first later confirmed beach
  status may create it as a recovery path.
- Newer explicit Mayor bathing restrictions remain an independent safety
  signal and may refresh the beach root.
- AEMET, CAMS and Meteosalud operational updates remain independent of the
  beach root and follow their existing deterministic delivery rules.
- One small atomic daily state stores only the message anchors and compact
  semantic baselines needed by these one-shot processes.
- Concise process output covers success, duplicate, skip and failure.

The CLI `preview` command remains available for local inspection. An optional
`listen` process accepts only a fresh `/preview` command in a private chat
from a user ID listed in `TELEGRAM_ALLOWED_USER_IDS`. Morning preview uses the
same SafeBeach-free Morning Digest path as production. Group commands,
unauthorized users, stale updates, and other commands are ignored. Neither
preview path changes publication state or publishes to the configured group.
If preview generation fails, the private reply includes a stable
source-and-stage code plus a concrete safe cause. Raw URLs, credentials,
response bodies, transport internals, and tracebacks are never returned.
Group publication never includes this diagnostics block.
Cached Cultura enrichment preserves a safe technical failure marker so a
private preview distinguishes an unavailable or malformed timeline from a
successful check with no matching event. Direct Meteosalud, CAMS, library,
AM Guardamar and pharmacy omissions use the same private diagnostics path;
successful empty optional results remain quiet where emptiness is normal.

### Boundaries

- Not a complete news feed
- Not a substitute for emergency services or official warning channels
- Not continuous real-time monitoring
- No unsupported predictions or invented summaries
- Missing low-value or optional-source sections may be omitted

## Supermarket product award feed

The bot may publish occasional rich editorial notes about verified
award-winning products that are sold by supported Spanish supermarkets. The
product may be a private label, a proven retailer-exclusive item or an ordinary
brand with an exact current retail listing. Public wording must distinguish
those relationships.

This remains one shared stream across OCU, cheese, wine, olive oil, jamón,
consumer sensory awards and future award families.

The runtime contract is deliberately small:

- source-specific award adapters discover and deterministically parse only their
  own official/authoritative result surfaces;
- each award adapter defines a source-native stable `event_key`;
- award evidence and retailer evidence are separate under ADR 0084;
- an exact retailer join requires EAN/GTIN, exact retailer SKU, or a
  source-specific unambiguous commercial identity; manufacturer/brand-only,
  fuzzy, cross-country and marketplace matches fail closed;
- the shared engine owns per-source silent baseline, deduplication, one queue,
  deterministic rendering, and Telegram delivery;
- discovery runs at 13:50 Europe/Madrid;
- publication runs at 14:20 and sends at most one queued award per local day;
- the first successful observation of a newly registered award source silently
  marks its existing items as seen, so new award families never backfill their
  historical archive.

The active researched retailer set is Mercadona, Lidl España, ALDI España,
Consum, Carrefour España supermarket, Masymas / Juan Fornés Fornés and
DIA España. Alcampo / Auchan was technically researched but is intentionally
excluded because it has low practical local utility for the Guardamar audience.
Retailer evidence adapters do not get their own schedules or continuous
catalogue polling.

OCU is the first active award adapter. `Mejor del Análisis` means the best
result in that specific OCU comparison. `Compra Maestra` is a value/balance
distinction and is never described as the highest absolute quality. OCU
publication requires an overall/global score of at least **85/100**; a high
health, tasting or other partial subscore cannot satisfy that gate.

Articles are deterministic but may be substantially richer than the initial
POC. A source adapter may retain verified context such as comparison/entry
count, test or judging method, category/class, score, tasting result,
nutrition/quality classification, product description, composition, producer,
production country, vintage, DO, grape, maturation or other source-native
identity facts. If a producer is named publicly, country is mandatory; city or
region is optional additional context.

The headline contains the product, supermarket and award/result, not the numeric
score. Repeated methodology is rendered inside Telegram's expandable HTML
blockquote so the changing product facts remain visible without printing the
same judging explanation in full every day.

A queued item may wait several days. When exact retailer identity is known, the
publication step may make one bounded exact-product refresh immediately before
rendering. It returns all verified current package variants of that same awarded
commercial product. Each shown row keeps package size, price and unit price
when available. The bot never chooses one package on behalf of the reader, and
never transfers the award to a different flavour/recipe/SKU.

The feed sends at most one item per day rather than exactly one. If no
source-specific exceptional candidate exists, that day stays quiet.

Retailer product photos are disabled by default. Current legal checks found
reuse restrictions on several target retailer sites. A Telegram image is
enabled only for a source with an exact matched SKU, bounded allowlisted media
and a documented licence/permission/media policy that permits the intended
reuse. Missing or unclear rights always produce text-only output.

Award publication must work with Gemini/OpenRouter absent. No LLM may discover
awards, match products to retailers, invent editorial facts or repair an
ambiguous SKU join.

The shared queue preserves at-most-once delivery semantics. An ambiguous
Telegram send remains `uncertain` and is not automatically resent; a
deterministic rejection can safely return the event to the queue for a later
day.

New award bodies and retailer evidence sources must follow ADRs 0083 and 0084
plus the dated implementation checklist in
`research/2026-09-25-supermarket-product-awards.md`. Do not add a new cron,
queue, database, worker, browser, notification framework, universal LLM parser
or source-independent fuzzy matcher.

## Feature boundary

The approved electricity table fills the former future-feature slot. Do not
add another product feature without a validated need and explicit decision.
The electricity workflow must remain independent of Morning Digest collection.

## Linked pinned city guide

The approved camera and direct-transport reference is independent of the
Morning Digest. It is published only by an explicit operator command. Detailed
messages are created or edited before the transport navigator and compact root;
the root is pinned only after every required Telegram link is available.

One small atomic state stores the destination, bot-authored message graph and
bounded source/media metadata for the two urban lines. Repeated commands edit
those messages. If Telegram confirms one is missing, the workflow recreates
only that message and rebuilds dependent links. Other failures stop
publication. One external daily refresh and the Termux Poppler utilities are
accepted by ADR 0042; no browser or resident collector is added.

The same 05:00 command updates the airport leaf from the official Bus Sigüenza
result for the current date. It shows both directions, exact operator map
points and the standard fare only while a stable official tariff passes strict
validation. One normalized snapshot preserves explicit dating and deleted-
message recovery during source outages. The adapter also repairs only the
operator's documented missing-intermediate TLS fault through a strictly
allowlisted, verified Let's Encrypt AIA fetch; it never disables TLS. See ADR
0043.

The private `/pinned_preview` command and the one-shot CLI preview send the
exact text sequence silently to the single allowlisted operator. They do not
touch the group, pin messages, or write publication state.

The two municipal urban lines use PNG photos rendered from the exact official
one-page PDFs under ADR 0042. A changed document is downloaded twice
identically before rendering. Other routes remain text-only unless a suitable
current operator image is available; dynamic-search screenshots and generated
timetables remain excluded.
The 07:30 Morning Digest is not replaced later in the day. Material
operational changes are short replies to it; beach status is a separate
seasonal root with confirmed changes threaded beneath that root.
