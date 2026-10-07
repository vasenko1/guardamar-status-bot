# ADR 0105: Exceptional supermarket closure notifications

- Status: Accepted
- Date: 2026-10-07

## Context

Guardamar residents benefit from advance notice when a physical supermarket
that normally works on a given weekday will be exceptionally closed. A
municipal, regional, or national holiday cannot determine that fact by itself:
the reviewed first-party schedules already show different behaviour between
stores on the same holiday.

Read-only Termux probes on the production Python/OpenSSL stack established
browser-free contracts for exactly three Guardamar stores:

- **Mercadona**, Avinguda del Mediterrani 14, store id
  `283185312286`: the official locator references a bounded
  `storage.googleapis.com/.../data.js` dataset with same-day
  `fechaCreacion`, a seven-day `in/fi` schedule and dated `fs` overrides.
  The reviewed codes are `C`/closed, `FA`/open full day,
  `FM`/open half day and `CR`/closed for works.
- **DIA**, C/ La Redonda 40, public store code `36111`, internal detail id
  `1003631`: `buscarInformacionTienda` returns a small JSON object with
  Monday-Saturday hours, dated holiday hours and temporary-closure fields.
- **masymas**, Av. del Puerto 18-20: the official Alicante / Guardamar form
  returns one exact row with the normal Monday-Saturday schedule and dated
  `Cierra el` / `Abre el` overrides.

The first-party evidence proves exact-date exceptions cheaply. It does not yet
prove one common, stable contract for seasonal Sunday regime boundaries across
all three retailers. One isolated Sunday difference must therefore not be
promoted into a resident-facing seasonal-change claim.

## Decision

Implement one independent short-lived one-shot at **08:15 Europe/Madrid**.
It is intentionally separate from Morning Digest, SUMA and Sports Today.

Each run:

1. queries the three retailer contracts sequentially through the shared
   bounded transport;
2. verifies the exact Guardamar physical-store identity;
3. normalizes only current/future exact-date status in memory;
4. treats only a closure on the reviewed Monday-Saturday baseline as an
   exceptional closure in v1;
5. lets one failed retailer fail independently without suppressing valid
   observations from the other stores;
6. creates at most one supermarket Telegram message per local day.

The reviewed holiday calendar is presentation context only. It never gates
collection and never overrides retailer facts. Shortened-but-open days are not
notification events.

### Lifecycle

Delivery identity is always per store, date and phase:

- `early:<date>:<store>`;
- `tomorrow:<date>:<store>`;
- `today:<date>:<store>`;
- `correction:<date>:<store>`.

Grouping multiple stores or phases into one Telegram message is presentation
only and does not change those identities.

Rules:

- `today`: closure is confirmed for today;
- `tomorrow`: closure is confirmed one day ahead;
- `early`: a closure later in the current Monday-Sunday week is known on
  Monday, or is first discovered Tuesday-Saturday while still at least two
  days away;
- a Monday-known Tuesday closure naturally carries both `early` and
  `tomorrow` identities in one Monday message;
- a Sunday-known Monday closure is only `tomorrow`;
- missed earlier phases are never fabricated later;
- a correction is eligible only when a fresh first-party observation explicitly
  shows open for a date for which this bot previously has a **confirmed**
  closure delivery.

A retailer response disappearing, failing, or merely omitting a formerly
listed closure never proves reopening.

### Crash-safe delivery state

Persist one small atomic JSON file containing:

- the latest successful normalized future closure dates per store;
- bounded `sent` keys;
- bounded `confirmed` keys;
- at most one bounded `uncertain_batch`;
- the last local day on which a supermarket message was confirmed delivered.

Before Telegram send, fresh observations and all message keys are atomically
reserved together. On deterministic send failure the complete pre-send state
is restored, so a later run may retry the same semantic notice.

On ambiguous Telegram failure the reservation is retained and is not
automatically resent. Those keys are accounted in `sent` but not in
`confirmed`; this prevents both duplicate delivery and a later false
"correction" based on an unconfirmed original publication. Distinct later
phases may still be sent on later days.

State pruning preserves current uncertain keys and enforces
`confirmed ⊆ sent`.

## User-facing copy

Messages are deterministic editorial Russian, not status dumps.

They say plainly:

- which store or stores are closed for the whole day;
- whether the date is today, tomorrow, or a named weekday;
- which other reviewed stores are open when mixed behaviour is relevant;
- when applicable, that Guardamar has an official day off and its reviewed
  holiday name;
- on a non-holiday exception, that the store would normally work that weekday.

Source codes, internal ids, state keys and parser terminology never appear in
public copy.

## Runtime and failure bounds

- no browser, JavaScript execution, AI, OCR, database, daemon or raw-response
  archive;
- exact HTTPS host/path/query allowlists;
- bounded response sizes and 15-second request timeouts;
- at most one navigation-style retry, only after 403/406 on the reviewed HTML
  locator pages;
- Mercadona requires same-local-day `fechaCreacion`; stale data fails closed;
- source identity/shape drift fails closed;
- one rotating 512 KiB workflow log;
- installer temporary files live under `$HOME/.cache/crontab`, never `/tmp`;
- no internal polling or retry storm.

Normal daily traffic is two Mercadona GETs (locator + data), one DIA detail GET
and one masymas form POST.

## Deferred boundary

Seasonal Sunday opening/closing transitions remain **deferred**. v1 suppresses
Sunday closure notifications even when an individual response contains Sunday
hours or a Sunday exception. Automation may be added only after first-party
evidence proves a stable regime boundary/range or multiple future Sundays prove
the transition without guesswork.

## Consequences

The feature stays lightweight, retailer-authoritative and independently
deployable. Source drift may temporarily silence one store; this is preferred
to publishing a guessed closure. No nearby-city stores, generic notification
framework, historical schedule database, per-store scheduler or browser
automation is introduced.
