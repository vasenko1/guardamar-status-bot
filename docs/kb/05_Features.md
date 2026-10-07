# Features

## Resident-impact news

Three daily one-shot checks use Euro Weekly News `News from Spain` only to
discover potentially useful Spain-wide practical changes. The first successful
RSS read is a silent baseline. Later runs classify at most eight unseen RSS
items in one bounded AI request. Unseen RSS entries already older than 48
hours are marked stale before AI, so recovery after device downtime does not
spend model quota on obsolete news. Relevant items form a tiny 48-hour queue:
high-priority items precede normal items, otherwise older items go first. A run
may inspect at most three candidates to bypass missing/duplicate/temporarily
unreachable sources, but it still composes and publishes at most one post.

A public post is allowed only when the EWN article itself contains a direct
link to an approved first-party authority/operator source. The bot does not
search for a missing source. It fetches that first-party HTML, discards the raw
page after the run, and asks the bounded AI composer for a short natural Russian
editorial note grounded in that first-party text.

The note is intentionally not a literal translation or a field-by-field
questionnaire. It uses one concise headline, 2-4 short narrative paragraphs,
and moderate thematic emoji. It should naturally explain the practical change,
timing, affected people and important caveats while preserving whether a
measure is only proposed/pending, approved, effective, an announced strike, or
an active disruption. Code appends one visible first-party source link; EWN is
not shown as the factual source.

Ordinary crime, celebrity, sport, entertainment, human-interest, routine
political statements without a practical consequence, and remote local stories
without wider relevance are excluded. Current weather/storm/flood/wildfire/
earthquake/beach/local-emergency and road-closure status are also excluded
because existing official-source features already cover those domains.
Political/policy material must remain neutral and factual.


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

One independent short-lived SUMA process runs at 08:05 Europe/Madrid. It
cross-checks the current Guardamar municipal tax rows against SUMA's general
voluntary-payment period and publishes at most one standalone message only on
these exact local dates:

- the payment-period opening date;
- seven days before the published direct-debit setup deadline;
- the published direct-debit charge date;
- one day before the voluntary payment period ends.

The first successful run is a silent baseline: trigger dates at or before that
day are recorded without publication, while future dates remain eligible. A
missed date is never replayed later. Concrete campaign dates and bootstrap
examples belong in the dated research/ADR record, not in this stable feature
contract.

Every public SUMA message uses plain resident-facing Russian rather than the
literal administrative term "voluntary period". It lists every accepted tax or
fee with a reviewed explanation of what it applies to, gives the exact ordinary
payment deadline and relevant domiciliación dates, and states the possible
late-payment additions. A tax label without a reviewed resident explanation
fails closed instead of producing a vague reminder.

The state is a tiny atomic list of semantic date keys. A future official date
revision naturally creates a new future key; no history, queue or generic
notification framework is retained. Definite Telegram failure rolls the key
back for a same-day manual retry, while an ambiguous send keeps it to avoid an
automatic duplicate. Source failure or source disagreement is silent.

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

## Sports event presentation

ADR 0100 defines dedicated sports presentation on the shared Event pipeline.
Sports Slice E activates the first resident-facing publication layer from the
already accepted local sources; later league-source and Event Access expansion
remain staged.

Sporting events remain ordinary normalized events with one optional canonical
sport code. The same accepted event facts feed:

- the existing next-day/weekend planning message, under a dedicated sports
  subsection;
- one standalone current-day sports message;
- the existing event-access lifecycle when advance registration, reservation or
  ticket action exists.

The current-day message is intentionally separate from the previous planning
mention: it answers what can still be attended today and may surface an
explicit source-backed cancellation. It runs at 08:25 Europe/Madrid with one
09:25 recovery, reads only fresh accepted same-day local snapshots, performs no
source HTTP or AI, and uses `state/sports_today.json` for crash-safe dated
delivery. No qualifying sport creates no message and no delivery marker.
Morning omits sport in the same release to avoid a third repetition.

Published sports copy is written for a resident rather than exposing raw
federation rows. When the responsible source provides the facts, it names the
sport, participants, competition/division, group, round or explicit knockout /
qualifying / friendly stage, meaningful team category, schedule and venue.
Missing facts are omitted rather than inferred.

No separate evening sports-tomorrow message, sports database, keyword
classifier, generic competition framework, browser worker or per-sport cron is
approved.

### Sports implementation status

The first resident-facing slice is active in the implementation:

- `Event.sport` remains on its previously introduced positional slot and the
  new source-proven `occurrence_status` field is appended after it;
- FACV/Pesca preserve their explicit sport identity and merge semantics protect
  different known sports;
- Russian sport label/icon metadata is deterministic;
- fishing national dates/details are source-corrected before planning;
- Tomorrow/Weekend share one fresh local planning loader and render dedicated
  sports subsections without changing their publication schedules;
- Sports Today uses the same local loader, time-aware current-day eligibility,
  complete fail-closed rendering and crash-safe delivery;
