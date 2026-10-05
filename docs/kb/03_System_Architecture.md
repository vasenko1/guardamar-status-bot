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
8. **External update checks** run at 10:10–10:40 in five-minute steps for the
   beach lifecycle. CAMS uses only the 10:40 invocation for its early late-cycle
   check; later recovery uses only the first invocation of already scheduled
   operational windows until today's UTC cycle is accepted, comparing the remaining
   local day semantically, and send one compact reply only for a material
   change. From 1 June through 15 October, every update invocation also
   checks SafeBeach. The first valid current response with at least one flag
   creates the separate beach root immediately; later valid responses edit
   that same root through 10:40. Event catalogs are attempted at most once
   that day so later event facts are saved without seven repeat calls.
9. **Beach root** is independent of Morning Digest content. Its SafeBeach
   snapshot is live only during 10:10–10:40; after that it becomes the
   operational baseline and confirmed SafeBeach changes are separate replies.
   A missing initial root may still be created by the first later confirmed
   status. Newer explicit Mayor bathing restrictions remain an independent
   safety signal and may refresh the root.
10. **Minimal state** keeps the local date, Morning Digest and beach-root
   message IDs, publication time, and compact semantic baselines.
11. **Exit** ends every process; no collector or watcher remains active.

Externally scheduled operational checks keep SafeBeach, AEMET and late
environment work as independent bounded lifecycles. Beach candidates use at
most two scheduled confirmations. AEMET performs CAP-only checks hourly at
`:51` from 07:51 through 23:51, while SafeBeach and CAMS/Meteosalud retain their
existing windows. Confirmed beach changes reply to the independently maintained
beach root; AEMET, CAMS and Meteosalud changes reply to the immutable Morning
Digest. Source failure preserves the last verified baseline and never creates
an all-clear message.

If nothing trustworthy and useful remains after filtering, the run may produce
no message.

## Runtime lifecycle inventory

| Lifecycle | Trigger | Resident-facing effect |
| --- | --- | --- |
| Morning Digest | 07:30 daily | One immutable daily message; pharmacy, events, holidays/markets, AEMET weather/sea/UV, locally computed sunrise/sunset, CAMS/Meteosalud baseline and fresh CCE hydrology contribute here without becoming separate morning processes. |
| SUMA tax reminders | 08:05 daily one-shot | Independent one-shot cross-checks two official HTML pages and may publish at most one exact-date tax/debit reminder; separate state, no daemon or resident scheduler. |
| SafeBeach + Mayor bathing status | 10:10–10:40 in season, then bounded operational checks | Separate daily beach root, live early edits, later confirmed replies; explicit Mayor bathing restrictions remain an independent safety signal. |
| AEMET operational warnings | Hourly at `:51` from 07:51 through 23:51 | One bounded CAP-only check; material warning changes reply to the Morning Digest. |
| CAMS / Meteosalud late environment | 10:40 CAMS early check plus existing operational recovery; Meteosalud on operational checkpoints | Material air-quality, pollen, heat or cold changes reply to the Morning Digest. |
| CCE / Previfoc emergency risks | Hourly at `:19` | CCE/Segura hydrological transitions remain immediate. Previfoc is still observed hourly, but changes seen before 07:00 are kept silent and only the still-current delta may publish on the first run after 07:00; fresh active hydrology may also appear in the next Morning Digest. |
| IGN earthquakes | Hourly at `:55` | Standalone/series notice for new events at M1.8+ within 20 km. |
| Hidraqua network incidents | Every 30 minutes | Standalone notice for a new confirmed water-network event ID. |
| TomTom road/lane closures | Hourly at `:37` | One bounded Guardamar snapshot; strict provider-ID reconciliation preserves the physical closure lifecycle before two-snapshot end confirmation, so source ID churn cannot create false reopen/new-close messages. |
| Transport | 05:00 sync, 08:42 notification | Owns and repairs the dynamic airport, Alicante, Elche, Orihuela and Zenia Boulevard cards; reconciles transport state and publishes accepted schedule/service/fare changes. |
| Linked guide + courses | 09:02 sync; course notices 09:42/11:42; two seasonal 19:45 checks | Reconciles guide-owned cards while preserving existing transport-owned cards in the shared Telegram graph; may send pool/Zona Azul seasonal notices and publishes accepted course/programme changes, including grouped fresh-source registration boundaries for tomorrow. |
| One-off event access | 12:47 daily, recovery 13:47 | ADRs 0090–0092 define the event-centric v2 runtime: one text root per event, source-proven access options, and strict threaded replies. The first implementation enables only CONVEGA and remains inert on legacy v1 state until the operator runs the explicit migration. |
| Electricity | 20:30/20:35/20:45/21:00/21:20 attempts | One next-day PVPC table reply after the first complete official dataset. |
| Resident-impact news | 11:11/15:11/18:11 daily | One bounded EWN discovery read; one batch AI classification; at most one first-party-grounded Russian Telegram note. |
| Next-day events | Sunday–Thursday 19:25, recovery 20:25 | Reads only fresh same-day local event catalogs; one editorial unit may be rich with one official image URL, while multiple units stay in one text planning post. The recovery reuses the same state, so a confirmed or uncertain first delivery cannot duplicate. No evening source fetch or AI. |
| Weekend digest | Friday 19:15, retry 20:15 | One weekend-events digest when verified events exist. |
| Pharmacy catalogue | Sunday 05:50 | Source refresh only; consumed by Morning Digest. |
| Bathing-zone control | 19:35 daily 01 Jun–15 Sep; PDF only for a new report identity | A fresh first or later official weekly report produces one 🧪 group notice with actual sample dates, laboratory water quality by beach and only non-excellent visual water/sand exceptions; stale first report becomes baseline. |
| Event/translation/AEMET preparation | Pre-morning one-shots | Source preparation only; no independent public notification. |
| Municipal Wi-Fi source watch | Inside guide sync | A changed official municipal PDF is parsed fail-closed; only a semantic point/SSID/password change updates the existing card and, after reconciliation, produces one public group notice linking to that card. |
| OCI capacity search | Independent GitHub Actions | Infrastructure only; no Telegram city publication. |

