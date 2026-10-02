# CONVEGA and one-off event registration lifecycle

## Question

How should the bot discover and publish registration lifecycle information for
one-off public-interest events such as CONVEGA guided routes, tournaments,
runs, hikes and excursions without turning the project into a generic
notification framework or adding material load to the Termux phone?

This investigation also asks whether CONVEGA can be integrated through cheap
deterministic HTTP/REST reads, how registration identity and delivery state
should work, and when the source/publication jobs should run so they do not
compete with the existing Android workload.

The design in this note is **research output**, not yet a durable ADR. Runtime
code has not been changed by this investigation.

## Repository context reviewed

Before recording this research, the repository instructions and current
architecture were reviewed at main commit
`527665b5657862d713d003ddfcb36e8f81bd9b5d`.

Relevant project rules and existing decisions:

- `AGENTS.md`
- `docs/kb/00_Project_Overview.md`
- `docs/kb/01_Product_Vision.md`
- `docs/kb/02_Project_Principles.md`
- `docs/kb/03_System_Architecture.md`
- `docs/kb/04_Runtime_Constraints.md`
- `docs/kb/06_Data_Sources.md`
- `adr/0035-weekend-events-digest.md`
- `adr/0072-unified-course-notifications.md`
- `adr/0080-next-day-planning-notices.md`
- `research/2026-09-17-sports-source-production-probe.md`
- `research/2026-09-26-virgen-rosario-event-gap.md`

The relevant inherited constraints are:

- weak Android / Termux is a product constraint;
- use official or first-party sources;
- one-shot processes only;
- no database, message broker, generic scheduler, daemon or resident worker;
- source failure must remain unknown rather than fabricating a state change;
- deterministic validation must guard factual publication;
- small atomic JSON state is preferred;
- public Telegram sends must protect against ambiguous delivery;
- registration/date notices should read local normalized state, not perform
  arbitrary source work during rendering;
- silence is preferable to a weak or misleading claim.

## Product problem

Some public-interest events become useful to residents **before** the event
day because participation requires registration.

Examples discussed during the design review include:

- CONVEGA GR-92 guided routes;
- a Guardamar table-tennis tournament with a limited number of participants;
- a half-marathon / 10K event with separate distances and a registration
  deadline;
- a tennis open with an exact registration deadline time;
- football tournaments, where a team or category may need to register;
- guided excursions with a limited number of places;
- events with separate sessions or independently registered variants.

The existing event pipeline answers primarily "what happens today/tomorrow/this
weekend". It is not sufficient when registration opens or closes one or more
weeks before the event.

Recurring municipal courses and sections are already covered by
`course_notifications.py`, but that module is deliberately coupled to guide
cards, recurring-course identity and course-specific rules. One-off event
registration must not turn it into a generic framework.

## Product policy established by the investigation

### In scope

One-off public or public-interest events for which an official/first-party
source exposes an actionable registration lifecycle.

The first intended source is CONVEGA. Future examples may include municipal
or club tournaments, runs, hikes and guided excursions.

### Out of scope

- recurring course / school / season enrollment already owned by the course
  lifecycle;
- private promotional events that are otherwise outside the event policy;
- generic availability polling;
- price-change alerts;
- capacity-count alerts;
- participant-count alerts;
- venue-change alerts;
- registration-link-change alerts;
- route/description/contact-change alerts;
- a general event cancellation framework;
- a generic cross-source registration merger;
- browser automation, Playwright, Selenium or a JavaScript runtime.

### Resident value

The useful lifecycle moments are intentionally narrow:

1. registration is currently active when first discovered;
2. a verified registration opening boundary is today or tomorrow;
3. a verified registration closing boundary is tomorrow, with a same-day
   fallback only if the advance notice was not delivered;
4. a previously announced registration becomes explicitly full/closed;
5. a previously announced full/closed registration is explicitly open again;
6. a previously announced registration deadline changes materially;
7. the event date itself changes after the bot previously announced the
   registration.

The event day remains owned by Morning / Tomorrow / Weekend. Registration must
not create a second event-day publication channel.

## CONVEGA authority and source surfaces

CONVEGA is a first-party public-interest organizer for the researched GR-92
guided routes.

