# CONVEGA and one-off event registration lifecycle

## Status

Research/design finalized after two read-only production probes on 2026-10-02.
The accepted design is recorded in ADR 0089.

Implementation is now present on branch
`feat/convega-one-off-registration` in draft PR #259. The branch contains the
REST source adapter, normal Event projection, one-off registration lifecycle,
Termux wrappers/cron integration, tests, rendering guard and documentation.
It is intentionally **not merged or deployed yet**: the repository has no
general CI workflow, so focused and full regression suites plus one bounded
live source smoke test must pass on the Termux production device before PR
promotion.

Current implementation review additionally enforces:

- Guardamar locality before Event/RegistrationRecord projection;
- explicit-open precedence over same-day opening wording;
- rejection of same-day snapshots whose `observed_at` is in the future;
- operator resolution commands for ambiguous Telegram delivery.

This file remains the empirical source record; ADR 0089 is the durable decision.

## Question

How should the bot discover and publish registration lifecycle information for
one-off public-interest events such as CONVEGA guided routes, tournaments,
runs, hikes and excursions without:

- adding a generic notification framework;
- overloading the existing recurring-course lifecycle;
- creating false registration claims;
- depending on browser automation or AI extraction;
- materially increasing CPU, memory or network load on the Termux phone?

The first concrete source is CONVEGA's guided GR-92 campaign.

## Repository context reviewed

The final review was performed against repository main commit
`8d1b8a3b9cf78764c52a020686387a83bd29204c`.

Before making this research update the required repository instructions were
reviewed:

- `AGENTS.md`;
- `docs/kb/00_Project_Overview.md`;
- `docs/kb/01_Product_Vision.md`;
- `docs/kb/02_Project_Principles.md`;
- `docs/kb/03_System_Architecture.md`;
- `docs/kb/04_Runtime_Constraints.md`.

Relevant durable decisions and patterns were also re-read:

- `adr/0035-weekend-events-digest.md`;
- `adr/0072-unified-course-notifications.md`;
- `adr/0080-next-day-planning-notices.md`;
- existing event merge/rendering code;
- recurring-course delivery state;
- FACV/Pesca local-catalog patterns;
- the shared bounded HTTPS transport;
- current Termux runtime-lock owners and event-planning launchers.

The following inherited constraints remain decisive:

- weak Android / Termux is a product constraint;
- one-shot processes only;
- official/first-party sources only;
- deterministic validation for factual publication;
- source failure remains unknown;
- last-good source state must survive transient failure;
- small atomic JSON state;
- no database, queue, daemon, resident scheduler or browser;
- ambiguous Telegram delivery must not be automatically resent;
- normal event display continues to use the existing `Event` model.

## Executive conclusion

The feature is technically justified and can be implemented without
overengineering.

The final shape is:

1. one small source-specific `convega.py` adapter using WordPress REST;
2. one normalized CONVEGA snapshot with a single `records[]` collection;
3. two in-memory projections:
   - ordinary `Event[]` for Morning / Tomorrow / Weekend;
   - minimal `RegistrationRecord[]` for one-off registration lifecycle;
4. one small source-independent
   `event_registration_notifications.py` lifecycle/delivery module;
5. one normal invocation at 12:47 and one recovery invocation at 13:47;
6. a project runtime lock only around the bounded source-refresh phase, never
   around Telegram delivery;
7. at most one registration Telegram message per run;
8. no browser, JavaScript runtime, OCR or factual AI extraction;
9. no generic event bus or notification framework.

The remaining empirical unknown is only the exact future markup used when
stage 22 becomes registrable. That is not a blocker because the parser can
fail closed to `unknown` until a positively validated registration action is
visible.

## Product problem

Some official/public-interest events are most useful before their event date
because participation requires registration.

Examples include:

- guided routes and excursions;
- public races;
- tournaments;
- municipal or club competitions;
- one-off workshops with a participation deadline.

The existing Morning / Tomorrow / Weekend event pipeline answers primarily
"what is happening today/tomorrow/this weekend". It does not own a long-lived
registration lifecycle.

Recurring courses already have a separate lifecycle in
`course_notifications.py`. That module is deliberately coupled to pinned
guide cards, recurring-course identity, course-specific registration intervals
and multi-message semantic buckets. One-off event registration should not be
forced into that model.

## Scope

### In scope

- one-off official/public-interest events with source-backed registration
  state or registration boundaries;
- the first source: CONVEGA guided GR-92 routes;
- first discovery of an actually active registration;
- explicit full/closed transitions;
- explicit reopening;
- exact source-backed opening/closing date boundaries;
- source-backed registration deadline changes;
- source-backed event-date correction after a registration was announced.

### Out of scope

- recurring course/season enrollment already owned by course notifications;
- private promotional events that do not qualify for the normal event policy;
- generic availability polling;
- participant counts and capacity counters;
- price-change notifications;
- venue/description/route/contact-only changes;
- registration-link-change notifications;
- a general event cancellation framework;
- cross-source registration merging;
- generic plugin/form-provider support outside source adapters;
- continuous monitoring;
- browser automation;
- AI extraction of source facts.

