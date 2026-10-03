# 0091: Generalize one-off registration into event-access lifecycle

- Status: Accepted
- Date: 2026-10-03
- Implementation: Pending production probes

## Context

ADR 0089 deployed a source-owned one-off registration lifecycle.
ADR 0090 accepted one Telegram root per event with rich presentation and strict
threaded follow-ups.

Further source review shows that residents need the same proactive treatment
for several ways of getting into an event:

- registration;
- reservation of a place/seat;
- paid ticket sale;
- free ticket/invitation claim.

Guardamar's official cultural sources publish all of these patterns. They also
publish events with several independent sessions, each with its own
registration/ticket link.

The existing global `Event` model already has separate ticket and registration
fields, and existing renderers already distinguish tickets, free tickets,
registration contacts and capacity. The new requirement therefore belongs in
the proactive lifecycle projection, not in a second global Event model.

## Decision

### Target concept: event access

The next one-off lifecycle revision becomes an **event-access lifecycle**.

It answers one narrow resident question:

**Has a source-backed way to obtain access to this future event appeared,
changed, filled or closed?**

It is not a generic event bus, commerce system, ticket inventory, or booking
engine.

Supported access kinds in the first revision:

- `registration` — sign-up/registration;
- `reservation` — reserve a place/seat;
- `ticket` — obtain a paid or free ticket/invitation.

A free invitation remains `ticket` with zero price / invitation presentation
rather than a fourth lifecycle kind.

Free walk-in admission such as `entrada libre hasta completar aforo` does not
create proactive access lifecycle output when the resident has no action to
take in advance.

### One event root, multiple access options

One source-owned event record owns one Telegram root as defined by ADR 0090.

The record may contain one or more source-proven access options.

Conceptually:

```text
EventAccessRecord
  record_id
  source
  source_url
  access_kind
  event facts needed for lifecycle identity
  presentation facts for the current observation
  options[]

AccessOption
  option_id
  label / occurrence time facts
  status
  action_url
  action_text
  opens_at / closes_at (optional source facts)
  price facts (optional presentation)
  capacity_limited
```

This is conceptual schema, not permission to add generic inheritance or a
database.

For the first implementation, `access_kind` belongs to the **event root**, not
to every option. All options under one root therefore share
`registration`, `reservation` or `ticket` semantics. This matches the
reviewed sources and avoids polymorphic per-option rendering.

If a real first-party source later proves that one event simultaneously exposes
heterogeneous access kinds, handle that source explicitly after review rather
than generalizing the first schema in advance.

A normal single-registration event has one option.

A multi-session activity such as an Escape Room may have:

```text
10:00 -> registration link A
12:00 -> registration link B
13:00 -> registration link C
```

All three belong to one event root because the source proves they are sessions
of the same activity.

### Source-proven grouping only

Do not group occurrences merely because titles look similar.

A shared root requires source evidence such as:

- one parent/detail page containing all sessions;
- an explicit source session-family key;
- another deterministic source-owned parent identity.

Current municipal `session_source_key` is useful evidence for a session
family, but production probes must verify whether it is durable enough for
lifecycle identity across source corrections.

Agenda Guardamar already parses multiple occurrence-specific ticket links from
one event detail page. Its future access projection should retain that parent
detail identity instead of flattening every occurrence into unrelated Event
rows.

### Option identity

Each option needs deterministic source-owned identity when per-option state
changes are tracked.

Prefer, in order:

1. explicit source option/session ID;
2. stable occurrence/detail link identity;
3. another reviewed deterministic source key.

Do not treat a translated display label alone as identity.

If a source cannot provide safe option identity, it may still publish one
event-level access root, but option-specific full/closed transitions must fail
closed rather than guess.

### Missing options are not terminal evidence

When a previously known option is absent from a later successful source
observation, preserve its prior semantic baseline. Absence alone does not mean
`full`, `closed`, cancelled or removed.

Only observed options update their semantic evidence. This is the option-level
equivalent of ADR 0089's disappearance/unknown rule.

A newly observed option may create a threaded "added session" notice after the
event root exists. An unobserved prior option is not silently deleted from
lifecycle history before normal event-retention pruning.

### Several action methods are not several options

A single tournament registration may offer:

- web form;
- WhatsApp;
- email;
- an in-person box office or municipal desk.

Those are several ways to perform the same action, not separate access
options.

Keep one option and render one primary validated `action_url` plus a compact
reviewed `action_text` when useful. `action_text` is deliberately broader
than the deployed registration-only `registration_contact`: it may contain
phone/email/WhatsApp instructions or a source-backed offline action such as
"Casa de Cultura, 09:00–14:00".

Do not create artificial lifecycle records for each contact channel.

An `open` option may therefore be actionable through either a validated URL
or reviewed action text. A physical ticket office/reservation desk must not be
forced into a misleading "contact" field merely to satisfy the model.

### Root card templates

The root heading is selected from access semantics, for example:

- `Открыта регистрация`;
- `Открыта бронь мест`;
- `Билеты поступили в продажу`;
- `Доступны бесплатные билеты / приглашения`.

If a future explicit boundary is the first useful notice:

- `Завтра открывается регистрация`;
- `Завтра открывается бронь`;
- `Завтра начинается продажа билетов`.

The rich card keeps the ADR 0090 poster/Russian event presentation contract.

### Multi-option rendering

If different options have different URLs, prefer compact linked rows:

```text
📝 Регистрация:
• 10:00 — Записаться
• 12:00 — Записаться
• 13:00 — Записаться
```

If all options share the same action URL, avoid repeating the same link:

```text
🕐 Сеансы: 10:00 · 12:00 · 13:00
📝 Записаться
```

Use date + time labels when options span several days.

The first revision uses ordinary HTML links in message text/caption.

Do not add inline keyboards by default. Telegram supports URL buttons, but
buttons would add new reply-markup/edit semantics and stale-button management
when one option later fills. Existing HTML links already satisfy the resident
action with lower operational complexity.

### Option-specific trigger identity

Boundary and transition trigger IDs must include the option identity when the
fact is option-specific.

Conceptually:

```text
<kind>:<record_id>:<option_id>:<boundary>
```

The current ADR 0089 record-level trigger key is insufficient for a
multi-session event because two options may share the same deadline/date.

Event-level triggers remain event-level only when the source fact truly applies
to the whole root.

### Per-option lifecycle

Option status keeps the existing narrow states:

- `unknown`;
- `open`;
- `full`;
- `closed`.

One option becoming full does not make the whole event full while another
option remains open.

Examples of threaded follow-ups:

```text
⏰ Сеанс 12:00 — мест больше нет.
На 10:00 и 13:00 запись ещё открыта.
```

If all known options become terminal, a compact event-level summary may say
that no options remain available.

If several options of the same event change in one observation, combine those
changes into one reply to that event root.

Never combine changes from different event roots.

A newly added source-proven option may produce one reply such as
`Добавлен сеанс 15:00 — запись открыта`.

Disappearance alone never means full/closed/cancelled.

### Aggregate event status is derived, not authoritative source truth

Do not persist a synthetic event-level `full` merely because one option is
terminal.

User-facing aggregate wording is derived from the current option set.

Claim the whole event has no availability only when source evidence safely
establishes that no known option remains open and no unresolved/unknown option
could still be available.

### Ticket semantics

A ticket lifecycle may become `open` when a source-specific contract proves
tickets are currently obtainable.

Positive evidence may include:

- an explicit source statement such as `entradas ya están a la venta`;
- a reviewed current sale window plus purchase location;
- an occurrence-specific purchase URL whose source contract has been verified
  to represent current availability.

A price by itself does not prove sale is open.

A future sale window follows the same ADR 0089 timing rule: store silently,
create the rich root the day before opening, then reply when sale becomes
currently actionable if that adds useful information.

User-facing terminal wording depends on kind:

- registration/reservation full -> places unavailable;
- ticket full -> tickets sold out;
- registration closed -> registration closed;
- reservation closed -> reservation closed;
- ticket closed -> ticket sales ended.

### Free invitation semantics

An official `entrada libre con invitación` action with a usable claim link is
treated as zero-price ticket access and is proactively eligible.

An official `entrada libre hasta completar aforo` with no advance action is
not proactively eligible.

This prevents a false "tickets available" alert for simple walk-in admission.

### Existing Event model remains presentation-compatible

Do not replace or duplicate the global `Event` model.

Morning/Tomorrow/Weekend continue using existing fields such as:

- `ticket_url`;
- `ticket_price_cents`;
- `registration_url`;
- `registration_contact`;
- `capacity_limited`;
- `access_note`;
- `image_url`.

Source adapters additionally project one source-owned EventAccessRecord only
when actionable access evidence/future boundaries exist.

Do not scan merged Morning `Event[]` for lifecycle truth.

### Cross-source ownership and duplicate prevention

The same real event may appear in more than one official source. Do not solve
this with a generic fuzzy cross-source merge.

Each accepted access projection must define which source **owns the actionable
access lifecycle** for that source shape.

Examples of the intended rule:

- a municipal/Turismo event whose ticket action delegates to an accepted
  Agenda Guardamar occurrence should not independently create a second ticket
  lifecycle root;
- municipal/Turismo remains the owner for its own registration/reservation
  forms and contacts;
- FACV owns its tournament registration;
- Biblioteca owns a first-party library reservation when proven;
- CONVEGA owns its own registration record.

A secondary official source may enrich presentation only after a deterministic
source-backed join (for example exact action URL + exact occurrence identity).
If that join is not proven, prefer one less-enriched root over a duplicate or
fuzzy merge.

The production probes must therefore inventory not only IDs/options but also
cross-source overlap and delegated action URLs before source ownership is
coded.

Ownership must also remain stable once a Telegram root exists. A later
secondary-source discovery must not silently move the lifecycle to a new
`record_id` and create a duplicate root. After root creation, another source
may enrich or confirm the same access only through the already reviewed
deterministic join. If ownership cannot be reconciled safely, keep the existing
root owner and fail closed on the competing projection rather than migrate it
implicitly.

### Current source implications

#### Municipal/Turismo