The source investigation identified three useful WordPress surfaces:

1. Registration/detail landing page:
   `https://convega.com/rutasguiadas-senderodelmediterraneo/`
2. Senderismo category:
   `https://convega.com/category/senderismo/`
3. Announcement article:
   `https://convega.com/convega-organiza-dos-rutas-guiadas-por-el-gr-92-mejor-sendero-homologado-2025-de-la-comunitat-valenciana/`

The landing page is a **mutable campaign/registration surface**, not a complete
long-lived event catalogue. The announcement article can describe more future
routes than the current landing page is showing.

For the current campaign, the announcement article names two outings:

- 4 October 2026, GR-92 stage 21;
- 8 November 2026, GR-92 stage 22.

During the production probe on 2 October, the registration landing page
showed only stage 21 / 4 October and explicit `¡¡PLAZAS AGOTADAS!!`.
It did not expose stage 22 or 8 November in the current rendered content.

This difference is important: discovery and current registration status should
not be assumed to come from the same document.

## Production probe

### Device context

Read-only probe performed from the production Termux environment:

- local date/time: 2026-10-02 19:20 +0200;
- branch: `main`;
- HEAD: `527665b5657862d713d003ddfcb36e8f81bd9b5d`;
- clean working tree;
- curl 8.18.0;
- Python 3.12.12.

The probe changed no project or state files and sent nothing to Telegram.

### Landing page transport

`https://convega.com/rutasguiadas-senderodelmediterraneo/`

Observed:

- HTTP 200;
- no redirect;
- HTTP/2;
- TLS verification successful;
- `text/html; charset=UTF-8`;
- compressed transfer approximately 41 KB;
- expanded local HTML approximately 276 KB;
- total request time approximately 1.53 s.

Visible evidence included:

- `Ruta por la Etapa 21 del Sendero del Mediterráneo`;
- `¡¡PLAZAS AGOTADAS!!`;
- Guardamar;
- 4 October 2026 / `04/10/2026`.

It did **not** contain:

- stage 22;
- 8 November 2026;
- `forms.gle`;
- `google.com/forms`;
- WPForms / Gravity Forms / Forminator / Contact Form 7 markers;
- a visible registration form.

The only HTML form was the site search form.

The page exposed stable WordPress metadata:

- page ID: `41588`;
- canonical landing URL;
- shortlink `?p=41588`;
- REST endpoint:
  `https://convega.com/wp-json/wp/v2/pages/41588`.

The production probe fetched that REST endpoint successfully:

- JSON size in the unrestricted probe: about 78.7 KB;
- ID: `41588`;
- WordPress date: `2026-09-16T09:35:54`;
- modified: `2026-09-23T08:42:33`;
- slug: `rutasguiadas-senderodelmediterraneo`;
- published page;
- `content.rendered` about 60.5 KB.

The REST body itself contained:

- `plazas agotadas`;
- stage 21;
- 4 October 2026.

It did not contain:

- stage 22;
- 8 November;
- a Google Forms registration URL.

This proves that a browser/JavaScript execution is not needed to observe the
current terminal registration state.

### Senderismo category transport

`https://convega.com/category/senderismo/`

Observed:

- HTTP 200;
- no redirect;
- HTTP/2;
- TLS verification successful;
- approximately 32.8 KB compressed transfer;
- request time approximately 0.99 s.

The page exposed:

- WordPress category ID `338`;
- REST endpoint
  `https://convega.com/wp-json/wp/v2/categories/338`;
- the current article
  `Convega organiza dos rutas guiadas por el GR-92...` as the first heading.

The category HTML did not itself expose the stage/date details. It is therefore
best viewed as a cheap discovery/index surface, not the factual event-detail
record.

### Announcement article transport

The current GR-92 announcement article observed:

- HTTP 200;
- no redirect;
- HTTP/2;
- TLS verification successful;
- approximately 36.3 KB compressed transfer;
- request time approximately 0.93 s.

Visible text contained:

- `inscripción`;
- stage 21;
- stage 22;
- Guardamar;
- 4 October;
- 8 November.

The article exposed:

- WordPress post ID `42197`;
- REST endpoint
  `https://convega.com/wp-json/wp/v2/posts/42197`.