## Confirmed CONVEGA authority model

CONVEGA is the official organizer/source for the researched GR-92 guided
routes.

Three public source surfaces were confirmed:

1. Senderismo category:
   `https://convega.com/category/senderismo/`
2. current guided-route landing:
   `https://convega.com/rutasguiadas-senderodelmediterraneo/`
3. announcement article:
   `https://convega.com/convega-organiza-dos-rutas-guiadas-por-el-gr-92-mejor-sendero-homologado-2025-de-la-comunitat-valenciana/`

The surfaces have different responsibilities:

- the Senderismo category is a discovery/index surface;
- the announcement article is an event-catalogue surface;
- the landing is the current registration/status surface.

The current landing must not be treated as the full future event catalogue.
The announcement currently describes two guided routes while the landing
currently describes only one.

## Production probe 1: WordPress REST contract

A read-only production probe was run from the Termux device on
2026-10-02 at approximately 22:22 Europe/Madrid.

Production context at the start of that probe:

- branch: `main`;
- deployed code HEAD:
  `527665b5657862d713d003ddfcb36e8f81bd9b5d`;
- clean working tree;
- curl 8.18.0;
- Python 3.12.12.

The later repository Research-only commit does not affect any of these source
observations.

### Senderismo category

Confirmed WordPress category:

- ID: `338`;
- slug: `senderismo`;
- current post count: `12`.

Slug lookup returned exactly one category and the same ID.

Measured metadata calls:

- `per_page=3`: 1,424 bytes, about 0.95 s;
- `per_page=10`: 4,780 bytes, about 1.12 s;
- `per_page=100`: 5,710 bytes, about 1.82 s.

`per_page=100` returned all 12 current category posts in one response.

Conclusion:

- `per_page=3` is an unnecessary and brittle optimization;
- the entire current category metadata costs only about 5.7 KB;
- runtime discovery should use one bounded complete metadata list, currently
  `per_page=100`.

The current GR-92 announcement is post `42197`, published
2026-09-21.

### Announcement post 42197

Measured REST detail:

- response size: 9,776 bytes;
- request time: about 2.66 s;
- content text contains:
  - stage 21;
  - stage 22;
  - 4 October;
  - 8 November;
  - registration/form wording;
- it does not contain current `PLAZAS AGOTADAS`;
- it does not expose an embedded registration form.

This confirms that the article supplies event facts but is not the current
availability source.

### Guided-route landing

WordPress page:

- ID: `41588`;
- slug: `rutasguiadas-senderodelmediterraneo`;
- title: `Rutas guiadas Sendero del Mediterráneo`;
- modified: `2026-09-23T08:42:33`.

Slug lookup returned exactly one page and matched fixed-ID lookup.

Measured full REST response with content:

- response size: 68,940 bytes;
- request time: about 1.49 s;
- `content.rendered`: about 60.5 KB;
- visible text: about 2.5 KB.

Current content positively contains:

- stage 21;
- 4 October 2026;
- exact terminal phrase `PLAZAS AGOTADAS`.

Current content does not contain:

- stage 22;
- 8 November;
- registration wording;
- a registration form;
- form inputs;
- a submit button;
- a registration CTA.

The only iframe is a Google Maps embed.

Therefore the current accepted registration states are:

- stage 21 -> `full`;
- stage 22 -> `unknown`.

Stage 22 exists as an event in the announcement, but the current registration
surface does not prove that it is open.

### WordPress search

Site search for "sendero mediterraneo" found both page `41588` and post
`42197`, plus unrelated pages/posts.

Search endpoints are useful for research/recovery but are unnecessary in the
normal source contract. Category + stable landing slug are narrower and easier
to validate.

### `modified_after`

The WordPress collection filter works correctly in the measured case:

- cutoff one second before the page's modified timestamp returned the page;
- cutoff one second after returned an empty list.

This is useful diagnostic evidence but should not be required for normal
runtime. Daily full landing content is cheap enough that correctness is simpler
than metadata-first optimization.

### HTTP cache validators

The page REST response did not provide:

- `ETag`;
- HTTP `Last-Modified`.

Therefore runtime should not depend on `If-None-Match` or
`If-Modified-Since`.

### WordPress revisions

The public page advertises 531 revisions through `_links.version-history`,
but fetching revisions anonymously returns:

- HTTP 401;
- `rest_cannot_read`.

Revisions are not a usable runtime or research dependency.

### Wayback

A research-only CDX lookup for the landing found no usable archived snapshots
and took about 22 seconds.

Wayback is rejected completely for runtime and does not justify further
research effort here.

## Production probe 2: form/action technology

A second read-only production probe inspected public CONVEGA pages selected by
registration/form-related terms.

The goal was to determine whether CONVEGA uses one stable registration plugin
whose markup could define `open`.

