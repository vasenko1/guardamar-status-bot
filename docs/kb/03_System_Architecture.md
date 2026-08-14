# System Architecture

## Architecture goal

Use one small, understandable application that can collect official data,
build a deterministic Morning Digest, and deliver it through Telegram while
remaining reliable on a weak Android device.

This page defines responsibilities and boundaries. Detailed module layouts,
schemas, and library choices belong in later design work or ADRs.

## High-level flow

1. **Pre-morning event refreshes** update two small normalized catalogs at
   05:10 and 05:30, including a bounded rolling supplemental event window,
   then exit.
2. **External 07:30 trigger** starts one short-lived digest process.
3. **Source collection** requests current data from approved official sources
   and reads event facts from the local catalogs.
4. **Normalization** converts source-specific responses into small, consistent
   records while preserving source, place, and time.
5. **Validation and relevance filtering** rejects stale, incomplete,
   out-of-area, or low-value records using explicit rules.
6. **Digest building** orders the remaining facts and formats one short
   message.
7. **Telegram delivery** sends the early message and stores its message ID.
8. **External beach checks** run at 10:10–10:40 in five-minute steps. Each
   process checks SafeBeach first, retains at most the best whole normalized
   partial response for this window, and attempts each event catalog at most
   once that day so later event facts are saved without seven repeat calls.
9. **Conditional replacement** checks the Mayor channel once after SafeBeach
   succeeds or its retry window expires. A verified update permits one fresh
   full collection, delivery of the replacement, then deletion of the earlier
   message.
10. **Minimal state** keeps the local date, both Telegram message IDs,
   morning publication time, and cleanup result.
11. **Exit** ends every process; no collector or watcher remains active.

After the later full digest is settled, externally scheduled operational
checks compare current SafeBeach and AEMET warning state with one small daily
snapshot. Beach candidates use at most two scheduled confirmations. Confirmed
changes are sent as replies to the current full digest; older updates remain
unchanged.

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

Traffic documents normalize into independent mobility measures rather than one
document-wide type. A measure has an action, location and validity interval,
plus only relevant hours, affected users, exceptions, alternative route and
destinations.

### Telegram boundary

Sends one outbound digest through the Telegram Bot API. The publication
runtime does not receive Telegram updates or expose a webhook. An optional
separate listener receives only private message updates for the allowlisted
`/preview` operator command. Telegram details remain separate from source and
digest rules. One shared standard-library client handles send, delete, and
`getUpdates`; it accepts only HTTPS responses from `api.telegram.org`, requires
bounded JSON, and retries only transient send failures.

### Shared runtime

Provides only genuine cross-cutting needs:

- configuration and secrets loading;
- lightweight HTTP access;
- concise logging;
- small persistent state;
- startup and graceful shutdown.

### Next-day electricity prices

One independent evening command requests official ESIOS indicator `1001` for
the next Madrid date, selects `Península`, requires all 24 hourly values,
formats one two-column PVPC table, and exits. On the first publication it sends
a short explanation, stores its Telegram message ID, and sends the table as a
reply; later daily tables reply to the same explanation without repeating it.
It atomically
stores one complete normalized target-day price snapshot plus the published
target date and persistent explanation ID. Public output is built from that
snapshot;
the personal ESIOS token and raw response are never stored. It reuses only
Telegram and minimal file state; it does not depend on Morning Digest internals.

### Linked pinned guide

One manual one-shot workflow maintains a static set of camera and transport
messages. It reconciles detailed messages, the navigator and compact root into
a bidirectional link graph, then pins the root. Exact missing-message responses
replace deleted bot-authored messages and bounded passes rewrite every affected
forward and return link before success. Unchanged-message responses are treated
as idempotent success; other HTTP 400 errors fail closed without duplicates. A
small independent atomic state stores only chat and message IDs. It has no
schedule, source collection, media conversion, or dependency on Morning Digest
state.

## Operating model

- One 07:30 process plus up to seven short update checks in season
- Four or five seasonal operational beach checks, with five- and ten-minute
  confirmation invocations that access SafeBeach only while a candidate is
  pending; three warning-only AEMET checks per day
- Up to five short evening electricity attempts; success-only state makes
  later invocations no-ops after the first publication
- One optional manual pinned-guide publication or update
- Optional lightweight operator listener with one idle Telegram long poll
- One event loop with bounded asynchronous I/O
- One direct 07:30 collection; one later full collection only after an update
- No webhook or public server
- No resident scheduler, source polling, or watcher; only bounded one-shot
  event refresh, digest, electricity and operational-change commands
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