No dedicated registration form was present in the article HTML.

### Probe conclusion

The phone can read everything required for this source through ordinary HTTPS.
There is no reason to use a browser.

The current best source model is:

- **category/index or bounded posts REST list** for cheap discovery;
- **specific announcement post REST content** for event identities/dates when
  a new/changed candidate appears;
- **registration landing REST page** for the current campaign state.

The current landing page is not sufficient by itself as a future-event
catalogue.

## Recommended lightweight REST strategy

The normal runtime should avoid downloading the three full HTML pages used by
the diagnostic probe.

The intended steady-state flow is:

1. one tiny WordPress REST discovery request, for example:
   `/wp-json/wp/v2/posts?categories=338&per_page=3&_fields=id,date,modified,slug,link,title`;
2. one tiny registration-page metadata request, for example:
   `/wp-json/wp/v2/pages/41588?_fields=id,modified`;
3. fetch full `content` for a post/page only if the ID is new or its
   `modified` timestamp changed.

Candidate detail calls should also use `_fields` so the adapter receives only
the fields it actually validates.

The intended ordinary day is therefore approximately:

- two small REST GETs;
- zero browser;
- zero JavaScript execution;
- zero image/OCR work;
- zero AI for factual extraction;
- no full HTML parser;
- no continuous polling.

A change day may add one bounded detail REST GET.

The exact REST response sizes with `_fields` are still to be measured in a
small follow-up probe before implementation. The architecture does not depend
on a particular byte count.

### HTTP implementation

Use the project's existing standard-library `fetch_bounded()` transport.

Do not add:

- `requests`;
- BeautifulSoup;
- Playwright;
- Selenium;
- Chromium;
- a browser driver.

The CONVEGA adapter should have its own exact HTTPS URL policy, bounded JSON
size and timeout, while reusing only the shared transport mechanics.

## Source identity

Stable registration identity is the most important correctness property.

### Rule

`record_id` must be assigned by the source adapter and must not depend on
mutable title/date presentation.

Bad identity:

`title + event date`

because a reschedule would look like one event disappearing and another being
created.

Preferred source-local shape:

`convega:gr92:stage-21:2026`

`convega:gr92:stage-22:2026`

The date is not the identity.

If a future source provides an immutable organizer/event ID, that ID should be
preferred. A canonical article ID can support provenance but is not sufficient
when one article contains multiple independently registered occurrences.

If stable identity cannot be proven for a source, semantic status transitions
and reschedule notifications must fail closed rather than guess.

## Minimal normalized registration contract

The current proposed v1 contract is intentionally smaller than the recurring
course model:

```text
record_id
source
source_url
title

event_start_date
event_end_date?

registration_start_date?
registration_start_time?
registration_end_date?
registration_end_time?

status
until_full

registration_url?
registration_contact?
```

Snapshot-level fields:

```text
version
observed_at
events[]
registrations[]
```

`observed_at` belongs to the source snapshot and should not be duplicated in
every record.

### Status

Minimal explicit status enum:

- `unknown`
- `open`
- `full`
- `closed`

The status is an accepted source claim, not a conclusion from disappearance.

Examples:

- explicit `PLAZAS AGOTADAS` -> `full`;
- a known date boundary passing does not fabricate `closed`;
- disappearance of `PLAZAS AGOTADAS` produces `unknown`, not `open`;
- `full -> open` is publishable only when the new source evidence positively
  proves `open`.

### Optional bounds

Unknown dates remain null.

Examples:

- "registration until 10 October" -> unknown start, known end;
- "registration starts 5 October" -> known start, unknown end;
- "while places remain" with no dates -> no fabricated deadline.

Exact time is stored only when the source explicitly publishes it. A date-only
deadline is not converted to 23:59.

### Deliberately excluded from v1

Do not add until a real source requires them:

- registration window arrays;
- `event_key` / `group_key`;
- variant-label state;
- participant-kind state;
- capacity counts;
- capacity unit;
- price periods;
- waitlist state;
- suspension state;
- general event cancellation state.

A future multi-distance run or multi-category tournament can initially expose
one stable `record_id` per independently registered variant. An optional
grouping key can be added later without changing the lifecycle engine.

## Relationship to the existing Event model