The answer is no.

### No universal registration plugin

Observed public mechanisms include:

1. Contact Form 7:
   - `cita-previa`;
   - `orienta-plus`;
   - rendered REST content contains an HTML `<form>`, required inputs and a
     submit control.
2. Forminator:
   - `formulario-inscripcion-concurso-escolar`;
   - rendered REST content contains a Forminator `<form>`, fields and submit
     button.
3. explicit external CTA:
   - `personas-emprendedoras2026`;
   - `Ir a inscripción` links to
     `https://convega.empleactiva.com/emprendedores/registro`.
4. ordinary information links with no form:
   - `convegaprueba` links to the GR-92 landing using
     `MÁS INFORMACIÓN`.

This proves that the GR-92 parser must not be tied to Contact Form 7,
Forminator, Elementor Form, Google Forms or any other specific provider.

### REST content is sufficient to see rendered forms

Both Contact Form 7 and Forminator forms were visible inside WordPress
`content.rendered` returned by REST.

Therefore a lightweight stdlib `html.parser.HTMLParser` is sufficient for
structural action detection. No browser or JavaScript execution is required.

### Embedded form action is not a public registration URL

Contact Form 7 content fetched through REST produced an action resembling the
REST URL plus a form fragment.

Forminator may render with an empty action and submit by JavaScript/Ajax.

Therefore:

- the presence of a validated embedded form may prove an actionable
  registration state;
- its raw `form action` must not be published to residents;
- for embedded forms, `registration_url` should be the canonical public
  landing page.

### Explicit external CTA can be the registration URL

A source-backed explicit CTA such as:

`Ir a inscripción -> https://convega.empleactiva.com/...`

can supply a direct `registration_url` only after strict source-specific URL
validation.

The shared global `normalize_registration_url()` must not be broadened to all
observed CONVEGA-related hosts.

### HTTPS remains mandatory

Another public CONVEGA page contained several `inscripción` buttons pointing
to plain `http://convega.com`.

Those are not acceptable normalized registration URLs.

Source-specific URL policy remains HTTPS-only, with:

- no credentials;
- no custom ports;
- exact allowed hosts;
- source-backed explicit action semantics.

### False-positive lesson from the research parser

The diagnostic script initially classified `MÁS INFORMACIÓN` as
registration-like because the broad substring `form` appears inside the word
`información`.

Production code must not use broad substring matching such as:

- `"form" in text`;
- arbitrary loose keyword fragments.

Registration semantics must use reviewed normalized words/phrases and
structural controls.

## Final lightweight REST strategy

The final design intentionally optimizes for correctness and simplicity rather
than minimum bytes.

### Normal daily source refresh

1. Fetch full Senderismo metadata:
   `/wp-json/wp/v2/posts?categories=338&per_page=100&order=desc&orderby=date&_fields=id,date,modified,slug,link,title`
2. deterministically identify a small bounded set of guided-GR-92 announcement
   candidates from metadata;
3. fetch detail for the relevant current candidate(s) using bounded
   `_fields=id,date,modified,slug,link,title,content`;
4. fetch the guided-route landing by its stable slug with content, validating
   that the slug lookup resolves uniquely.

The current measured cost with one announcement candidate is approximately:

- category metadata: 5.7 KB;
- announcement: 9.8 KB;
- landing: 68.9 KB;
- total: about 84–85 KB/day.

That is roughly only a few megabytes per month and is preferable to adding
metadata cache branches or relying on a modified timestamp for current
registration state.

### No metadata-first landing optimization

Do not use:

`metadata GET -> modified changed? -> detail GET`

for the registration landing.

The full content request is already cheap and directly observes the status
surface.

### Announcement caching

Do not introduce a persisted modified-cache solely to save approximately
10 KB/day for the current announcement.

Always refetch the small bounded relevant announcement detail on the normal
daily source refresh. This makes source behavior simpler and avoids depending
on WordPress edit metadata for material event-date corrections.

### HTTP implementation

Use the existing `fetch_bounded()` stdlib transport with a CONVEGA-specific
URL policy, response size bound and timeout.

Do not add:

- `requests`;
- BeautifulSoup;
- Playwright;
- Selenium;
- Chromium;
- a browser driver.

Use only stdlib JSON + `HTMLParser` for source parsing.

## Source adapter scope

The first adapter should remain intentionally narrow:

- official CONVEGA;
- Senderismo category;
- guided GR-92 campaign announcements;
- the known guided-route landing contract.

It should not try to turn every CONVEGA page into a generic event or
registration source.

Other CONVEGA programmes can receive explicit adapters/rules later if product
scope requires them.

## Source identity

Registration/event occurrence identity must not depend on mutable event dates
or translated titles.

The previously proposed key:

`convega:gr92:stage-21:2026`

is no longer preferred because the same stage could theoretically appear more
than once in a calendar year.

For the current source, the stronger source-backed identity is:

- `convega:post-42197:stage-21`;
- `convega:post-42197:stage-22`.

