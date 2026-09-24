# ADR 0077 — Minimal SUMA tax-period notifications

Date: 2026-09-24
Status: Accepted

## Context

SUMA Gestión Tributaria publishes two lightweight public HTML surfaces that
together provide the resident-facing facts needed for Guardamar:

- the Guardamar municipal page lists the local taxes currently in or approaching
  a collection period and their exact start/end dates;
- the general voluntary-payment page publishes that campaign's voluntary
  payment dates, the direct-debit setup deadline and the direct-debit charge
  date.

The information changes slowly, but the deadlines are actionable. A frequent
watcher, browser automation, PDF parsing, AI extraction, a database, or a new
resident process would add cost without improving the product.

## Decision

Add one small standard-library adapter in `suma.py`.

Each scheduled run performs exactly two bounded sequential HTTPS GETs:

1. `https://www.suma.es/cuerpo_infmunicipal.xhtml?m=76`;
2. `https://www.suma.es/periodo-pago-voluntario`.

The general payment period is accepted only when at least one Guardamar tax row
has exactly the same start and end dates. Ambiguous, malformed, mismatching or
unavailable HTML fails closed and produces no public message.

The product has exactly four semantic trigger dates:

1. payment-period opening;
2. seven days before the published direct-debit setup deadline;
3. the published direct-debit charge date;
4. one day before the voluntary payment period ends.

A run publishes only when the local `Europe/Madrid` date exactly equals a
trigger date. Missed triggers are never replayed retrospectively.

The first successful production run is a silent baseline. Trigger dates at or
before that bootstrap day are recorded as already accounted for; future trigger
dates remain eligible. Thus a bootstrap on 24 September 2026 produces no old
July/September notices while preserving the 1 October charge notice and
7 October final reminder.

Delivery state is a tiny atomic `state/suma.json` containing only bounded
semantic trigger keys such as `charge:2026-10-01`. The date is part of the key,
so an official future-date revision creates a new future trigger naturally
without a date-change state machine. Exact-date eligibility still prevents
retrospective notices.

Before Telegram send, the trigger key is persisted. A definite delivery failure
rolls it back so a same-day retry remains possible. An ambiguous send keeps the
key to avoid an automatic duplicate because Telegram has no idempotency key.

At most one SUMA message is emitted per run. If trigger dates ever collide, the
higher-value charge/final/debit/opening priority selects one message; the charge
copy also states the remaining voluntary-payment deadline.

## Scheduling

Do not add a SUMA cron row.

The existing `termux/run-daily.sh` invokes `telegrambot suma` immediately
after the 07:30 Morning Digest command. SUMA is a separate process and state, so
its source or delivery failure does not change Morning Digest state. The shell
keeps the Morning Digest exit status and only logs a SUMA failure.

No daemon, queue, database, provider registry, browser, OCR, PDF parser, AI
provider or raw-source cache is added.

## Current 2026 baseline

The official 2026 period is 27 July through 8 October. The direct-debit setup
deadline is 23 September and the charge date is 1 October. The Guardamar page
currently lists IBI urbana, IBI rústica, IAE and vados for that exact period.

With first production bootstrap on 24 September 2026:

- opening and direct-debit reminder are silently baselined;
- 1 October remains eligible for the charge notice;
- 7 October remains eligible for the final reminder.

## Consequences

- two small bounded HTML requests per day;
- no added scheduler;
- no retrospective spam after outages or deployment;
- source disagreement is silent rather than guessed;
- a source outage on the exact trigger day may suppress that notice, which is
  preferred to publishing a stale cached deadline;
- a later official date revision becomes eligible on its newly calculated exact
  trigger date without bespoke migration logic.