A source may project the same source observation into two independent
representations:

1. ordinary `Event[]` for Morning / Tomorrow / Weekend;
2. minimal `RegistrationRecord[]` for registration lifecycle notices.

RegistrationRecord must **not** enter `_merge_events()`.

The existing Event pipeline remains the single model for normal resident event
display. The registration lifecycle should not expand `Event` with a generic
state machine.

This preserves the architecture established by ADR 0080: one existing Event
model for planning/digest publications rather than a second general event
model.

## Source ownership and deduplication

Registration lifecycle has one authoritative owner per registration.

For a CONVEGA-organized guided route, CONVEGA owns the RegistrationRecord even
if Ayuntamiento or Todo Cultura also mention the event.

Do not build a generic cross-source registration merger.

Ordinary Event facts may still be merged by the existing event pipeline.

This source-ownership boundary avoids ambiguous status/link conflicts and
keeps identity source-specific.

## Existing Event merge risk discovered

The current `_merge_events()` combines optional fields additively, including:

- `registration_url`;
- `registration_contact`;
- `access_note`.

A possible conflict is:

- current authoritative source: `места закончились`, no active form;
- older duplicate source: still carries a registration URL.

A merged Event could otherwise render a contradictory line equivalent to:

`места закончились · Регистрация`.

The implementation must add a narrow presentation/merge regression so a
terminal normalized access fact suppresses stale registration action in
resident display.

Do not solve this by adding a full registration lifecycle to the global Event
model.

## Lifecycle semantics

### First discovery

Unlike recurring course catalogues, first successful source observation is not
always silent.

If a one-off future registration is first discovered while it is currently
active, this is useful resident information.

Wording:

- known opening occurred earlier -> `Идёт запись...`;
- source-backed opening is exactly today -> a same-day opening wording may be
  used;
- first-seen `full` / `closed` -> silent baseline because the audience was
  never previously invited to register.

This differs intentionally from course catalogue launch behavior.

### Announced vs observed

The system must distinguish:

- bot has observed the record;
- audience has been told about the record.

Only successfully published registrations enter `announced_record_ids`.

Consequences:

- first-seen full -> baseline only;
- first-seen full later becomes explicit open -> `Идёт запись`, not
  `снова открыта`;
- previously announced open becomes full -> `Места закончились`;
- previously announced full becomes explicit open -> reopening notice.

### Opening boundaries

A known tomorrow opening may create one advance notice.

If the advance notice was not delivered, same-day evaluation may produce a
fallback.

Do not publish both by default.

If the source provides only a date:

- before that day -> `завтра открывается...`;
- on that day -> `сегодня открывается...` or current-active wording according
  to evidence;
- do not invent an hour.

If the source provides an exact time, wording may distinguish before/after the
time.

### Closing boundaries

For an explicit end date:

- preferred reminder: day before;
- same-day notice only when the day-before reminder was not delivered.

No end date -> no closing reminder.

Past deadlines are never replayed after device downtime.

### `until_full`

For one-off events, `until_full` means that places may run out before the
published deadline.

It must not reuse course-specific wording that implies registration can
continue after the main period.

Suitable meaning:

`до 10 октября, если места не закончатся раньше`.

### Status precedence

Current explicit terminal status beats a future boundary.

Example:

- status = full;
- nominal deadline = tomorrow.

Result: publish only the full/places-ended semantic outcome, not "registration
ends tomorrow".

### Disappearance

Record/source disappearance proves nothing.

On source error, partial parsing, empty/unexpected response or record
disappearance:

- no closed/full/cancelled claim;
- keep the last accepted semantic baseline;
- no automatic all-clear/reopening.

### Deadline changes

For a registration previously announced to residents, a meaningful source-backed
deadline extension/shortening can produce one corrective notice.

Do not notify on every metadata change.

### Event date changes

If a previously announced registration retains the same stable record identity
but its event date changes, one narrow corrective notice is useful because the
previous registration message is now materially stale.

Use factual wording such as:

`Изменилась дата мероприятия — теперь ...`

Do not infer the reason ("organizers postponed") unless the source explicitly
states it.

### Cancellation/postponement

A general event cancellation lifecycle remains out of scope for this feature.

