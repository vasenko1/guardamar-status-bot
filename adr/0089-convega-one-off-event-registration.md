# ADR 0089: CONVEGA one-off event registration lifecycle

- Status: Accepted
- Date: 2026-10-02

## Context

The existing event pipeline is intentionally optimized for today, tomorrow and
the weekend. Some official events are actionable earlier because residents must
register before the event date. Recurring courses already have a dedicated
registration lifecycle, but that implementation is coupled to pinned guide
cards, recurring-course identity and course-specific semantics.

Production investigation of CONVEGA's guided GR-92 campaign established a
lightweight first-party source contract:

- WordPress category `senderismo` is a small discovery index;
- announcement post `42197` contains stage 21 (4 October 2026) and stage 22
  (8 November 2026);
- the stable guided-route landing
  `rutasguiadas-senderodelmediterraneo` is the current registration/status
  surface;
- the current landing proves stage 21 is `PLAZAS AGOTADAS` while it does not
  expose stage 22 as currently registrable;
- WordPress REST exposes the required rendered content without a browser;
- CONVEGA uses multiple registration technologies elsewhere (Contact Form 7,
  Forminator and explicit external CTAs), so registration state cannot depend
  on one plugin implementation.

Two read-only production probes measured the normal source budget at roughly
85 KB for category metadata, one relevant announcement and the current landing.
This is small enough to prefer direct daily content reads over metadata-first
cache complexity.

The design is recorded in
`research/2026-10-02-convega-one-off-event-registration.md`.

## Decision

### Source adapter

Add one narrow `convega.py` adapter for the approved guided GR-92 campaign.

The adapter uses the existing bounded standard-library HTTPS transport and
WordPress REST only. It adds no browser, JavaScript runtime, OCR, source-side
AI, database, queue or new Python dependency.

A normal refresh:

1. reads the complete bounded Senderismo metadata list
   (`per_page=100`, currently 12 posts);
2. identifies the relevant guided-route announcement deterministically;
3. reads its small REST content;
4. resolves the guided-route landing by the stable slug and reads its REST
   content;
5. writes one atomic normalized source snapshot.

The adapter preserves the last-good snapshot on transport or parser failure.

### One source snapshot, two projections

Store one small source-specific `records[]` snapshot rather than duplicated
`events[]` and `registrations[]` copies.

The same source record projects in memory to:

- the existing `Event` model for Morning / Tomorrow / Weekend;
- a minimal `RegistrationRecord` for registration lifecycle notices.

Do not add one-off lifecycle state fields to the global `Event` model and do
not send RegistrationRecord through `_merge_events()`.

### Stable occurrence identity

Use source-owned identity independent of mutable titles and dates.

For the current campaign:

- `convega:post-42197:stage-21`;
- `convega:post-42197:stage-22`.

The WordPress post ID identifies the campaign and the stage identifier
disambiguates occurrences inside it. A date correction therefore preserves
identity. If a future source shape cannot produce an unambiguous stable
occurrence identity, lifecycle semantics fail closed.

### Registration-state evidence

Registration status is one of:

- `unknown`;
- `open`;
- `full`;
- `closed`.

Current landing state may be associated with an occurrence only when the
source-derived occurrence match is unique. Strong identifiers/date facts are
preferred; fuzzy translated-title matching is not registration identity.

Evaluate state in this order:

1. reviewed explicit terminal phrases such as `PLAZAS AGOTADAS` win and
   produce `full`;
2. otherwise, a positively validated event-registration action may produce
   `open`;
3. everything else is `unknown`.

A future `closed` phrase is not accepted until observed and reviewed.

A positive registration action may be either:

- a genuine embedded form with a submit control on the dedicated event landing
  and reviewed registration semantics; or
- an explicit registration CTA with reviewed normalized visible text and a
  strict source-specific HTTPS URL.

Plugin names are not part of the contract. Generic information links,
arbitrary contact/search forms, missing terminal markers and disappearing
actions never imply `open` or `closed`.

For an embedded form, the resident action URL is the canonical public landing,
not the form action returned inside REST-rendered HTML.

Do not broaden the shared global Google-Forms registration URL allowlist for
CONVEGA.

### Current accepted campaign state

At acceptance time:

- stage 21 is `full`;
- stage 22 is `unknown`.

No stage-22 opening notice is allowed until a current source positively proves
an actionable registration state.