The WordPress post ID identifies the campaign announcement and the stage
identifier discriminates independent occurrences inside that announcement.

Consequences:

- rescheduling does not change identity;
- a later campaign with a new post ID does not collide;
- stage 21 and stage 22 remain distinct;
- if the source ever contains two indistinguishable occurrences with the same
  stage discriminator, lifecycle semantics fail closed until another stable
  discriminator is proven.

Future adapters should use their own immutable organizer/event IDs when
available.

## Occurrence association

Current registration status from the landing may only be applied to an
announcement occurrence when association is unambiguous.

For the current campaign:

- landing: stage 21 + 4 October;
- announcement: stage 21 + 4 October, stage 22 + 8 November.

This yields exactly one match for stage 21.

The adapter should prefer strong source facts such as:

- explicit stage/occurrence identifier;
- explicit event date.

Do not use fuzzy translated-title matching for registration status.

If the landing produces:

- zero occurrence matches; or
- more than one possible occurrence match,

registration status is `unknown` for that association. Ordinary Event facts
from the announcement remain usable.

### Multi-occurrence landing rule

Do not pre-build a complex DOM-proximity status mapper.

If a future landing shows multiple occurrences and status/action controls
cannot be deterministically associated with each occurrence, fail closed for
registration state and record the source shape for a future source-specific
parser update.

## Final open/full/closed contract

For one uniquely associated occurrence, evaluate current landing state in this
order.

### 1. Explicit terminal status

Reviewed exact source phrases such as normalized
`PLAZAS AGOTADAS` produce `full`.

A future `closed` phrase must be separately observed/reviewed before being
accepted as `closed`.

Terminal state has priority over any stale action control remaining on the
page.

### 2. Positively validated registration action

Only when no accepted terminal marker applies may an occurrence become
`open`.

Valid positive evidence may be:

#### Embedded actionable form

A real HTML form with a submit control, on the dedicated event/campaign
landing, together with reviewed registration semantics for the occurrence/page.

Do not classify an arbitrary contact/search form as event registration.

Do not depend on plugin-specific class names.

For an embedded form:

- status may become `open`;
- resident `registration_url` is the canonical public landing URL;
- never expose the REST-rendered form action.

#### Explicit registration CTA

An anchor whose reviewed normalized visible text has explicit registration
meaning, for example:

- `Inscripción`;
- `Ir a inscripción`;
- `Inscríbete`;
- `Reservar plaza`;
- `Formulario de inscripción`.

The link must pass source-specific strict HTTPS validation.

A generic `MÁS INFORMACIÓN` link is not an opening signal.

### 3. Unknown

Everything else is `unknown`.

In particular:

- absence of `PLAZAS AGOTADAS` is not `open`;
- absence of a form is not `closed`;
- announcement text saying registration exists is not proof that it remains
  open now;
- disappearance of an action does not prove closure;
- disappearance of a record does not prove cancellation.

## Current accepted registration state

At the end of the 2026-10-02 probes:

### Stage 21

`convega:post-42197:stage-21`

- event date: 2026-10-04;
- current landing matches stage/date;
- exact `PLAZAS AGOTADAS` is present;
- no active form/action remains.

Accepted state: `full`.

### Stage 22

`convega:post-42197:stage-22`

- event date: 2026-11-08;
- event exists in the official announcement;
- the official announcement places this route through Torrevieja, Orihuela
  Costa and Pilar de la Horadada, not Guardamar;
- current landing does not describe stage 22;
- no source-backed current registration action for stage 22 has been observed.

Accepted registration state: `unknown`.
Publication relevance: outside the Guardamar Event/RegistrationRecord
projection under the current official facts.

No stage-22 event or registration message is currently justified for the
Guardamar group.

## Locality filter

CONVEGA is a comarca-level organizer, so not every discovered campaign
occurrence is relevant to Guardamar. The official 2026 announcement provides a
concrete counterexample: stage 21 runs between Guardamar and Torrevieja, while
stage 22 runs through Torrevieja, Orihuela Costa and Pilar de la Horadada.

The source layer may parse out-of-area occurrences for campaign consistency,
but user-facing Event and RegistrationRecord projections require explicit
source-backed Guardamar relevance (route/place/start/finish involving Guardamar).
Do not infer locality merely because two stages share one announcement or one
registration landing.

## Normalized source snapshot

Do not store duplicated `events[]` and `registrations[]` copies of the same
source facts.

Prefer one source-specific snapshot:

```text
version
observed_at
records[]
```

Each source record stores the source facts necessary to project both domains,
for example:

```text
record_id
source
source_post_id
source_url
landing_url?

title
occurrence_label?
event_start_date
event_start_time?
event_end_date?
place?
route?

registration_start_date?
registration_start_time?
registration_end_date?
registration_end_time?
observed_status
until_full
registration_url?
registration_contact?
```

Exact final source-record fields should remain limited to facts actually
required by Event projection or the registration lifecycle.