A registration notifier must not infer cancellation from disappearance.

If a source explicitly shows an event as cancelled, its adapter must not expose
the registration as active, but a broader cancellation notification system is
a separate design problem.

## Temporal validation and impossible states

The adapter/lifecycle must fail closed on contradictory normalized facts.

Examples requiring suppression/diagnostic handling:

- event end before event start;
- registration start after registration end;
- explicit `open` while the same accepted record also gives an already passed
  absolute registration deadline;
- other mutually inconsistent status/boundary facts.

A registration-metadata conflict should suppress registration lifecycle output
for that record without necessarily deleting an otherwise valid ordinary Event.

## Freshness

Registration notices require a source snapshot observed on the same
Europe/Madrid calendar date.

Stale snapshot:

- no new registration notice;
- no date-boundary reminder;
- no baseline erasure;
- no inferred closure/full/cancellation.

Known future boundaries should still require a fresh same-day source snapshot
on the trigger day. This matches the project's fail-closed course/tomorrow
patterns.

A separate immediate control GET before publication is not recommended for v1.
Registration is not a safety-critical real-time feed, and the source refresh
should remain independently bounded. If production later proves that a few
hours of same-day staleness causes false availability messages, a
candidate-only confirmation can be added from evidence rather than
pre-emptively.

## Notification state

A separate small file is preferred, conceptually:

`state/event_registration_notifications.json`

Minimal state:

```text
version
baseline
announced_record_ids
sent_triggers
pending
```

Do not overload the global Morning publication state.

### Baseline

Stores last accepted normalized registration records.

A source failure/disappearance must not replace the baseline with an
authoritative empty catalogue unless the source contract proves completeness.

### `announced_record_ids`

Bounded set of records for which a public registration message was confirmed
sent.

Used to gate:

- full/closed notices;
- reopening wording;
- corrective deadline/event-date changes.

### `sent_triggers`

Bounded exact date/event trigger keys for at-most-once boundary notices.

Example keys:

- `opening-tomorrow:<record>:<date>`
- `opening-today:<record>:<date>`
- `closing-tomorrow:<record>:<date>`
- `closing-today:<record>:<date>`

A bounded limit such as the most recent 512 trigger keys is sufficient.

Past boundary triggers are never replayed.

### Pending delivery

At most one Telegram message should be produced by a registration-notification
run, so the pending state can be much simpler than course notifications.

Conceptual pending fields:

```text
created_at
valid_until?
message
candidate_baseline
candidate_announced_record_ids
candidate_sent_triggers
status
```

Delivery status:

- `pending`
- `uncertain`

A separate per-message `sent` sub-state is unnecessary because a run sends
at most one Telegram message.

## Time-sensitive pending expiry

A new bug class was identified during design review: an exact-time message may
become false before the scheduled retry.

Example:

- 09:47 builds "registration opens today at 10:30";
- Telegram definitively rejects the send;
- retry runs at 11:47.

The old text must not be sent after 10:30.

Therefore pending delivery may carry `valid_until`.

Before a safe retry:

- if still valid -> retry;
- if expired -> discard/recompute from the current fresh snapshot;
- if the new semantic state is now "registration is active", render the current
  wording instead.

An `uncertain` delivery is different: it may already exist in Telegram and
must **not** be auto-cleared merely because `valid_until` passed. Operator
inspection remains required.

## Telegram delivery safety

Copy the project's existing invariants rather than building a generic engine:

1. exclusive file lock;
2. build one candidate;
3. atomically persist the delivery reservation as `uncertain` immediately
   before the non-idempotent Telegram send;
4. confirmed success commits baseline/announced/triggers and clears pending;
5. explicit deterministic rejection / rate limit may restore safe retryable
   pending where applicable;
6. ambiguous timeout/failure remains `uncertain`;
7. automatic resend is blocked while uncertain.

A corrupt lifecycle state must fail closed. Never silently reset state and
risk replaying old registrations.

No common `AtomicJsonStore` or generic lifecycle framework is needed now.
Specialized small state classes are already an accepted project pattern.

## Message design

Messages should be short, factual and action-first.

### Already active when discovered