## Accepted sports-event target architecture

ADR 0100 accepts a dedicated sports presentation layer on the existing event
pipeline. It is **implementation pending** until the staged rollout completes;
the runtime lifecycle inventory above continues to describe current production.

The accepted target keeps one normalized `Event` stream and adds one optional
source-owned `sport` fact. Sports do not get a second database, collector,
scheduler or registration lifecycle.

Once implemented:

- `Завтра в Гуардамаре` and Friday `Афиша выходных` include a separate
  sports subsection;
- one standalone local-snapshot-only `Спортивные мероприятия сегодня`
  publication serves the current-day reminder/correction;
- Morning omits sport after that current-day publication is operational;
- advance registration/reservation/ticket information continues through the
  event-access lifecycle in ADRs 0090-0092;
- source-specific authority and locality checks happen before generic Event
  merge; no global sports ownership/precedence framework is introduced.

Sports copy must preserve source-backed competition context such as league,
group, round/stage, category, schedule and venue when available. Explicit
same-day cancellation/postponement is a correction, not a silent omission.

Each implementation slice has a verification gate. A later slice starts only
after focused tests, the full suite and architecture/code review leave no
unresolved defect for the current stage.

## Logical areas

### Morning Digest

Owns the daily workflow and digest-specific rules. It can use independent
source adapters but must not depend on source-specific formats after
normalization.

### Source adapters

Each factual adapter represents one approved official or first-party source. It
is responsible for accessing and interpreting that source, including its
freshness indicators. A failed adapter must not block unrelated adapters.

ADR 0087 adds one discovery-only adapter for EWN `News from Spain`. It may
surface candidates and extract links, but factual publication still requires a
separate approved first-party source adapter path.

### Digest policy

Defines deterministic rules for:

- freshness;
- geographic and date relevance;
- inclusion and omission;
- priority;
- message length and section order.

Core selection and formatting are deterministic. The former Policía Local
traffic adapter is retired from runtime because the reviewed page did not
provide a dependable current traffic feed; no daily police request or traffic
AI fallback remains.

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
authority states and compares them with one small atomic prior-state file.
CCE/hydrological transitions remain eligible immediately at every hourly run.
Previfoc is a daily prevention product: observations before 07:00 Europe/Madrid
are stored but neither rendered nor acknowledged as published. The first run at
or after 07:00 publishes only a still-current Previfoc delta; an overnight
intermediate value that reverted before morning produces no stale notice. No
second scheduler, queue or pending-state field is added. Source failure is
unknown, never an all-clear; it cannot erase a stronger last verified state.
Raw HTML, ArcGIS responses and PDFs are not archived. PDF bytes and extracted
text remain process-local and are discarded on exit.

## Operating model

- One 07:30 process plus up to seven short update checks in season
- Four or five seasonal operational beach checks, with five- and ten-minute
  confirmation invocations that access SafeBeach only while a candidate is
  pending; three warning-only AEMET checks per day