From this one snapshot:

- `convega_events(...)` projects normal `Event[]`;
- `convega_registration_records(...)` projects minimal lifecycle records.

## Minimal lifecycle RegistrationRecord

The source-independent lifecycle contract remains small:

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

Status enum:

- `unknown`;
- `open`;
- `full`;
- `closed`.

Unknown dates remain null. Date-only deadlines are never changed to an invented
23:59.

Do not add in v1:

- window arrays;
- generic event/group keys;
- capacity counts;
- waitlist state;
- participant counts;
- price periods;
- suspension state;
- generic cancellation state.

A future multi-distance/multi-category event can initially emit one stable
record per independently registered occurrence.

## Relationship to the existing Event model

The existing `Event` model remains the only general event-display model.

Do not add one-off lifecycle state fields globally to `Event`.

One CONVEGA source observation may project to:

1. ordinary `Event[]` for Morning / Tomorrow / Weekend;
2. lifecycle `RegistrationRecord[]`.

The registration records never enter `_merge_events()`.

This preserves ADR 0080's single normal event pipeline.

## Existing merge/rendering contradiction

Current event merging independently preserves:

- `registration_url`;
- `registration_contact`;
- `access_note`.

The shared renderer then emits the access note and registration action
separately.

Therefore a terminal source fact can otherwise combine with a stale action from
another duplicate and render a contradiction such as:

`места закончились · Регистрация`.

The minimal fix should remain presentation-oriented:

- CONVEGA terminal state projects one reviewed exact internal access note;
- the event renderer suppresses registration URL/contact when the access note
  is one of the exact internal terminal-registration notes.

Do not use fuzzy substring logic such as "contains закрыт".
Do not introduce a global registration state machine into `Event`.

Lifecycle source ownership remains independent: CONVEGA owns the registration
state even if another municipal source contributes normal Event enrichment.

## Lifecycle semantics

### First discovery

First observation is not universally silent.

- first-seen explicit `open` / positively actionable registration:
  publish `Идёт запись...`;
- first-seen `full`: baseline only;
- first-seen `closed`: baseline only;
- first-seen `unknown`: baseline only.

This avoids missing the only useful registration notice for a one-off event
while avoiding pointless "already full" launch noise.

### Observed vs announced

The state must distinguish source knowledge from audience knowledge.

Only a confirmed successful registration publication places a record in
`announced_record_ids`.

Examples:

- first-seen full -> later explicit open, never announced before:
  `Идёт запись`;
- announced open -> full:
  `Места закончились`;
- announced full -> explicit open:
  reopening notice.

### Unknown must not erase explicit evidence history

A current `unknown` observation is not an explicit state transition.

The lifecycle baseline should retain a separate
`last_explicit_status` evidence value.

Example:

```text
full -> unknown -> explicit open
```

must still be understood as reopening for a record previously announced.

Do not overload current observed status with this historical evidence. Keep the
concepts separate:

- current source record has `status=unknown`;
- state may retain `last_explicit_status=full`.

This prevents stale full from being presented as a current fact while
preserving the evidence needed for later transition semantics.

### Opening boundaries

If the source explicitly provides a future registration opening:

- tomorrow -> one advance notice;
- same-day fallback only when the advance notice was not confirmed delivered;
- exact time wording only when exact time is source-backed.

A date-only opening never invents a clock time.

A past opening discovered later becomes current-active wording only if current
source evidence positively proves `open`. Do not replay an old "opened"
trigger.

### Closing boundaries

If the source explicitly provides an end date:

- preferred reminder: day before;
- same-day fallback only if the day-before reminder was not delivered.

No explicit deadline -> no deadline reminder.

`until_full=true` means capacity may terminate registration earlier. Copy
must preserve that qualifier.

An explicit `closed` transition that merely confirms an already communicated
deadline can normally remain silent. A source-backed early/unexpected close, or
a close for which no closing reminder was delivered, may notify.

### Terminal precedence

Current explicit `full` / `closed` beats opening/closing boundary messages.

Do not send "registration ends tomorrow" when the same fresh source already
proves that places are gone.

### Deadline changes

A meaningful source-backed deadline extension/shortening may notify only when:

- the registration was previously announced;
- the record is still relevant;
- current evidence does not prove a terminal state.

Do not turn an `unknown` current availability observation into an affirmative
"registration remains open" claim.

### Event date correction

If a previously announced registration retains the same stable identity but
its event date changes, one factual correction is useful:

`Изменилась дата мероприятия — теперь ...`

Do not infer the reason unless the source states it.

### Past events

Do not create new registration lifecycle messages after an occurrence's event
date has passed.

Same-day registration remains possible only when current source evidence
explicitly supports it.

### Disappearance

Source/record disappearance is silent.

Never infer:

- closed;
- full;
- cancelled;
- reopened.

### Cancellation

A general event cancellation lifecycle remains outside this feature.

## Final lifecycle state