```text
📝 Идёт запись на маршрут GR-92

📅 4 октября
Маршрут по этапу 21: Guardamar del Segura → Torrevieja
🔗 Записаться

📣 обЪявления Гуардамар
```

Do not say "opened" when the bot only knows that registration is active now.

### Deadline reminder

```text
⏳ Завтра заканчивается запись

• Турнир ...
  📅 мероприятие — 12 октября
  Запись до 10 октября, 19:30 · Записаться
```

### Full

```text
🎟 Места закончились

• Маршрут GR-92 — 4 октября
```

### Event date correction

```text
🗓 Изменилась дата мероприятия

• Турнир ... — теперь 19 октября
```

### Grouping

A run sends at most one Telegram message.

If several semantic changes qualify, group them into compact sections such as:

- registration opened/active;
- deadline tomorrow;
- places ended;
- corrected date/deadline.

Do not create one Telegram push per event.

If the generated message unexpectedly exceeds Telegram limits, v1 should fail
closed rather than introduce multi-message transaction complexity.

## Links and provenance

`source_url` and `registration_url` are separate facts.

- `source_url`: official event/campaign page that supplies context and
  provenance;
- `registration_url`: direct actionable form/booking link, when verified.

A registration form may disappear or move after places fill, while the
official source page remains useful.

Registration URLs must follow strict HTTPS/source-specific validation. Do not
turn the shared registration-host allowlist into a broad list of arbitrary
third-party domains.

The exact source/action URL policy for future CONVEGA active registration
still needs to be verified when a live open-registration state is available,
because the current production page was already full and exposed no active
form.

## Translation

The normal `prepare-event-translations` flow prepares municipal/Agenda/etc.
titles for today and tomorrow, while one-off registration can be useful weeks
before the event.

The registration notifier must not call AI.

Recommended extension:

- existing translation preparation also reads a bounded set of current/future
  CONVEGA registration/event titles;
- only cache misses go to the existing approved title translation path;
- cap the number of CONVEGA future registration titles;
- if translation is unavailable, safe normalized Spanish is preferable to
  blocking a factual registration notice.

No new translation cron or AI workflow is required.

## Runtime scheduling and phone-load analysis

The requested product goal is not only freshness but also avoiding CPU/RAM/
network overlap on the weak Android device.

Current recurring minute-level background/one-shot work includes:

- Hidraqua: `:00` and `:30`;
- capacity backstop: `:12`, `:27`, `:42`, `:57`;
- CCE/Previfoc: `:19`;
- TomTom traffic: `:37`;
- earthquakes: `:55`.

Therefore no hour is completely empty.

The widest stable gap in the recurring minute schedule is the interval after
`:42` and before `:55`.

The main morning load also includes:

- 05:00 transport sync;
- 05:10 municipal event refresh;
- 05:30 Agenda refresh;
- 06:00 / 06:30 / 07:00 event translation preparation;
- 07:15 AEMET preparation;
- 07:30 Morning Digest;
- 08:05 SUMA;
- 08:42 transport notifications;
- 09:02 guide sync;
- 09:42 and 11:42 course notifications;
- 10:10–10:40 SafeBeach/update window;
- 11:11 resident news.

Afternoon/evening work includes:

- Product Awards at 14:20;
- resident news at 15:11 and 18:11;
- weekend/tomorrow event planning around 19:15–20:25;
- seasonal bathing/guide work;
- electricity attempts starting 20:30.

### Recommended registration schedule

Current preferred schedule:

- **12:47** — CONVEGA REST sync;
- **12:50** — local registration lifecycle evaluation/publication;
- **13:47** — conditional recovery sync;
- **13:50** — conditional recovery publication.

This is preferable to the earlier 09:47/11:47 idea because the main morning
cycle and SafeBeach work have completed.

At 12:47 the prior recurring process begins at 12:42 and the next scheduled
recurring process is 12:55. The CONVEGA source call is expected to be a tiny
REST one-shot rather than the much heavier diagnostic HTML reads.

### Recovery must be cheap

13:47 is not a second unconditional source fetch.

If today's valid CONVEGA snapshot already exists:

- recovery sync exits before HTTP.

Likewise the recovery publication should exit immediately when:

- no eligible semantic change exists;
- the change was already sent;
- delivery is uncertain.

