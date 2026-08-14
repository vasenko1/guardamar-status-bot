# Runtime Constraints

## Target environment

The production target is Termux on an Android device with:

- limited RAM and CPU;
- limited battery capacity;
- unstable or intermittent mobile internet;
- storage that should not grow without bounds;
- Android process suspension or termination;
- no assumption of a fixed public address or always-on server.

Development on a desktop must not introduce assumptions that fail in Termux.

## Runtime requirements

The publication process must:

- start quickly;
- terminate after each morning or update-check run;
- run as one short-lived lightweight process;
- use outbound Telegram calls only;
- perform network work asynchronously and with explicit timeouts;
- bound retries, concurrency, response sizes, queues, caches, and logs;
- tolerate individual source failures;
- allow a later invocation to retry when no success was recorded;
- keep persistent state small and local;
- avoid duplicate digest delivery after uncertain failures where practical.

The electricity process follows the same one-shot limits. It stores one
published date and one bounded normalized target-day snapshot, requires a
complete 24-hour response, and never waits in memory for ESIOS to publish later
data.

The optional operator listener may keep one bounded Telegram `getUpdates`
long poll solely for allowlisted private `/preview`. It must not schedule
publication, poll data sources until a command arrives, use a webhook, or
persist update history.

One short daily deployment check may fetch the tested GitHub `deploy` branch.
It must exit immediately when no update exists and must not become a resident
deployment agent or self-hosted CI runner.

The linked pinned guide uses explicit one-shot operator commands plus one short
daily urban-timetable synchronization. It may store one small message graph,
two current and two previous timetable PNGs, and bounded source metadata. PDF
rendering is allowed only after a stable changed official one-page document;
one strict normalized airport schedule and fare snapshot is also allowed.
Fare text extraction is allowed only after a stable changed official tariff
PDF. One bounded in-memory HTTPS intermediate-certificate recovery is allowed
only for the documented Bus Sigüenza missing-issuer fault; it must not disable
TLS verification or persist certificates. No browser, OCR, resident collector,
or background process is allowed.

## Resource policy

### CPU and battery

- Prepare compact event translations before publication and one normalized
  AEMET snapshot at 07:15; the 07:30 process reuses them. In season, allow
  only seven quick SafeBeach checks
  from 10:10 through 10:40 and at most one later full recollection.
- Leave exact timing to a lightweight external Termux scheduler.
- Install the operational-monitor cron rows by merging them with the existing
  crontab; never replace unrelated jobs owned by another bot.
- Avoid continuous parsing, transformation, or monitoring.
- Do not optimize speculatively, but reject designs with obvious background
  cost.

### Memory

- Process small responses and compact records.
- Do not retain full source histories in memory.
- Limit concurrency to the small number of approved sources.
- Avoid heavy frameworks and model runtimes.

### Network

- Assume requests can time out, disconnect, or return incomplete data.
- Make only the bounded requests required by scheduled collection, the morning
  collection, or an authorized on-demand preview.
- Reuse connections when simple and safe.
- Never retry indefinitely.
- AEMET recovery is bounded inside the adapter: three attempts for the
  mandatory forecast and two for each optional product, with short exponential
  delays or a server-provided `Retry-After` only when it fits the runtime
  budget.
- SafeBeach uses one bounded request per invocation. Do not add an inner retry,
  raw-response cache, cookies, or browser execution; the external five-minute
  checks already provide seasonal recovery. The daily publication state may
  retain only one small normalized whole partial response until the 10:40
  fallback. Its bounded HTML limit is 512 KiB.
- Later-day beach monitoring uses four or five primary seasonal checks. A
  five-minute confirmation request occurs only for a candidate change; one
  final request is allowed only when that confirmation reveals a different
  explicit state. Later AEMET checks request only the CAP warning product every
  four hours and share delivery with beach changes when their windows overlap.
- The 05:30 Agenda Guardamar refresh may inspect at most twelve same-host
  detail links with no more than three requests in flight. The 05:10 municipal
  refresh makes one HTML request and downloads MUPI only after its official
  URL changes. Neither stores downloaded pages or media. Today's bounded title
  set is translated only by the 06:00/06:30/07:00 preparation commands and
  stored in a bounded atomic cache. The 07:30 digest never calls Gemini.