### Lifecycle semantics

Add one small source-independent
`event_registration_notifications.py` one-shot.

First observation:

- `open` -> publish current-active registration;
- `full`, `closed`, `unknown` -> silent baseline.

Track audience knowledge separately from source observation through bounded
`announced_record_ids`.

A current `unknown` observation never erases the last explicit status
evidence. State retains `last_explicit_status` separately so
`full -> unknown -> explicit open` can still be identified as reopening when
the audience had previously been told about that registration.

Opening/closing date notices require explicit source-backed boundaries. Use one
tomorrow notice with a same-day fallback only when the advance notice was not
confirmed delivered. Never invent a time or deadline. Past triggers are not
replayed after downtime.

Current terminal state has precedence over date-boundary messages.
Disappearance is silent and never means closed, full, cancelled or reopened.

A redundant explicit close that merely confirms an already communicated
deadline may remain silent; an early/unexpected explicit close may notify.

General event cancellation remains out of scope.

### Delivery state

Keep one small atomic lifecycle state:

```text
version
baseline
announced_record_ids
sent_triggers
uncertain
```

There is no persisted retryable pending queue and no `valid_until`.

Before the single possible Telegram send, atomically persist one `uncertain`
reservation containing the rendered message and exact candidate commit state.
Confirmed success commits that candidate and clears uncertainty. A
deterministic send failure clears uncertainty and leaves the old semantic
baseline so the next run recomputes from current facts/time. An ambiguous send
keeps uncertainty and blocks automatic resend until operator resolution.

This preserves crash safety without the multi-message state machine required by
course notifications.

### Freshness and schedules

Registration lifecycle notices require a CONVEGA snapshot observed on the same
Europe/Madrid date.

Run one wrapper:

- 12:47 normal;
- 13:47 recovery.

The wrapper refreshes CONVEGA only when today's successful snapshot is absent,
then evaluates the local lifecycle. Normal recovery therefore performs no HTTP.

The project-wide `state/code-runtime.lock` may protect only the short source
refresh. Release it before Telegram delivery so a slow low-priority send cannot
block higher-priority hourly 112, earthquake, traffic or capacity tasks.

Morning may consume last-good CONVEGA Event data, matching existing FACV/Pesca
catalog behavior. Tomorrow uses same-day freshness. Friday
`run-weekend.sh --fresh` performs one best-effort CONVEGA source refresh
before Weekend rendering, without creating another registration-notification
cadence.

### Translation

Registration publication performs no AI calls.

The existing event-title translation preparation may consume a bounded set of
future CONVEGA titles from the local snapshot. A title first discovered after
morning preparation may temporarily use normalized Spanish; that does not block
a factual registration notice. No separate translation cron is added.

### Existing Event rendering

A terminal registration access note must suppress a stale merged registration
URL/contact so normal Event display cannot render a contradiction such as
`места закончились · Регистрация`.

Implement this as a narrow exact internal terminal-note rendering guard, not a
global Event registration state machine.

## Consequences

### Benefits

- early actionable notices for official one-off events;
- no browser, OCR or factual AI extraction;
- about 85 KB normal daily source traffic for the current CONVEGA campaign;
- stable identity across date corrections;
- fail-closed behavior for unseen future markup;
- one source observation feeds the existing event pipeline and the narrow
  registration lifecycle without duplicate source state;
- one message maximum per run;
- crash-safe Telegram delivery without a queue.

### Costs

- one new source snapshot;
- one small lifecycle state file;
- two daily one-shot invocations;
- one additional best-effort source refresh in Friday's existing fresh Weekend
  path;
- source-specific parser maintenance if CONVEGA materially changes its campaign
  markup.

## Alternatives rejected

- browser / Playwright / Selenium;
- full-page HTML scraping when REST is available;
- OCR;
- AI extraction of registration facts;
- reusing `course_notifications.py`;
- adding lifecycle state globally to `Event`;
- a generic notification/event bus;
- cross-source registration merging;
- plugin-specific form detection;
- metadata-first landing caching to save tens of kilobytes;
- `per_page=3` discovery;
- four separate sync/publish/recovery cron rows;
- global runtime lock during Telegram delivery;
- persisted retryable message queues / `valid_until`;
- an extra morning CONVEGA fetch;
- a separate translation cron;
- inferring closure from disappearance.