This yields one real source refresh on normal days.

### Shared runtime lock

New launchers should participate in the existing
`state/code-runtime.lock` convention where appropriate.

This protects the device from real overlap even if a preceding :42 job takes
longer than expected.

If 12:47 cannot acquire the lock, it exits cleanly and 13:47 supplies a bounded
recovery opportunity.

The combination is:

- cron staggering;
- shared runtime lock;
- one-shot process;
- conditional recovery.

Do not solve overlap with a sleeping process or internal retry loop.

## Event catalogue timing

The earlier design considered putting CONVEGA into the 05:10
`sync-municipal-events.sh` wrapper. After full cron/load review, a dedicated
small CONVEGA source one-shot around 12:47 is preferred so it does not enlarge
the already busy pre-morning workload.

The normalized CONVEGA Event facts should still be consumable by existing
Morning / Tomorrow / Weekend pipelines.

The 12:47 snapshot is naturally fresh for same-evening event planning.

Friday's existing `--fresh` weekend workflow should eventually be reviewed so
CONVEGA is not uniquely stale compared with sources deliberately refreshed
before the Friday digest. If CONVEGA is added to the Friday late refresh, that
refresh must remain source-only; it must not create an additional registration
notification cadence.

This exact Friday integration remains an implementation detail to settle
against the final source adapter.

## Cron ownership

Registration is an event-planning concern, not a guide/course concern.

If the final cron entries are installed through an existing managed block,
`termux/install-weekend-cron.sh` is the better ownership boundary because it
already describes itself as event-planning notices and owns Weekend/Tomorrow.

Do not rename its historical marker merely for naming purity if that creates
production crontab migration risk.

No separate resident scheduler or daemon is needed.

## Expected runtime cost

Steady state target:

- one short CONVEGA source one-shot/day;
- about two tiny REST requests on an unchanged day;
- detail REST only when a source ID/modified value changes;
- one local JSON lifecycle check;
- recovery commands normally exit before network/send;
- no browser;
- no OCR;
- no model for extraction;
- no new Python dependency;
- no database;
- no queue;
- no background worker.

The production diagnostic full-HTML requests completed in approximately
0.9–1.5 seconds, so the intended `_fields` REST reads should be materially
lighter. Exact timing/bytes still need measurement.

## Cleanup

Lifecycle state should remain bounded.

Candidate cleanup rule:

- once `event_end_date or event_start_date < today - 30 days`, old inactive
  baseline/announced entries may be pruned;
- do not prune a record referenced by unresolved pending/uncertain delivery;
- `sent_triggers` remains fixed-size rather than an unbounded history.

No raw source archive is needed.

## Failure behavior

### Source unavailable

Preserve the last-good snapshot/baseline and publish no new source-state claim.

### Source malformed or unexpectedly empty

Fail closed. Do not treat parser failure as authoritative deletion.

### Registration metadata conflict

Suppress registration lifecycle for that record. Preserve an independently
valid Event if possible.

### State JSON invalid

Fail closed and require operator repair. Never silently recreate empty state
and replay the catalogue.

### Telegram ambiguous

Leave uncertain and stop automatic resend.

### Translation unavailable

Use safe source-language title if the source/event facts are otherwise valid.

## Test matrix before production

### Source / REST

- exact host/path allowlist;
- HTTP status/content-type/size/timeouts;
- malformed JSON;
- missing required WordPress fields;
- bounded `_fields` responses;
- category/post/page ID validation;
- unchanged `modified` skips detail fetch;
- changed/new ID fetches detail once;
- current `PLAZAS AGOTADAS` fixture -> full;
- broken/unexpected content does not erase last-good snapshot;
- stage 21 and stage 22 remain distinct identities.

### Normalization

- reversed event interval rejected;
- reversed registration interval rejected;
- unknown bounds preserved as null;
- no invented 23:59;
- explicit open + already-passed accepted deadline conflict fails closed;
- title/date change does not mutate stable record identity.

### Lifecycle

- first-seen active -> `Идёт запись`;
- first-seen full -> silent;
- observed-but-never-announced full -> explicit open renders current active,
  not "reopened";