- a fresh matching FPCV cancellation is retained explicitly, suppressed from
  proactive Tomorrow/Weekend planning and rendered as a correction by Sports
  Today;
- Morning excludes sports in the same release;
- complete planning rendering cannot silently drop a sport and removes optional
  teaser prose before failing closed.

No separate evening sports message, sports database, per-sport scheduler,
browser worker or generic status framework is introduced.

## One-off event registration notices

Official one-off events may publish a compact access lifecycle before their
event day when the responsible first-party source exposes an actionable
registration, reservation or ticket state/boundary. The enabled sources are
CONVEGA's guided GR-92 campaign and reviewed FPCV convocatoria details for
Guardamar fishing.

The source layer keeps one small normalized local catalogue that also projects
ordinary `Event` rows into Morning, Tomorrow and Weekend. Registration
lifecycle state remains separate from the global Event model and from recurring
course notifications.

A registration is announced on first discovery only when current source
evidence positively proves it is open. First-seen full, closed or unknown
records silently establish the baseline. Explicit full/closed/reopen
transitions, exact opening/closing boundaries, material deadline changes and
event-date corrections may notify under the bounded rules in ADR 0089.
Disappearance never means closure or cancellation.

The normal one-shot runs at 10:47 Europe/Madrid with one 11:47 recovery.
The one-hour spacing keeps the recovery inside CONVEGA's <=90-minute access
freshness when the primary refresh succeeds, while still providing a second
pre-noon chance before reviewed 12:00 deadlines. Same-day freshness is
mandatory for current access claims. Each enabled source
owns its own freshness check; one stale source is omitted rather than blocking
fresh independent sources. Records are processed deterministically one at a
time, so one invocation may send several independent event roots/replies
sequentially. One ambiguous delivery blocks every later send until operator
resolution.

The shared lifecycle uses event-centric state v3. Version 2 is migrated only by
the explicit operator command with a private non-overwriting backup. V3 adds
only material root context required to detect date/place/route/schedule
corrections and explicit occurrence cancellation/postponement; ordinary
presentation details remain outside state. Registration, reservation and ticket
copy is access-kind-correct. An exact event poster may be used only for a
self-contained root that fits the Telegram caption limit; deterministic remote
media rejection may fall back to the same text root, while ambiguous media
delivery never does.

The implementation uses bounded source-specific parsing only: no browser,
source-side AI, database, queue, daemon or generic notification framework.
FPCV is the second enabled source under ADR 0103. Its EventAccess identity is
the source-assigned convocatoria number (for example `43/26`), while the
existing Pesca CV refresh remains solely responsible for HTTP/PDF parsing.
Legacy FPCV details v1 is readable but not proactive-access actionable until a
normal refresh supplies the identity-bearing v2 observation. See ADRs
0089-0092 and 0103.

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
one delivery-only recovery at `20:15`.

Weekend delivery now uses the same small crash-safe dated-state shape as
Tomorrow: before a non-idempotent Telegram send it writes
`state/weekend_delivery.json` as `uncertain`; confirmed success stores the
Telegram message ID, while timeout/network/5xx ambiguity remains uncertain and
blocks the recovery send. Automatic retries are limited to explicit Telegram
rate-limit rejection. A deterministic rejection clears the reservation so the
later recovery may retry safely.

The existing `state/weekend.json` successful-target marker is still written
after confirmed Telegram delivery and checked first. It is retained as a
rollback-compatible marker for the previous runtime; the new Weekend process
also acquires its legacy lock so an old and new runtime cannot publish
concurrently across a deployment boundary. A previously confirmed
`weekend_delivery.json` state can repair a missing legacy marker without
sending another Telegram message.

Only the publishing command fills missing weekend translations;
`weekend-preview` reads the existing cache and prints the message without
Telegram or either publication-state mutation. See ADR 0035 and ADR 0080.

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

From 1 June through 15 October, SafeBeach has one separate daily root titled
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
- From 1 June through 15 October, check SafeBeach at `10:10` and every
  five minutes through `10:40`.
- Any valid current response with at least one known Guardamar flag is enough
  to create the separate beach root immediately.
- Every later valid response through `10:40` edits that same root. Do not
  merge records from separate responses; each edit represents one whole
  current source response.
- From 16 October through 31 May, make no scheduled SafeBeach requests.
- During 1–15 October, later SafeBeach monitoring uses the reduced four-window
  shoulder cadence. Independent AEMET CAP-only checks run hourly at `:51`
  from 07:51 through 23:51 year-round.
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

## Supermarket product awards

Every three local calendar days at most one independently recognised product may
be published. Publication requires reviewed award evidence, exact current
retailer identity and a fresh current price.

Retailer diversity is a preference, not a quota or veto. The first valid
category winner from the same supermarket as the previous post is retained as a
fallback while later categories are checked. A valid winner from another
retailer is preferred; when none exists, the same-retailer fallback publishes.
The bot never drops to a lower rank inside a category merely to change store.

ADR 0095 established the quality-first production pool; ADR 0104 adds
only one narrowly qualified WCCC/Mercadona category and moves one existing
winner to stronger local retail evidence:

- NALTROS Brut / OCU / ALDI;
- Realfooding Gazpacho / OCU / Carrefour;
- Oleoestepa DOP Estepa / OCU / Carrefour;
- AROM'ARTE Intenso / OCU / DIA;
- Anís Chinchón Dulce / MAPA / DIA;
- Ambar Especial / World Beer Awards / Consum;
- Mahou Sin Filtrar / World Beer Awards / Masymas;
- Queso añejo tostado mezcla Hacendado / WCCC / Mercadona.

Producto del Año and Sabor del Año remain discovery sources rather than
production category rankings. WCCC does not open a generic class-winner path:
the reviewed Mercadona candidate is admitted only by the narrower Class 114
winner + Championship Round/Top-20 contract. Lidl remains an active research
target, but no product is inserted merely to satisfy retailer diversity.

Public Product Awards posts are photo-first. The normal article includes an
exact reviewed photo of the selected product. The bot makes bounded best-effort
attempts through the selected candidate's small approved official image
hierarchy and uses Telegram remote media plus bounded upload recovery where
needed. A deterministic failure may advance to the next reviewed exact image.
A no-image Rich Message is allowed only as the final degraded fallback when
every reviewed image path is blocked or fails deterministically. Media failure
never discards a product whose award identity and current price are still valid.

The public copy is deterministic and must preserve the reviewed editorial facts
available for that candidate: retailer in the headline, exact current package,
verified country when proved by the source, producer/manufacturer, one
source-backed reason the product stood out, and the fresh current price. Numeric
scores remain in the body rather than becoming the default headline. Carrefour
price wording refers explicitly to the official website and does not claim
Guardamar-local shelf stock.

The expandable methodology quote has one separate job: explain how that
specific source/category tests products or selects a winner. It must not repeat
the product name, award/result, score/rank, retailer, price, sample count or
candidate highlight already present in the article body. OCU methodology is
category-specific because cava, gazpacho, AOVE and coffee capsules use different
test procedures. World Beer Awards may share one reviewed judging-process text
across beer styles; MAPA spirits uses its own reviewed selection procedure.
WCCC uses its reviewed technical-judging method: a 100-point starting score,
defect deductions and class medals, without repeating the candidate's Top-20
result. A new source/category without reviewed methodology fails closed instead
of using generic filler prose.

Consum's current JSON uses working numbered `media[]` assets while its base
`productData.imageURL` values may 404. ALDI NALTROS currently fails closed
because the exact product page reports an explicit product-page error rather
than current product data.

The 3 October source-policy re-review is complete: the four Producto del Año
entries are removed from the production registry because the award is
innovation-first. This is a source-semantics decision, not a negative judgment
about the products themselves.

## Calendar notices

The existing daily 18:00 celebration/holiday publisher also carries a
next-day Europe/Madrid clock-change notice when the local timezone data contains
a transition tomorrow. The 07:30 Morning Digest receives the same locally
computed fact for the transition day. The feature uses no remote source, AI,
new cron or new state; it reuses the existing crash-safe calendar-alert
delivery state. Exact wall-clock jumps come from installed timezone data rather
than an annually hardcoded date table.

Municipal programme precedence remains conservative. Todo Cultura is
supplemental. A reviewed source conflict may suppress a Todo row only through a
narrow evidence-bound correction; the 6 October 2026 Rosario correction
requires the exact Todo date/time/title plus the verified Ayuntamiento 19:00
Rosario and 20:00 Mass pair. Generic duplicate thresholds are unchanged.



## Exceptional supermarket closures

One independent 08:15 Europe/Madrid one-shot watches exactly three physical
Guardamar stores: Mercadona at Avinguda del Mediterrani 14, masymas at
Av. del Puerto 18-20, and DIA at C/ La Redonda 40.

Only a first-party retailer schedule may establish whether that physical store
is open or closed. The reviewed Guardamar holiday calendar is optional
presentation context; it never creates a closure and never overrides an open
retailer schedule. Routine weekly closing days and shortened-but-open days do
not create standalone notices.

A verified exceptional closure may be announced early in the current week,
again tomorrow, and again today, with per-store/date/phase identities even when
several facts are grouped into one resident-facing message. Monday-known
Tuesday closures collapse early+tomorrow into one Monday message; missed
earlier phases are never replayed. At most one supermarket message is delivered
per local day.

If a fresh first-party schedule explicitly proves open after this bot
previously confirmed a closure message for that date, one compact correction is
eligible. Source failure, omission or third-party evidence never counts as
reopening. Ambiguous Telegram delivery blocks automatic duplication but is not
treated as a confirmed publication for future corrections.

Public text is deterministic natural Russian: it names the affected stores,
states plainly that they are closed for the whole day, says today/tomorrow/the
weekday, names other reviewed stores that are open when useful, and may explain
a reviewed official Guardamar day off. Internal source codes and state labels
are never shown.

Seasonal Sunday transition notices are deferred. A single Sunday difference is
never promoted into a regime-change claim.
