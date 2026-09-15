# ADR 0067: Linked places and activities guide pilot

## Status

Accepted — 2026-09-16

## Context

The pinned city guide already provides cameras and transport through one
recoverable Telegram message graph. Guardamar also has durable places and
recurring activities that do not fit the daily event pipeline.

The first useful vertical slice is the Polideportivo Municipal and municipal
swimming. The physical hierarchy is real rather than editorial: the
Polideportivo is the complex, while the indoor Manel Estiarte pool and the
outdoor municipal pool are distinct facilities inside it. Swimming is a
recurring activity that links to those facilities but is not itself a place.

The source landscape is uneven. Facility facts are stable enough for a small
static guide. Aqualider's public SimplyBook `/v2/service/` and `/v2/provider/`
endpoints were tested from the production Termux runtime on 2026-09-16 and
returned bounded JSON without a prior session, cookie, CSRF bootstrap, browser,
or HTML scrape. The same account retains old summer services after their season
ends, and copied descriptions contradict provider/venue labels, so visible
catalogue entries alone do not prove current registration or a winter schedule.

A burst of per-service `/booking/working-days/` requests eventually returned an
HTTP 200 `text/html` `Please wait` queue page. Therefore HTTP status alone is not
success, and polling availability once per service would not scale safely.
The frontend contains a multi-service availability endpoint, but its exact
request/response contract has not yet been validated on the production runtime.

## Decision

### Telegram information architecture

Extend the existing pinned graph with exactly six messages:

```text
📌 Полезное о Гуардамаре
├── 📹 Онлайн-камеры
├── 🚌 Транспорт
├── 📍 Места
│   └── 🏟 Polideportivo Municipal
│       ├── 🏊 Крытый бассейн Manel Estiarte
│       └── ☀️ Открытый муниципальный бассейн
└── 🎓 Занятия и секции
    └── 🏊 Плавание
```

All six new messages use the existing shared `обЪявления Гуардамар` footer.
The compact pinned root keeps its existing no-footer convention.

The hierarchy organizes browsing, but cross-links remain direct. The swimming
card links straight to both pool cards, and each pool card links straight to
swimming. Do not add breadcrumb chains.

Do not create separate Telegram cards for the Polideportivo's other courts and
spaces until enough independent resident-facing information exists to justify a
card. The Polideportivo card may list them compactly as plain text.

### Pool season model

Use one deterministic product calendar:

- 16 June through 15 September, inclusive: outdoor municipal pool;
- 16 September through 15 June, inclusive: indoor Manel Estiarte pool.

Do not require a fresh annual announcement for the normal switch. Do not build a
generic exception framework in advance; a real authoritative exceptional
closure or delayed opening can add the smallest explicit override when needed.

Do not describe summer and winter swimming groups as moving or transferring
between pools. They are separate seasonal programmes and registrations.

### Swimming source policy

The first implementation reads only the two small stateless JSON catalogue
endpoints:

- `/v2/service/`;
- `/v2/provider/`.

Store only normalized service/provider identifiers, names, and their
relationships. Do not retain raw JSON, descriptions, pictures, SEO fields,
marketing claims, or response history.

The first successful observation is a silent baseline. Later catalogue changes
are stored and logged but do not by themselves trigger a public programme alert,
because catalogue visibility is not proof of availability.

A source response is accepted only when the HTTPS host, bounded response size,
MIME type, JSON parse, and expected schema all validate. `200 text/html`, empty
or malformed payloads, timeouts, and incomplete cross-references preserve the
last-good normalized baseline and produce no public change.

Do not make one availability request per service. The target is at most one
batched availability request for the whole SimplyBook account after its contract
is validated. If that validation fails, do not fall back to N per-service
requests; leave automatic availability out until a cheaper reliable surface is
found.

Until batched availability is validated, the public swimming card states the
fixed facility seasons and provides a direct booking action link without
claiming that registration is open or publishing an inferred timetable.

### Runtime and state

Add one short-lived `sync-guide` job at 16:30 Europe/Madrid.

The job:

1. performs the two bounded catalogue GETs sequentially;
2. updates one small `state/guide.json` last-good normalized baseline;
3. runs the existing pinned-message reconciliation so deleted guide cards and
   affected links recover through the established self-healing path;
4. on 15 June or 15 September, publishes the deterministic next-day pool-season
   notice once and records that confirmed Telegram message ID.

There is no second publisher job, daemon, worker pool, concurrency layer,
database, per-sport state, per-sport cron, or new dependency.

The existing 05:00 transport sync continues to reconcile the same pinned graph,
so the new static guide cards also benefit from its normal daily recovery.

### Implementation shape

Keep explicit logical keys in the existing `pinned.py`. Do not introduce a
`Place`/`Activity` ontology, relation framework, generic CMS, source scheduler,
or persistence abstraction for this slice.

One small `guide.py` module owns the Aqualider catalogue normalization, guide
state, deterministic pool-season helper, and one-shot guide sync. New sports can
be added explicitly until actual repetition demonstrates a need for a shared
abstraction.

## Consequences

- The resident-facing hierarchy can grow without flattening every facility into
  the root `Места` list.
- Current code remains small and Termux-friendly.
- A SimplyBook queue page cannot erase the last-good state or masquerade as an
  empty catalogue.
- The bot does not fabricate a winter swimming timetable from stale summer
  records.
- Automatic registration availability remains intentionally incomplete until a
  single-account batch request is proven safe.

## Rejected alternatives

- Put both pools directly under `Места`: rejected because the Polideportivo is a
  real parent complex and future sports facilities would flatten the branch.
- Merge both pools into one card: rejected because they have distinct seasons,
  contacts, operational changes, and direct activity links.
- Create generic place/activity/relation models now: rejected as premature
  abstraction.
- Poll `working-days` once per service: rejected after the source returned its
  `Please wait` queue during a small burst.
- Use SimplyBook descriptions/provider names as operational truth: rejected
  because the current account contains contradictory and stale labels.
- Add cookies, CSRF bootstrap, browser automation, or HTML parsing: rejected;
  the required catalogue endpoints work statelessly.