The earlier persisted retryable `pending + valid_until` design is rejected as
unnecessary for a one-message-per-run lifecycle.

Use a smaller state conceptually:

```text
version
baseline
announced_record_ids
sent_triggers
uncertain
```

### Baseline

Per record, keep:

- latest accepted semantic facts needed for diffing;
- `last_explicit_status` separately from current `unknown`.

The source snapshot itself remains the source of current observed status.

### announced_record_ids

Bounded set/list of registrations the audience has actually been told about.

### sent_triggers

Bounded exact date-trigger keys, for example:

- opening-tomorrow;
- opening-today;
- closing-tomorrow;
- closing-today.

Keep only a bounded recent history such as 512 keys.

Past date triggers are never replayed after downtime.

### uncertain

At most one message exists per run, so no multi-message pending queue is
needed.

Immediately before Telegram send, atomically persist one uncertainty
reservation containing enough information to resolve an ambiguous send, for
example:

```text
created_at
message
record_ids
trigger_ids
candidate_baseline
candidate_announced_record_ids
candidate_sent_triggers
```

The persisted candidate commit state is necessary for operator recovery after
an ambiguous send. Without it, an operator who verifies that the message did
arrive could not safely commit the exact state without risking a later
duplicate.

There is no retryable persisted message.

### Delivery algorithm

1. acquire the lifecycle state lock;
2. read today's accepted source snapshot;
3. compute current records and candidate next semantic state;
4. if no message is needed:
   - commit accepted baseline changes;
   - exit;
5. render one current message;
6. atomically persist `uncertain` with candidate commit state;
7. call Telegram;
8. confirmed success:
   - commit candidate state;
   - clear `uncertain`;
9. deterministic failure:
   - clear `uncertain`;
   - leave the old semantic baseline;
   - next invocation recomputes from current facts;
10. ambiguous failure:
   - retain `uncertain`;
   - block automatic resend until operator resolution.

### Why `valid_until` is no longer needed

A deterministic Telegram failure does not retain old rendered text.

The next invocation recomputes the message from:

- current local time;
- current same-day source state.

Therefore a message like "opens today at 10:30" cannot be blindly retried after
10:30; it will be rebuilt with current semantics.

An ambiguous delivery is never retried automatically, regardless of age.

This removes the need for a separate `valid_until` field and retryable
pending state.

## Freshness

Registration lifecycle notices require a source snapshot observed on the same
Europe/Madrid local date.

Stale/missing/future snapshots:

- create no new registration notice;
- create no date-boundary reminder;
- do not erase baseline evidence.

This requirement is intentionally stricter than Morning event display.

### Morning

Existing FACV/Pesca precedent confirms that Morning can read a last-good local
event catalogue without requiring same-day observation.

Therefore no extra early-morning CONVEGA fetch is needed solely for Morning.

### Tomorrow / Weekend

Proactive next-day/weekend publication should use the same freshness rules
already established by ADR 0080/ADR 0035.

The 12:47 CONVEGA refresh is naturally fresh for normal same-evening planning.

## Scheduling and resource isolation

### Current recurring minute-level work

The reviewed cron landscape includes:

- Hidraqua: :00 / :30;
- capacity backstop: :12 / :27 / :42 / :57;
- CCE/Previfoc: :19;
- traffic: :37;
- earthquakes: :55;
- Morning/event/guide/course work concentrated earlier in the day;
- Product Awards at 14:20;
- resident news later in the afternoon/evening;
- Tomorrow/Weekend event planning in the evening.

The interval after :42 and before :55 remains the widest stable recurring gap.

### Final normal schedule

Use two invocations of the same wrapper:

- **12:47** normal run;
- **13:47** recovery run.

Do not use four separate 12:47/12:50/13:47/13:50 cron rows.

Conceptual wrapper:

```text
if no successful CONVEGA snapshot observed today:
    bounded source refresh

run local registration lifecycle evaluation
```

Normal recovery behavior:

- today's snapshot already exists -> zero CONVEGA HTTP;
- no pending semantic change -> zero Telegram;
- already sent -> no-op;
- uncertain -> no resend.

### Runtime lock scope

The project-wide `state/code-runtime.lock` is currently shared by higher
priority short tasks including 112, earthquakes, traffic and the capacity
backstop.

Do not hold that global lock during registration Telegram delivery.

Otherwise a slow Telegram request could cause an hourly higher-priority monitor
to skip its invocation.

If used for CONVEGA, the global runtime lock should cover only the short
bounded source-refresh phase:

1. acquire global runtime lock;
2. fetch/validate/write CONVEGA snapshot;
3. release global runtime lock;
4. run registration publication under its own lifecycle state lock.

If the 12:47 source phase cannot acquire the global lock, it exits source
refresh cleanly. Publication then finds no fresh same-day snapshot and remains
silent. The 13:47 recovery gets one bounded second opportunity.

No sleeping retry process is introduced.

## Friday Weekend freshness