Already carries registration/reservation/ticket facts and source-proven session
families for some multi-session events.

Highest-reuse first target, subject to identity/presentation probes.

#### Agenda Guardamar

Already parses occurrence-specific ticket URLs and multiple sessions from one
detail page, with a 45-day event horizon.

The current snapshot loses the parent detail-page identity. A future access
projection should retain that source identity so several session ticket links
can belong to one root.

Do not assume every ticket URL proves current sale until production probes
confirm the live source behavior for available/sold-out/not-yet-open states.

#### Biblioteca

Official activity-registration form exists, and detail pages are already
fetched/cached for changed cards.

Probe first-party event details for occurrence-specific reservation evidence
before extending the adapter.

#### FACV

Official tournament articles can publish current registration contacts, web
forms, capacity and prices.

Several contacts for one tournament remain one option.

#### AM Guardamar

The normalized SourceEvent/Event contract already has ticket/registration
presentation fields and official featured images.

Probe whether current WordPress posts expose deterministic actionable
admission facts often enough to justify access projection.

### Price changes

Price belongs to the rich presentation.

The first implementation does not add a generic price-change lifecycle.
Early-bird/late-price changes can be added later only if real source evidence
shows resident value.

This avoids turning the feature into a ticket-market monitor.

### Legacy-state migration guard

The first event-access deployment migrates the deployed registration state only
once.

Use deterministic single-option migration for each valid v1 record
(`access_kind="registration"`, one stable default option) while preserving
baseline, last explicit status, audience knowledge and sent triggers. Never
invent a Telegram root ID.

Deployment must refuse the migration while the legacy v1 state contains an
unresolved `uncertain` delivery; the operator must resolve that existing
ambiguity first. This avoids trying to reinterpret an in-flight v1 publication
under the new root schema.

If a legacy `announced_record_id` has no root message ID, preserve audience
knowledge. On its next material publication, create one self-contained
replacement/current-state root and store its Telegram ID instead of pretending
the event was never announced or sending an unthreaded follow-up.

### Translation/media/threading

ADR 0090 remains controlling for:

- one rich root per event;
- event-specific poster;
- Russian presentation;
- strict replies;
- root message ID persistence;
- crash-safe ambiguous delivery.

Options are rendered inside that root and later replies.

Poster identity is event-level, not option-level.

### Source horizons are source-specific

Do not impose one global future-event horizon on all access sources.

The current adapters already differ materially: Biblioteca is intentionally
short, Agenda Guardamar and AM Guardamar are roughly month-scale, municipal
programme discovery is month-scale, while CONVEGA is much longer.

Production probes must measure how early actionable access appears for each
source. Increase a source horizon only when its official catalogue actually
contains useful earlier events and the bounded network/storage cost remains
small.

A short Morning-only horizon must not be assumed sufficient merely because it
was adequate for same-day digest rendering.

### Translation selection

Rich access roots for future events require Russian presentation before the
event day.

Do not translate every future catalogue event. Extend the existing
translation-preparation workflow so each source contributes only its future
**actionable access candidates** (plus current Morning items).

This reuses the existing bounded cache and 06:00/06:30/07:00 preparation path
without adding per-message AI or a second translation framework.

### Scheduling/freshness

ADR 0089 / the publication-sync research remain controlling initially:

- reuse existing morning source snapshots;
- per-source freshness in the multi-source revision;
- 12:47 normal + 13:47 recovery initially;
- add no second refresh until production timing probes prove morning snapshots
  materially miss same-day access announcements.

Recurring office/box-office opening hours are presentation instructions, not
daily lifecycle transitions. For example, a ticket campaign available from
1–10 October at Casa de Cultura 09:00–14:00 is one open campaign across that
source-backed sale window; do not emit daily "opened/closed" transitions merely
because the physical desk closes overnight. Exact one-time campaign boundaries
may still drive the normal day-before/current-open lifecycle.

## Consequences

### Benefits

- one coherent resident experience for registration, reservation and tickets;
- supports multi-session activities without one Telegram root per slot;
- reuses existing Event fields, source adapters, media and Telegram links;
- keeps later full/closed updates anchored to one rich event card;
- supports both online and in-person access;
- avoids artificial grouping of contact methods;
- stays bounded and Termux-friendly.

### Costs

- lifecycle model needs an option collection instead of one scalar action;
- state migration must preserve semantic baseline/root IDs while introducing
  option-level evidence;
- Agenda/municipal sources need stronger parent/option identity retention;
- per-option renderer and regression tests are required.

## Alternatives rejected

### One lifecycle record per time slot

Rejected. It would create several nearly identical root cards/posters for one
activity and weaken the event-level Telegram thread.

### One flat registration/ticket URL on the event

Rejected. It cannot safely represent several independent session links.

### Inline keyboards in v1

Rejected as unnecessary transport/edit complexity. Revisit only after real
resident UX evidence.

### Treat every ticket price/link as open sale

Rejected. Sale availability remains source-specific evidence.

### Proactively announce free walk-in capacity

Rejected when there is no resident action before arrival.

### Generic commerce/ticket inventory engine

Rejected. The feature remains a narrow event-access lifecycle.
