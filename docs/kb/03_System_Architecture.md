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
3. **Source collection** requests current data from approved official sources,
   reads event facts from local catalogs, and reads one small public CAMS JSON
   produced off-device by a daily GitHub Action.
4. **Normalization** converts source-specific responses into small, consistent
   records while preserving source, place, and time.
5. **Validation and relevance filtering** rejects stale, incomplete,
   out-of-area, or low-value records using explicit rules.
6. **Digest building** orders the remaining facts and formats one short
   message.
7. **Telegram delivery** sends the early message and stores its message ID.
8. **External update checks** run at 10:10–10:40 in five-minute steps. Three
   bounded checkpoints (10:10, 10:25 and 10:40) may accept a newer CAMS
   forecast until today's UTC cycle is accepted, compare only the remaining
   local day semantically, and send one compact reply only for a material
   change. Each
   process checks SafeBeach first, retains at most the best whole normalized
   partial response for this window, and attempts each event catalog at most
   once that day so later event facts are saved without seven repeat calls.
9. **Beach root** checks the Mayor channel during the initial SafeBeach window
   and again only on the first invocation of already scheduled operational
   windows. Verified beach or newer explicit Mayor bathing transitions create
   or refresh one standalone beach root; they never replace or delete the
   Morning Digest.
10. **Minimal state** keeps the local date, both Telegram message IDs,
   morning publication time, and cleanup result.
11. **Exit** ends every process; no collector or watcher remains active.

Externally scheduled operational checks compare current SafeBeach and AEMET
warning state with one small daily snapshot. Beach candidates use at most two
scheduled confirmations. Confirmed beach changes reply to the independently
maintained beach root; AEMET, CAMS and Meteosalud changes reply to the immutable
Morning Digest. Source failure preserves the last verified baseline and never
creates an all-clear message.

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
bounded JSON, retries transient sends under their delivery policy, and applies
bounded recovery to idempotent edits and pins.

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

One recoverable Telegram graph contains cameras, transport, durable places, and
recurring activities under a compact pinned root. The same existing
reconciliation machinery owns every logical message ID. Exact
`MESSAGE-NOT-FOUND` responses replace deleted bot-authored messages and bounded
passes rewrite affected forward and return links before success. Unchanged edits
are idempotent success; unrelated HTTP 400 errors fail closed without creating
replacement duplicates.

`state/pinned_guide.json` stores only the shared message graph plus bounded media
metadata for the two urban transport lines. The existing 05:00 transport sync
checks their official PDF links, the date-specific Bus Sigüenza airport result,
and the verified standard fare, then reconciles the complete guide graph. Its
narrow Let's Encrypt issuer recovery remains limited to the documented Bus
Sigüenza chain fault and preserves normal TLS and hostname verification.

A separate 09:02 `sync-guide` process reads Aqualider's public SimplyBook
`/v2/service/` and `/v2/provider/` JSON endpoints sequentially. It accepts only
the exact HTTPS host, bounded JSON and an internally reciprocal service/provider
schema. One compact `state/guide.json` stores bounded last-good normalized
guide-source snapshots, source-attempt markers, the reconciliation-success
day, and the seasonal-notice delivery marker; raw source responses are not
stored.
The first successful catalogue read is a silent baseline. A catalogue diff is
stored and logged but does not itself prove registration availability and does
not create a public programme alert.

The same 09:02 process reconciles the existing guide graph and records a
success marker only after card reconciliation. On 15 June and 15
September it may publish one next-day municipal-pool season notice from the fixed
calendar. New-message delivery retries only explicit Telegram rate limits;
ambiguous delivery is recorded rather than automatically resent. There is no
resident guide worker, database, browser, per-sport process, or per-service
availability polling.

### Unified 112/Previfoc watcher

One short-lived `check-112` command runs at minute `:19` of each hour. It is the only Telegram publication
boundary for CCE/Previfoc risk transitions.

Each invocation performs bounded reads of the public CCE active-emergencies
page, the current CCE text-readable PDF, and the tiny current-day Previfoc
zone-6 ArcGIS state. The CCE PDF is **not** conditional on a local AEMET rain/thunderstorm
warning because lower-Segura hydrological risk may originate upstream. AEMET
remains an independent source and is not re-requested by this watcher.

Adapters normalize observations first. The orchestrator merges equivalent
authority states, compares them with one small atomic prior-state file and
publishes at most one coherent transition. Source failure is unknown, never an
all-clear; it cannot erase a stronger last verified state. Raw HTML, ArcGIS
responses and PDFs are not archived. PDF bytes and extracted text remain
process-local and are discarded on exit.

## Operating model

- One 07:30 process plus up to seven short update checks in season
- Four or five seasonal operational beach checks, with five- and ten-minute
  confirmation invocations that access SafeBeach only while a candidate is
  pending; three warning-only AEMET checks per day
- Up to five short evening electricity attempts; success-only state makes
  later invocations no-ops after the first publication