Each publication workflow holds its own local file lock. Morning replacement
state and electricity success state are separate small atomic JSON files. The
replacement is sent and recorded before deletion of the morning message; a
later invocation retries only failed cleanup.

The electricity workflow checks its success state before any ESIOS work. A
complete normalized target-day snapshot is reused by later attempts, including
recovery after Telegram delivery failure. A missing, wrong-date, or invalid
snapshot is never published and is replaced only after one complete validated
API response. Electricity preview and publication share the same non-blocking
local lock, preventing concurrent duplicate source requests.

The AEMET adapter retries only transient transport, rate-limit, server, or
expired-link failures. It repeats the complete metadata-plus-product request,
uses short exponential delays or the server's `Retry-After`, and never retries
permanent or invalid-data failures. The 05:30 Agenda Guardamar refresh reads
event details with at most three concurrent same-host requests and saves a
small atomic catalog. The morning run translates only today's bounded titles.
If the mandatory forecast remains
unavailable during replacement, the same-day prepared AEMET snapshot supplies
the weather blocks alongside the newly verified beach information.

The SafeBeach adapter performs one bounded HTML request per invocation and
does not add an internal retry or response cache. The external five-minute invocations
provide recovery. It accepts only a page carrying today's local calendar date
and independently valid, timestamped beach records. It returns every valid
record among the six known Guardamar zones in fixed product order. Conflicting,
duplicate, or malformed records are omitted. Update checks before 10:40
continue until all six zones are present. The 10:40 attempt may use any
non-empty valid set so a
persistently missing record does not suppress all beach information.
Separate attempts never merge beach records. The daily publication state keeps
only the whole response with the most verified beaches, breaking ties in favor
of the later observation. A valid current 10:40 response remains authoritative;
the attempt reuses the stored candidate only after a timeout or invalid final
response. Candidates older than the bounded window or from another date are
ignored and successful replacement removes the temporary record.

Mayor, Policía Local, and municipal-agenda transports accept only their exact
official HTTPS hosts, expected content types, and bounded responses. Gemini
uses the same fail-closed protocol checks. One OpenRouter request with a
pinned non-Google model may follow a Gemini failure, using the identical
bounded public input and JSON schema. Both return structured diagnostics;
provider response text is never exposed. A corrupt event catalog is ignored.
The official municipal HTML text is primary; a changed MUPI is supplementary.
Its second structured reading receives only the image, never the first result,
and deterministic intersection keeps agreeing facts. A MUPI failure cannot
erase valid text facts. Narrow corrections may be pinned to one reviewed
official poster when a documented OCR error is discovered.

The Mayor-channel event path reuses the existing bounded public-page request.
Besides its dedicated market, bathing and Fiestas de Barrio rules, it accepts
only a fresh invitation with a quoted title, explicit current date, valid
time and explicit place. It uses no AI, cache or additional request; ordinary
news and retrospective reports remain ineligible.

Termux refreshes municipal and Agenda Guardamar catalogs at 05:10 and 05:30,
invokes the morning command at 07:30, and runs the update command every five
minutes from 10:10 through 10:40 in `Europe/Madrid`.
The first update invocation that acquires the daily state lock attempts each
event catalog once, independently of whether SafeBeach succeeds. These facts
are retained for later publications and do not alone trigger replacement.
The electricity command runs at 20:30, then after 5, 15 and 30 minutes, with a
final 21:20 attempt. It publishes at most once for the next local date.

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

Telegram `sendMessage` has no idempotency key. A lost success response before
the message ID is stored remains an unavoidable duplicate edge.

## Architecture guardrails

- Prefer structured official feeds or APIs over page scraping.
- Collect sources only in bounded scheduled runs; never continuously.
- Bound network time, retries, response sizes, concurrency, and stored history.
- Keep domain rules independent from transport and source formats.
- Do not add a generic cache layer for municipal or event information. ADR
  0033 permits only a bounded Todo Cultura cursor, candidate index and covered
  dates inside the existing normalized catalog; no raw response is cached.
- ADRs 0012 and 0028 permit two bounded normalized event catalogs. When the
  official page advances early, a new poster
  is merged with still-relevant prior-poster events for a seven-day transition
  window; expired facts are not retained.
- Add abstractions only for current, demonstrated needs.
- Keep Gemini and its single OpenRouter fallback isolated to accepted bounded
  municipal extraction and title-only translation; do not add general AI,
  provider chains, microservices, webhooks, or heavy background infrastructure.
