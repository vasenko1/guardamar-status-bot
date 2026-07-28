# System Architecture

## Architecture goal

Use one small, understandable application that can collect official data,
build a deterministic Morning Digest, and deliver it through Telegram while
remaining reliable on a weak Android device.

This page defines responsibilities and boundaries. Detailed module layouts,
schemas, and library choices belong in later design work or ADRs.

## High-level flow

1. **External 10:02 trigger** starts one short-lived digest process.
2. **Source collection** requests current data from approved official sources.
3. **Normalization** converts source-specific responses into small, consistent
   records while preserving source, place, and time.
4. **Validation and relevance filtering** rejects stale, incomplete,
   out-of-area, or low-value records using explicit rules.
5. **Digest building** orders the remaining facts and formats one short
   message.
6. **Telegram delivery** sends the message.
7. **Success state** atomically saves only the successfully published local
   date.
8. **Exit** ends the process; no collector or watcher remains active.

If nothing trustworthy and useful remains after filtering, the run may produce
no message.

## Logical areas

### Morning Digest

Owns the daily workflow and digest-specific rules. It can use independent
source adapters but must not depend on source-specific formats after
normalization.

### Source adapters

Each adapter represents one approved official source. It is responsible for
accessing and interpreting that source, including its freshness indicators.
A failed adapter must not block unrelated adapters.

### Digest policy

Defines deterministic rules for:

- freshness;
- geographic and date relevance;
- inclusion and omission;
- priority;
- message length and section order.

Core selection and formatting are deterministic. The optional Policía Local
fallback may ask Gemini for structured translation of an unknown official
notice, but application validation—not the model—decides whether it is safe to
include.

### Telegram boundary

Sends one outbound digest through the Telegram Bot API. The publication
runtime does not receive Telegram updates or expose a webhook. An optional
separate listener receives only private message updates for the allowlisted
`/preview` operator command. Telegram details remain separate from source and
digest rules.

### Shared runtime

Provides only genuine cross-cutting needs:

- configuration and secrets loading;
- lightweight HTTP access;
- concise logging;
- small persistent state;
- startup and graceful shutdown.

### Future Feature

One isolated feature slot is reserved. It may reuse shared runtime facilities,
but it must not depend on Morning Digest internals or expand shared components
speculatively. Its architecture is defined only after the feature is approved.

## Operating model

- One short-lived Python process per local day
- Optional lightweight operator listener with one idle Telegram long poll
- One event loop with bounded asynchronous I/O
- One direct collection pass during the 10:02 execution
- No webhook or public server
- No resident scheduler, source polling, watcher, or synchronization job
- Small local state
- No required database server, message broker, or worker service

## Failure boundaries

- **Source unavailable:** omit that source's contribution.
- **Stale or invalid data:** reject it; do not substitute a normal-looking
  default.
- **Partial collection:** build a digest only from independently valid facts.
- **No useful content:** send nothing.
- **Telegram unavailable:** use bounded recovery and avoid duplicate delivery.
- **Later invocation:** retry when no confirmed success was stored.

The process holds a local file lock during its run to prevent overlapping
invocations. It checks the last successfully published date before collection.
After Telegram confirms delivery, it atomically writes only that local date.
Collection or delivery failure writes no publication state.

The external Termux scheduling mechanism invokes the command at 10:02 in
`Europe/Madrid`. Scheduling is deployment responsibility, not application
runtime behavior.

Deployment is also external to the application. GitHub Actions promotes a
`main` commit to the `deploy` branch only after the complete test suite passes.
A short Termux cron job checks that branch once at 04:00 before the morning run,
accepts fast-forward updates only, validates them on the phone, and restarts
the optional preview listener. Secrets and runtime state remain local.

The optional `listen` process is independent of publication. It accepts only
fresh `/preview` commands in private chats from configured user IDs, fetches
the same sources on demand, replies privately, and writes no publication
state. It uses no webhook, framework, update-offset file, or additional
dependency.

Telegram `sendMessage` has no idempotency key. If Telegram accepts a message
but the response is lost before the success date is stored, a later invocation
cannot distinguish that outcome from failure. This is the unavoidable edge of
the required success-only state model.

## Architecture guardrails

- Prefer structured official feeds or APIs over page scraping.
- Collect every source directly once; do not continuously refresh information.
- Bound network time, retries, response sizes, concurrency, and stored history.
- Keep domain rules independent from transport and source formats.
- Do not add a cache layer for municipal or event information.
- ADR 0012 permits one bounded monthly municipal-agenda snapshot as the only
  event-cache exception. It is refreshed atomically and expires with its
  covered period.
- Add abstractions only for current, demonstrated needs.
- Keep Gemini isolated to the accepted traffic fallback; do not add general AI,
  microservices, webhooks, or heavy background infrastructure.