- One local-only 19:25 next-day event one-shot Sunday–Thursday; no source request or AI call
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
  event refresh, digest, guide, electricity, resident-news and operational-change commands
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

Each publication workflow holds its own local file lock. Morning lifecycle,
next-day event delivery, and electricity success state are separate small atomic
JSON files. The next-day event marker persists `uncertain` before its new send,
so an ambiguous Telegram result cannot be automatically resent as a duplicate.
The
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
small atomic catalog. Pre-morning event preparation translates bounded cache
misses for today and tomorrow, so the evening planning one-shot never calls AI.
If the mandatory forecast is unavailable during Morning Digest publication or
an explicit `refresh-current`, the same-day prepared AEMET snapshot supplies
the weather blocks independently of the separate SafeBeach lifecycle.

The SafeBeach adapter performs one bounded HTML request per invocation and
does not add an internal retry or response cache. Scheduled SafeBeach requests
are allowed only from 1 June through 15 October; from 16 October through
31 May there are none. October uses the reduced four-window SafeBeach cadence
while AEMET retains its existing year-round warning schedule. Morning Digest collection never calls SafeBeach.
The 10:10–10:40 update invocations request it every five minutes inside the
annual window. Any valid current response with at least one known beach flag
is publishable immediately: the first creates the daily beach root and later
responses edit that root in place. Separate responses are never merged; every
edit represents one whole current source response, so missing records do not
survive as synthetic current flags.

After 10:40, the existing root supplies the operational baseline. The later
monitor follows its bounded cron cadence, confirms flag/jellyfish transitions,
and publishes them as replies instead of rewriting the SafeBeach snapshot in
the root. If no root existed by 10:40, a first later confirmed status may
create it as recovery. The adapter accepts only a page carrying today's local
calendar date and independently valid, timestamped records among the six known
Guardamar zones; conflicting, duplicate, malformed, inactive or ended records
are omitted.

Mayor and municipal-agenda transports accept only their exact official HTTPS
hosts, expected content types, and bounded responses. Gemini uses the same
fail-closed protocol checks. ADR 0085 permits one direct Groq GPT-OSS 120B
request only after an eligible Gemini provider failure and only for the four
approved bounded text operations. Factual event extraction and image reading
never route to Groq. Both clients return structured diagnostics; provider
response text is never exposed. A corrupt event catalog is ignored.
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
catalogs at 05:10 and 05:30, and invokes the Morning Digest process at 07:30.
SUMA is a separate one-shot at 08:05 so its rare tax reminder and bounded source
reads do not cluster with the briefing or neighboring scheduled work. The update
command runs every five minutes from 10:10 through 10:40 in `Europe/Madrid`.
The first update invocation that acquires the daily state lock attempts each
event catalog once, independently of whether SafeBeach succeeds. These facts
are retained for later publications and do not alone trigger replacement. The
linked guide/catalog sync runs at 09:02. The electricity command runs at 20:30,
then after 5, 15 and 30 minutes, with a final 21:20 attempt. It publishes at most
once for the next local date.

An independent earthquake command runs at minute 55 of every hour. Each
invocation performs one bounded request to the official IGN GeoRSS endpoint,
parses at most 128 records with the standard library, filters them to magnitude
1.8 or greater within 20 km of Guardamar, and exits. Its first successful run
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
no Android runtime dependency. The primary A1 launch intent remains
1 OCPU / 6 GB. After two complete OCI-state checks, one best-effort Compute
Capacity Report may select the otherwise identical 1 OCPU / 2 GB fallback only
when 6 GB is explicitly out of host capacity and 2 GB is explicitly available.
Any unavailable or inconclusive report preserves the 6 GB path. Each run can
issue at most one non-retried `LaunchInstance`; a non-terminated target always
makes the run a zero-create verifier. Strict Always Free ceilings fail closed.
Accepted 6 GB or 2 GB targets are polled to RUNNING and verified through their
primary VNIC.

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
- Keep Gemini primary for approved municipal/event AI work. Permit direct Groq
  GPT-OSS 120B fallback only for the four bounded text operations in ADR 0085;
  factual extraction and image reading remain Gemini-only. Do not add general
  AI, provider chains, microservices, webhooks, or heavy background
  infrastructure.
### Morning lifecycle

The morning publication is an immutable anchor. SUMA is independent of that
lifecycle and runs once at 08:05 through its own external one-shot. It keeps its
own source adapter and atomic state, never contributes to or edits the Morning
Digest, and failures in either workflow cannot mask the other. Its two HTML reads
are sequential and bounded, and no raw page is retained.