Once CONVEGA contributes ordinary `Event` records to Weekend, the existing
Friday `run-weekend.sh --fresh` path should best-effort refresh CONVEGA along
with the other event sources before rendering.

This:

- adds no new cron row;
- keeps ADR 0035's late-Friday freshness behavior consistent across sources;
- costs only one extra small Friday source refresh;
- must remain source-only and must not trigger a second registration
  notification cadence.

A failed Friday CONVEGA refresh should fall back to last-good state exactly as
the existing Weekend refresh path does for other sources.

## Translation

The registration notifier performs no AI calls.

Extend the existing translation preparation to include a bounded set of
current/future CONVEGA titles from the local snapshot.

Because the source normally refreshes at 12:47, an announcement first
discovered that day may not have a Russian cache entry until the next normal
translation preparation.

That is acceptable:

- use cached Russian when available;
- otherwise use safe normalized Spanish;
- never block a factual registration notice waiting for AI;
- do not add a separate translation cron.

Friday Weekend may continue using its existing bounded inline translation
behavior.

## URL and provenance rules

Keep these concepts separate:

- `source_url`: official context/announcement page;
- `landing_url`: official current campaign/registration page;
- `registration_url`: resident action URL, only when validated.

### Embedded form

If a dedicated current landing contains a validated event-registration form:

- `registration_url = canonical landing_url`.

Do not publish the REST-rendered `form action`.

### External CTA

If the official CONVEGA page exposes an explicit registration CTA to another
host, accept it only under a narrow CONVEGA-specific HTTPS allowlist.

`convega.empleactiva.com` is an observed valid action host on another
CONVEGA programme, but it should be allowed only when an explicit source-backed
registration action actually points there.

Do not pre-approve every host observed elsewhere on the website.

Do not expand the shared global Google-Forms registration allowlist merely for
CONVEGA.

## Message design

Public messages remain short and action-first.

### First-seen active

```text
📝 Идёт запись на маршрут GR-92

📅 4 октября
Маршрут по этапу 21: ...
🔗 Записаться

📣 обЪявления Гуардамар
```

Do not say "Открылась" when the bot only knows registration is active now.

### Deadline

```text
⏳ Завтра заканчивается запись

• Турнир ...
  📅 мероприятие — 12 октября
  Запись до 10 октября, 19:30
```

Only show an action link when it is currently validated.

### Full

```text
🎟 Места закончились

• Маршрут GR-92 — 4 октября
```

### Date correction

```text
🗓 Изменилась дата мероприятия

• ... — теперь 19 октября
```

One run sends at most one Telegram message. If several records qualify, group
them into compact semantic sections.

Do not introduce multi-message transaction complexity in v1.

If one grouped message exceeds Telegram's limit, fail closed and treat that as
a design/test failure rather than silently splitting the transaction.

## Expected runtime cost

Normal 12:47 source refresh with the current campaign:

- category metadata: ~5.7 KB;
- one announcement detail: ~9.8 KB;
- landing content: ~68.9 KB;
- total: ~84–85 KB;
- each measured CONVEGA request completed in roughly 1–3 seconds.

Processing cost:

- small JSON parsing;
- ~60 KB stdlib HTML parsing;
- deterministic string/date checks.

Normal 13:47 recovery:

- zero HTTP when today's successful snapshot exists;
- normally zero Telegram.

No:

- browser;
- JavaScript engine;
- OCR;
- factual AI extraction;
- new Python dependency;
- database;
- queue;
- resident worker.

## Failure behavior

### Source transport failure

Preserve last-good source snapshot. No new registration-state claim.

### Landing missing or ambiguous

Keep announcement Event facts.
Registration status becomes `unknown`.

### Announcement malformed

Do not replace valid last-good catalogue facts with a fabricated empty state.

### Contradictory normalized dates

Fail closed for that registration lifecycle record.

Examples:

- event end before start;
- registration start after registration end;
- explicit open combined with an already-passed absolute accepted deadline.

A bad registration record should not necessarily destroy an independently
valid ordinary Event contribution.

### State corruption

Fail closed. Do not silently initialize empty state and replay registrations.

### Telegram ambiguous delivery

Retain `uncertain`; block automatic resend.

### Translation unavailable

Use safe source-language title.

## Cleanup

Keep lifecycle state bounded.

Candidate rule:

- prune inactive records about 30 days after event end/start;
- never prune evidence referenced by unresolved `uncertain`;
- bound `sent_triggers` to a small recent history such as 512 entries.

No raw HTTP archive or image archive is required.

## Final test matrix

### CONVEGA REST/source

- exact HTTPS host/path policy;
- category slug/ID validation;
- current category count/pagination behavior;
- `per_page=100` single-response fixture;
- malformed/oversized JSON;
- timeout/HTTP/content-type failures;
- landing slug resolves exactly once;
- current stage-21 full fixture;
- stage-22 announcement exists but landing does not -> unknown;
- announcement includes stage 21 + stage 22 as separate records;
- source failure preserves last-good;
- no dependency on revisions/Wayback/cache validators.