- The 05:10 municipal refresh may read one Todo Cultura metadata page and one
  batch of at most three selected details. It keeps a five-minute cursor
  overlap, at most 100 lightweight candidates and 45 covered dates. Unchanged
  covered dates cause no full-detail or LLM work. The 10:10–10:40 invocations
  attempt each event catalog at most once per local day.
- Telegram operations share one bounded JSON client restricted to the official
  API host. Sends retain their workflow-specific delivery policy. Idempotent
  known-message edits and pins retry transient failures at most twice and
  honor only server delays that fit a 60-second per-wait bound.
- Electricity checks confirmed publication before any source access. The first
  complete ESIOS response for a target date is atomically normalized to one
  private local snapshot; later invocations reuse it instead of repeating the
  API request. Preview and publication share one non-blocking local lock. No
  raw response or token is stored. The publication marker also retains one
  Telegram message ID for the persistent PVPC explanation anchor.
- Mayor, Policía Local, municipal-agenda, Gemini, and the single OpenRouter
  fallback enforce exact HTTPS hosts, expected MIME types, and existing
  response-size limits. One secondary LLM request may follow a Gemini failure;
  neither provider retries inside this layer.
- Explicit Mayor-channel events reuse the existing bounded morning page read;
  they add no request, model call, raw-response cache or background process.
- Do not make digest delivery depend on every source succeeding.

### Storage

- Store configuration, minimal daily replacement state, the prepared AEMET
  snapshot from ADR 0029, and the two bounded normalized event
  catalogs accepted in ADRs 0012 and 0028. The municipal catalog may retain
  unexpired prior-poster events
  for at most the next seven days during a month transition.
- Store at most one complete normalized ESIOS target day with its official
  indicator and geographic scope, separately from the electricity publication
  marker. Replace it only after a complete validated response for another day.
- Keep logs rotated or otherwise bounded.
- Keep at most the current and previous accepted urban-timetable PNG for each
  municipal line. Temporary PDFs and candidate images are removed before the
  one-shot process exits.
- Keep one current and one previous normalized airport schedule/fare snapshot.
  Store no raw Bus Sigüenza HTML or PDF.
- Do not archive raw responses by default.
- Do not cache raw source responses or municipal information. Only normalized
  source-language event facts, bounded provenance, and the incremental Todo
  Cultura metadata allowed by ADR 0033 may enter the two event catalogs.
- Use one small atomic JSON file; SQLite is unnecessary for the MVP.

## Preferred technology direction

- Python available in Termux
- Python `tzdata` package because some Termux builds do not expose the Android
  timezone database to `zoneinfo`
- Termux `poppler` utilities only for changed one-page municipal timetable PDFs
  and changed Bus Sigüenza tariff PDFs
- `asyncio` for bounded network concurrency
- standard-library HTTP for the current small source and delivery set
- aiogram or aiohttp only if a later requirement clearly justifies them
- Python standard-library facilities where they are sufficient
- one atomic JSON file for daily Telegram message IDs and cleanup state

These are directions, not permission to add unused dependencies before their
need is demonstrated.

## Prohibited in the MVP

- Docker or container orchestration
- PostgreSQL or another server database
- Microservices, message brokers, or separate worker processes
- Webhook infrastructure or a public web server
- Heavy job schedulers or monitoring stacks
- Resident application schedulers, continuous source polling, collectors,
  watchers, or cache synchronization
- Browser automation for routine source collection
- Continuous OCR, computer vision, or media processing
- Local AI models, embeddings, vector databases, general cloud generation, or
  cloud AI outside the bounded municipal tasks and single secondary provider
  accepted in ADRs 0011, 0012, 0028, and 0030
- Unbounded retries, caches, queues, concurrency, logs, or data retention
- Dependencies that duplicate a clear standard-library solution without
  material benefit

## Degraded operation

Unstable infrastructure is normal, not exceptional:

- valid data from available sources may still produce a partial digest;
- an unavailable optional section should be omitted;
- stale data must not be presented as current;
- unavailable data must not be converted into reassuring defaults;
- no trustworthy content means no digest, not a fabricated one.

## Decision test

Before adding a dependency or recurring task, answer:

1. What user value requires it?
2. What are its idle and peak CPU, memory, storage, battery, and network costs?
3. How does it behave offline or after Android kills the process?
4. Is a simpler standard-library or scheduled alternative sufficient?
5. Can it be removed or recovered without complex operations?

Any exception to these constraints requires an accepted ADR.