Operational beach status has an independent seasonal root, while material AEMET,
CAMS and Meteosalud changes reply to the morning anchor. The existing atomic JSON
state stores only message identifiers and compact baselines; no database, daemon
or resident scheduler is introduced.

## Product-award one-shot

Product awards are an independent low-frequency workflow. One daily Termux
invocation reads the existing small atomic state first and exits before network
access while cooldown is active or the reviewed registry is exhausted.

A due run walks categories from the stored cursor and preserves authority
priority plus source-native rank. The retailer of the last confirmed
`published_events` entry is derived from the current registry when possible;
no retailer field is added to state.

Selection uses one bounded scan. The first valid category winner from the same
retailer as the previous post is held only as an in-memory fallback while later
categories are checked. The first valid category winner from a different
retailer is preferred. If none exists, the stored same-retailer fallback
publishes. A valid candidate always ends ranking inside its own category, so
retailer preference never demotes to a lower-ranked product.

Exact award evidence, exact current retailer identity and current price remain
publication requirements. Product photography is the normal presentation under
ADR 0096. Each candidate may expose a small reviewed hierarchy of exact official
image sources; producer/brand or official media assets are preferred where
practical, followed by award-organizer or exact retailer images. Consum still
prefers working official `media[]` over stale base `productData.imageURL`;
ALDI distinguishes an explicit product-page error from a healthy page whose
embedded product contract has drifted. Carrefour and DIA retain their
production-proven exact server-rendered retail verification path.

Delivery remains Rich Message first. The bot tries the first reviewed exact
image source remotely; after explicit remote-media rejection it may use the
existing bounded local upload recovery. A deterministic failure may advance to
the next reviewed exact image source. Only after all reviewed image paths are
exhausted may the same verified article degrade to a no-image Rich Message.
Ambiguous delivery never falls through to another send.

Confirmed delivery alone advances the existing event/selection history,
delivery day and category cursor. No retailer ledger, state migration, second
selector pass, persistent candidate cache, browser, AI service, queue or new
scheduler is introduced. A due run that publishes nothing records one concise
final log reason.

The reviewed registry itself is maintained separately. ADR 0095 removes
innovation-only Producto del Año entries and restores previously proven
quality-first OCU/MAPA categories. Retailer diversity in runtime cannot
compensate for source-policy weakness, so Mercadona and Lidl remain research
targets rather than quota-filling registry entries.

### One-off event access

ADR 0089 is the legacy CONVEGA registration-only state contract. ADRs 0090-0092
define the implemented event-centric v2 runtime: registration, reservation and
paid/free ticket access share one source-owned lifecycle, one real event owns
one Telegram root, and source-proven sessions are child options. The first
rollout activates only CONVEGA, uses text roots/replies, and requires an explicit
operator migration from v1 before normal scheduled runs can use v2.

Existing source refreshers remain responsible for network collection and small
normalized snapshots. Event-access publication consumes only pure local
source-specific projections grouped as fresh per-source batches; a stale source
is omitted independently and cannot suppress fresh unrelated sources. Do not
turn the notification runner into a second multi-source refresh subsystem.

Persistent lifecycle state is event-centric. State v2 keeps one bounded
`records[record_id]` entry containing semantic option state,
`audience_known`, one optional `root_message_id`, and record-local trigger
history. One global uncertain reservation protects exactly one outbound record
candidate. The planner processes one record at a time and commits only that
record after confirmed delivery. State migration is an explicit locked
operator action, never a hidden cron side effect.

The global `Event` model remains presentation-only for Morning/Tomorrow/Weekend
and is not replaced by a second general event model. Access truth remains
source-owned and fail-closed. Proactive access uses each source's reviewed
freshness contract; Morning may still consume last-good Event data under its
separate presentation rules.

The 2026-10-03 production probe opened the core implementation gate while
keeping source rollout capability-gated. CONVEGA is the reference-ready source.
Municipal/Turismo may expose only explicit reviewed one-off access facts.
Agenda Guardamar, Biblioteca, FACV, Pesca CV and AM Guardamar remain disabled
for proactive access until their documented identity/action gaps are closed.
This staged enablement avoids both a generic event scanner and speculative
source abstractions.

The first state-v2 rollout is intentionally smaller than the eventual
multi-source shape: CONVEGA only, text roots/replies only, no generic ownership
resolver and no photo transaction. CONVEGA proactive access requires a
same-day, non-future observation no more than 90 minutes old; a preserved older
last-good snapshot may still serve ordinary event presentation but cannot drive
a current access claim.