### HTML/action parsing

- exact terminal phrase -> full;
- terminal phrase + stale form -> terminal wins;
- dedicated registration form + reviewed registration semantics -> open;
- Contact Form 7 form recognized structurally, not by plugin name;
- Forminator form recognized structurally, not by plugin name;
- generic search/contact form is not registration;
- map iframe is not registration;
- generic `MÁS INFORMACIÓN` is not registration;
- substring `form` inside `información` does not match;
- explicit HTTPS `Ir a inscripción` CTA may be action;
- plain HTTP action is rejected;
- embedded form action is never exposed as resident URL;
- embedded form uses canonical landing URL;
- ambiguous multi-occurrence landing -> unknown.

### Identity / association

- post+stage identity stable through date change;
- stage 21 / stage 22 distinct;
- a later post with stage 21 does not collide;
- zero/multiple landing occurrence matches fail closed;
- title translation never affects identity.

### Lifecycle

- first-seen open -> current-active notice;
- first-seen full/closed/unknown -> silent;
- announced open -> full;
- first-seen full -> open -> current-active, not reopening;
- announced full -> unknown -> explicit open -> reopening;
- unknown does not erase last explicit evidence;
- disappearance silent;
- stale snapshot silent;
- past trigger not replayed;
- opening tomorrow vs same-day fallback deduplicated;
- closing tomorrow vs same-day fallback deduplicated;
- full beats deadline;
- already-communicated deadline can suppress redundant expected close;
- early explicit close may notify;
- date correction preserves identity;
- past event suppresses new registration lifecycle.

### Delivery

- exclusive lifecycle state lock;
- atomic state writes;
- no retryable persisted pending message;
- deterministic Telegram failure clears uncertainty and leaves old baseline;
- retry recomputes message from current facts/time;
- ambiguous failure retains uncertainty;
- persisted uncertain contains candidate commit state for operator resolution;
- confirmed success commits candidate state exactly once;
- corrupt state fails closed.

### Event integration

- one source record projects to Event and RegistrationRecord;
- Morning can read last-good CONVEGA Event data;
- Tomorrow requires fresh same-day source contribution;
- Weekend sees CONVEGA events;
- Friday `--fresh` best-effort refreshes CONVEGA;
- cross-source normal Event dedup remains existing behavior;
- terminal access note cannot render together with stale registration action;
- no lifecycle fields are added globally to `Event`.

### Termux/cron

- one 12:47 wrapper invocation;
- one 13:47 recovery invocation;
- recovery makes zero source HTTP when today's snapshot is already valid;
- global runtime lock protects only source refresh;
- Telegram delivery does not hold global runtime lock;
- busy 12:47 source lock causes quiet defer to 13:47;
- no daemon/sleeping retry;
- installer remains idempotent and preserves unrelated rows.

## Overengineering audit

The final design explicitly rejects:

- browser / Playwright / Selenium / Chromium;
- OCR;
- source-side AI extraction;
- generic notification/event bus;
- database;
- queue;
- daemon;
- resident scheduler;
- cross-source registration merge;
- plugin-specific form engine;
- persisted retry queue;
- `valid_until` retry state;
- four separate registration cron rows;
- global runtime lock during Telegram delivery;
- metadata-first landing fetch;
- persisted announcement modified-cache solely to save ~10 KB/day;
- extra morning CONVEGA fetch;
- separate translation cron;
- generic cancellation lifecycle;
- generic participant/capacity tracking;
- broad substring matching for registration semantics.

## Remaining empirical question

One natural source observation remains unavailable today:

> What exact markup/action will CONVEGA use when stage 22 becomes currently
> registrable?

This is not an implementation blocker.

The source adapter should:

- classify only positively understood structures;
- return `unknown` for an unseen structure;
- record diagnostics;
- be updated from evidence if stage 22 uses a new pattern.

Do not predict or fabricate that future markup.

## Final recommendation

The research phase is complete enough to proceed to a durable ADR and then
implementation.

Before runtime code:

1. convert the accepted durable architecture from this research into an ADR;
2. recheck the current latest ADR number rather than assuming it;
3. update relevant KB/Decision Log with the accepted architecture;
4. implement source layer first:
   - CONVEGA REST fetch/validation;
   - source snapshot;
   - stage 21/22 fixtures;
   - Event projection;
   - translation-item projection;
   - Friday Weekend refresh integration;
   - terminal-access rendering guard;
5. then implement lifecycle/delivery:
   - RegistrationRecord projection;
   - baseline + last-explicit evidence;
   - announced IDs;
   - bounded triggers;
   - uncertain reservation with candidate commit state;
   - one-message renderer;
   - 12:47/13:47 launcher/cron;
6. run code review and production preview/probe before enabling public sends.

This preserves the project's central tradeoff:

**prefer a small deterministic source-backed system that sometimes says
nothing over a more general system that can confidently say something false.**