- announced open -> full;
- full -> unknown silent;
- announced full -> explicit open;
- record disappearance silent;
- stale snapshot silent;
- missed past opening/deadline not replayed;
- deadline extension/shortening for announced record;
- event date correction for announced record;
- full + deadline tomorrow -> only full.

### Exact time and retry

- opening later today renders future time;
- retry after opening time does not send stale future wording;
- deadline already passed at current time does not send a same-day reminder;
- retry after `valid_until` recomputes;
- ambiguous send remains uncertain even after `valid_until`.

### Event integration

- CONVEGA Event can appear in Morning when relevant;
- Tomorrow can read the same normalized source;
- Weekend can read it;
- cross-source duplicate does not create two resident events;
- terminal access state cannot render together with stale registration action.

### Delivery/state

- exclusive lock;
- atomic write;
- deterministic Telegram rejection returns to safe retryable state;
- HTTP 429 safe retry;
- ambiguous send blocks auto-resend;
- confirmed success commits baseline/announced/triggers exactly once;
- corrupt state fails closed;
- cleanup never removes unresolved delivery evidence.

### Termux/cron

- installer remains idempotent;
- unrelated crontab rows preserved;
- historical managed block upgrades safely;
- runtime lock busy at 12:47 -> no overlap and no error storm;
- 13:47 recovery performs HTTP only when today's accepted snapshot is absent.

## Rejected alternatives

### Browser / Playwright / Selenium

Rejected. Production proves plain HTTPS and WordPress REST expose the needed
current content.

### Full HTML pages every day

Rejected as default. Diagnostic HTML works but is much heavier than the
available REST projections.

### One landing-page GET as the whole catalogue

Rejected. Current landing content contains only stage 21 while the official
announcement contains stages 21 and 22.

### Generic registration framework

Rejected. One small source-independent lifecycle module plus source-specific
adapters is enough.

### Generalize `course_notifications.py`

Rejected. It is correctly coupled to recurring guide/course semantics and
different registration wording.

### Expand global Event with lifecycle fields

Rejected for v1. Event remains the existing presentation model; registration
state is a parallel narrow concern.

### Database / queue / resident worker

Rejected under runtime constraints and unnecessary for the scale.

### Frequent polling / confirmation GET before every publication

Rejected initially. Same-day source freshness is sufficient unless production
proves a meaningful false-availability problem.

### Source disappearance means closed

Rejected. Missing data is unknown.

### First source run is always silent

Rejected for one-off active registrations because that can suppress the only
useful registration notice. First-seen full remains silent.

### Price/capacity/link/contact change notifications

Rejected to prevent scope creep into a general event watcher.

## Remaining empirical questions

Before source-specific parser implementation is finalized:

1. Measure real response sizes/timing of the proposed REST `_fields` URLs.
2. Verify the exact JSON shape/order of the Senderismo posts list.
3. Observe a future CONVEGA campaign while registration is actually open:
   - where the actionable registration link appears;
   - whether the landing page carries an explicit open marker or only a form;
   - whether one page is reused for successive stages;
   - whether `modified` reliably changes when the registration state changes.
4. Determine the most stable source-backed stage identity available in
   announcement/landing content.
5. Confirm whether stage 22 eventually replaces stage 21 on page 41588 or
   appears through another page/record.
6. Decide the exact Friday late-refresh integration once the source adapter
   contract is known.
7. Measure actual process duration under the intended REST-only source adapter
   to validate that 12:47/12:50 remains comfortably inside the quiet interval.

## Recommendation

Proceed with a **REST-only, browser-free CONVEGA proof of implementation**.

The architecture should remain:

- source-specific lightweight CONVEGA adapter;
- one small normalized snapshot with Event and RegistrationRecord projections;
- stable source-local registration identity;
- separate event-registration lifecycle state;
- same-day freshness;
- explicit status transitions only;
- one Telegram message maximum per run;
- ambiguous-delivery protection;
- 12:47 source refresh + 12:50 publication;
- conditional 13:47/13:50 recovery;
- existing runtime lock;
- existing Event pipeline for normal event-day display.

Before runtime implementation, run one final small REST probe using only the
candidate `_fields` endpoints and record its byte/timing results. Then convert
the durable choices into an ADR when the source contract and schedule are
accepted for production.