- One daily 05:00 transport sync and one daily 09:02 guide/catalog sync; both
  are short-lived and reconcile the same pinned Telegram graph
- Optional lightweight operator listener with one idle Telegram long poll
- One event loop with bounded asynchronous I/O
- One direct immutable 07:30 collection; later checks create only compact
  semantic replies or refresh the separate beach root, never a second digest
- No webhook or public server
- No resident scheduler, source polling, or watcher; only bounded one-shot
  event refresh, digest, guide, electricity and operational-change commands
- Small local state
- No required database server, message broker, or worker service

## Failure boundaries

- **Source unavailable:** omit that source's contribution.
- **CAMS JSON unavailable:** use a covering last-good local JSON; otherwise
  omit air quality and pollen without blocking publication.
- **Guide catalogue unavailable or malformed:** keep the last-good normalized
  baseline, still reconcile static guide messages, and publish no catalogue
  change claim.
- **Stale or invalid data:** reject it; do not substitute a normal-looking
  default.
- **Partial collection:** build a digest only from independently valid facts.
- **No useful content:** send nothing.
- **Telegram unavailable:** use bounded recovery and avoid duplicate delivery.
- **Later invocation:** retry when no confirmed success was stored.

Each publication workflow holds its own local file lock. Morning lifecycle
state and electricity success state are separate small atomic JSON files. The
morning anchor is never deleted on new lifecycle days; a missing beach root is
recreated only after Telegram confirms its message is gone.

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
official poster when a documented OCR error is discovered. Their drop filters
apply only to poster-only rows; a same-dated text occurrence keeps its identity
and may inherit only missing bounded reviewed details. A non-exhibition date
range is never treated as proof of daily activity. Event places are compacted
before persistence and rendering, and prose or instructions remain unlinked
when they are not safe map locations.

The Mayor-channel event path reuses the existing bounded public-page request.
Besides its dedicated market, bathing and Fiestas de Barrio rules, it accepts
only a fresh invitation with a quoted title, explicit current date, valid
time and explicit place. It uses no AI, cache or additional request; ordinary
news and retrospective reports remain ineligible.

Termux runs the transport sync at 05:00, refreshes municipal and Agenda Guardamar
catalogs at 05:10 and 05:30, invokes the morning command at 07:30, and runs the
update command every five minutes from 10:10 through 10:40 in `Europe/Madrid`.
The first update invocation that acquires the daily state lock attempts each
event catalog once, independently of whether SafeBeach succeeds. These facts
are retained for later publications and do not alone trigger replacement. The
linked guide/catalog sync runs at 16:30. The electricity command runs at 20:30,
then after 5, 15 and 30 minutes, with a final 21:20 attempt. It publishes at most
once for the next local date.

An independent earthquake command runs at minute 55 of every hour. Each
invocation performs one bounded request to the official IGN GeoRSS endpoint,
parses at most 128 records with the standard library, filters them to magnitude
2.7 or greater within 10 km of Guardamar, and exits. Its first successful run
seeds existing qualifying events silently while keeping fresh lower-magnitude
records eligible for an IGN revision. Later qualifying events within a
six-hour recovery window are sent once. Events observed within the same
six-hour series share one Telegram message; later events and source revisions
edit it in place, with at most five events visible. A missing series message is
recreated. An explicit Telegram rejection remains eligible for the next hour;
an ambiguous network result is recorded as uncertain instead of risking an
automatic duplicate. The state keeps at most 256 normalized records for 14 days,
and the raw XML is never stored. The monitor uses a short-lived local lock so a
manual duplicate invocation cannot overlap it.

Code deployment is external to the application and operator-driven over private
Tailscale SSH. The operator reviews Git state, runs relevant tests, commits the
completed change, and restarts only an affected resident service; one-shot cron
commands use changed code on their next run. There is no GitHub Actions
promotion, `deploy` branch, self-update cron task, resident deployment agent,
or inbound public port. Secrets and runtime state remain local.

An independent GitHub Actions workflow performs a bounded OCI capacity search
at minutes 7, 22, 37, and 52. It is not an application deployment path and adds
no Android runtime dependency. Its immutable launch manifest is recovered from
the OCI Resource Manager Stack. Each run checks OCI state twice and can issue
at most one non-retried `LaunchInstance`; a non-terminated target always makes
the run a zero-create verifier. Strict Always Free ceilings fail closed.
Accepted targets are polled to RUNNING and verified through their primary VNIC.

After a device reboot, Android requires the first user unlock before Termux app
storage and its boot-started services become available to the remote operator.

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
- Fetch account-level guide catalogues once per source account and fan the
  normalized result into guide entities; do not poll once per activity.
- Keep the local earthquake monitor hourly and one-shot; it is informational,
  never a replacement for official emergency alerts.
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
### Morning lifecycle

The morning publication is an immutable anchor. Operational beach status has
an independent seasonal root, while material AEMET, CAMS and Meteosalud
changes reply to the morning anchor. The existing atomic JSON state stores
only message identifiers and compact baselines; no database, daemon or extra
cron is introduced.
