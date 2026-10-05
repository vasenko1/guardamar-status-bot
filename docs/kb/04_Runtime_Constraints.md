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

CAMS ADS access and NetCDF decoding run only in the separate GitHub-hosted data
producer. Android performs one bounded JSON read at 07:30, then only bounded
checks at three existing lifecycle checkpoints and the first invocation of
existing operational windows until today's UTC cycle is accepted. A late
comparison considers only the remaining local day while retaining the rolling
input history. Production keeps one mutable last-good JSON, one accepted
lifecycle snapshot, and only the small cycle-addressed candidate files needed
while acceptance is pending. Accepted promotion prunes superseded candidates.
Operator previews use a disposable copied cache that is removed when the
preview ends. Android has no ADS credential, scientific Python dependency, or
CAMS polling process.

AEMET operational warning monitoring is an independent CAP-only one-shot at
minute 51 from 07:51 through 23:51 Europe/Madrid. It uses the existing optional-
product adapter limits: two bounded attempts, 15-second request timeouts and
bounded retry delays. These extra AEMET checks do not increase SafeBeach,
CAMS or Meteosalud request cadence, add a resident process, or persist raw CAP
responses. A failed CAP observation preserves the prior delivered/pending state
and does not publish a potentially stale pending warning on that invocation.

The OCI capacity search also runs only on a GitHub-hosted runner. Each invocation
is short-lived, has no SDK automatic retry, uses one concurrency group, and may
make at most one `LaunchInstance` request after two complete OCI-state checks.
One optional capacity-report call may choose the 2 GB A1 fallback only from an
explicit 6 GB `OUT_OF_HOST_CAPACITY` + 2 GB `AVAILABLE` result; failure or
inconclusive data falls back to the original 6 GB launch behavior. It never
loops on host capacity or retries 6 GB as 2 GB in the same run. The Android
installation receives no OCI SDK or credential. A larger trial service limit
must never override the explicit 2 OCPU, 12 GB RAM, and 200 GB Always Free cost
ceilings. Any existing non-terminated target makes subsequent runs read-only.
An optional Termux one-shot backstop uses only standard-library outbound GitHub
API calls five minutes after each GitHub schedule slot. It dispatches only when
the workflow is active and no queued/in-progress or younger-than-ten-minute
`main` run exists. The phone holds only a single-repository Actions PAT in a
private file; it never receives OCI credentials, OCI SDK, launch logic or audit
logic. Failed metadata reads and ambiguous dispatch responses do not trigger
same-invocation retries. The backstop shares the project runtime lock and has
no daemon, wake lock or persistent stop-marker (ADR 0063).

The optional operator listener may keep one bounded Telegram `getUpdates`
long poll solely for allowlisted private `/preview`. It must not schedule
publication, poll data sources until a command arrives, use a webhook, or
persist update history.

Deployment is a deliberate Tailscale SSH operation after tests, push, pull
request, and merge to canonical `origin/main`. A production target must pass an
ancestor check against the fetched `origin/main`; restart every affected
resident service. In particular, if deployed Python changes are reachable from
the private `/preview` path, the long-lived `guardamar-preview` service must be
restarted after the fast-forward and the replacement `telegrambot listen`
process must be verified. Fresh one-shot commands such as CLI `preview` or
`refresh-current` do not prove that the resident listener reloaded changed
modules. A temporary `DEVICE TEST ONLY` commit may run on Android only
for necessary Termux-specific verification and must restore the recorded clean
production commit and service afterward. It never becomes a production release
without merging to `main`. Deployment must not add a GitHub promotion branch,
scheduled self-update, resident deployment agent, self-hosted CI runner, or
public inbound port.

Termux cron installers must not assume that `SVDIR` is inherited.
Non-interactive SSH shells may not source the `termux-services` login-shell
startup that normally exports `SVDIR=$PREFIX/var/service`. An installer should
first accept an already-running `crond`; if startup is required, it must
preflight the expected Termux service directory, invoke `sv` with an explicit
service root, and verify the daemon after startup. It must not start a second
`crond` merely because service-manager environment is absent.

The Friday Weekend publication remains one short-lived 19:15 one-shot plus one
20:15 recovery. It uses one bounded atomic dated-delivery file
(`state/weekend_delivery.json`) and retains the prior
`state/weekend.json` success marker only for rollback compatibility.
Before a non-idempotent send it reserves `uncertain`; ambiguous
timeout/network/5xx delivery is never automatically resent. Only explicit
Telegram rate-limit rejection may be retried inside the send. The new runtime
also acquires the legacy Weekend lock, so a process from the previous release
cannot overlap delivery during deployment. No source request, cron row,
dependency, daemon or queue is added by this delivery hardening.

Sports Today is one short-lived local-snapshot publication at 08:25
Europe/Madrid with one 09:25 recovery. It performs no source HTTP and no AI:
the shared planning loader accepts only same-day fresh local snapshots, then
Telegram is the only outbound operation in the send path. Delivery uses the
shared bounded dated-state primitive at `state/sports_today.json`; a confirmed
or uncertain send blocks recovery, while no qualifying sport writes no marker.
Its wrapper rotates `state/sports-today.log` at 512 KiB. Both cron rows belong
to the existing event-planning/weekend managed block; there is no per-sport
installer, daemon, queue, database or runtime source lock. Morning sport
exclusion is deployed in the same release so the current-day publication
replaces, rather than adds to, the Morning repetition.

The Sports Slice C fishing enrichment remains inside the existing short-lived
05:10 fishing preparation lifecycle. It may read one bounded FPCV convocatoria
index, a small bounded set of first-party FEPyC national-authority pages, and
only exact FPCV convocatoria PDFs linked from accepted current/future Guardamar
rows. No new cron, daemon, browser, OCR, JavaScript runtime or Python dependency
is allowed.

For this workflow only, Termux `pdftotext -layout` is approved under these
hard bounds: exact `federacionpescacv.com` HTTPS link, `application/pdf`,
`%PDF-` magic, at most 1 MiB PDF bytes, one extraction attempt, at most
10 seconds extraction time, and at most 64 KiB non-empty UTF-8 text. At most
four relevant FPCV detail records and four explicit FEPyC authority records may
exist. Relevant FPCV PDF bytes may be checked once on a successful daily
details refresh; SHA-256 prevents repeat `pdftotext` work when the index row
and PDF content are unchanged. A changed index identity or changed PDF SHA
invalidates the old semantic detail immediately if the replacement cannot be
parsed; only an unavailable fetch of the same reviewed document may reuse
last-good within the freshness window. Raw PDF bytes and extracted text are
process-local and discarded after normalization.

Accepted authority/details override or enrich the base fishing Event only for
36 hours after their source-backed observation; future timestamps and older
last-good records are ignored. The existing strict
`state/pesca_cv_events.json` schema is not extended; FEPyC authority and FPCV
details use separate bounded rollback-safe state files. A details/PDF failure
must not invalidate a successfully refreshed base fishing calendar. See
ADR 0101.

The CONVEGA one-off registration slice runs only as short-lived one-shots at
12:47 and 13:47 Europe/Madrid. The first wrapper invocation performs at most one
bounded WordPress REST refresh when a valid same-day snapshot is absent. The
13:47 recovery reuses today's accepted local snapshot and therefore performs no
normal source HTTP. The source phase alone may hold `state/code-runtime.lock`;
the lock is released before Telegram delivery. Source responses are parsed
in-memory and only one compact last-good normalized JSON is persisted.

Registration lifecycle state is a separate bounded atomic JSON containing
baseline evidence, announced IDs, trigger keys, and at most one ambiguous
delivery reservation. Same-day snapshots with timestamps later than the local
invocation are rejected as future. No retryable message queue, database,
browser, OCR, JavaScript runtime, AI fact extraction, resident worker, or
continuous polling is allowed. A deterministic Telegram failure is recomputed
on the next invocation; an ambiguous failure blocks automatic resend until an
operator resolves it as sent or unsent. See ADR 0089.

The local earthquake feature may make one bounded official IGN GeoRSS request
at minute 55 of every hour. It has no internal retry, browser, screenshot,
resident worker, or raw-response cache. The process exits after parsing and
possible delivery. Normalized revision and delivery state is capped at 256
events and 14 days; its log rotates at 1 MiB with one previous file.
The monitor uses one mutually exclusive runtime lock. A conflicting invocation
exits successfully without a request.

The 112/Previfoc feature runs as one short-lived process at minute 19 of every
hour. It makes one bounded read each of the CCE active-emergencies page, the
current CCE PDF bulletin, and the current-day Previfoc zone-6 ArcGIS row. It
stores only normalized observations and publication state. CCE PDF bytes and
extracted text remain process-local and are discarded before exit; raw source
responses are never archived. The process shares the project runtime lock and
its log rotates at 1 MiB with one previous file.

The TomTom traffic feature remains one short-lived hourly process at minute 37.
It makes one bounded Guardamar incident-details request and no continuity lookup
request. Provider-ID churn is reconciled only from the current normalized
snapshot and the existing small `state/traffic.json`: no alias database, raw
response history, background watcher, or additional dependency is permitted.
Ambiguous continuity freezes only the affected lifecycle for that invocation;
it must not become an all-clear claim.

The CCE bulletin text extraction uses the already approved Termux `poppler`
package and `pdftotext`. The adapter validates the bulletin's own `FECHA` and
`HORA` before accepting its state. No OCR, browser, image rendering, or
additional Python dependency is introduced.

The linked pinned guide remains one shared recoverable Telegram graph. The
existing 05:00 transport invocation updates its bounded transport media and
source snapshots, then reconciles the whole graph. A second short 16:30
`sync-guide` invocation reads the two approved Aqualider catalogue JSON
endpoints sequentially, stores only one normalized last-good catalogue in
`state/guide.json`, reconciles the same graph, and exits. It adds no daemon,
worker pool, database, browser, per-sport process, or independent Telegram graph.

The guide catalogue may store service/provider identifiers, normalized names and
their reciprocal relationships only. It does not store source HTML, raw JSON,
descriptions, images, marketing claims, or response history. Normal pool seasons
come from the fixed product calendar. Registration availability remains out of
automation until one bounded account-level request is validated; N-per-service
availability polling is prohibited. Seasonal June/September notices are sent at
most once per switch key, and ambiguous new-message delivery is recorded rather
than automatically retried. The guide log rotates at 512 KiB with one previous
file.

PDF rendering for transport is allowed only after a stable changed official
one-page document; one strict normalized airport schedule and fare snapshot is
also allowed. Fare text extraction is allowed only after a stable changed
official tariff PDF. One bounded in-memory HTTPS issuer-chain recovery is allowed
only for the documented Bus Sigüenza missing-issuer fault. It may read at most
two allowlisted DER certificates from the official Let's Encrypt certificate
repository, must not disable TLS verification, and must not persist
certificates. No browser, OCR, resident collector, or background process is
allowed for the guide.

## Resource policy

### CPU and battery

- Prepare compact event translations before publication and one normalized
  AEMET snapshot at 07:15; the 07:30 process reuses them. In season, allow
  only seven quick SafeBeach checks
  from 10:10 through 10:40 and at most one later full recollection.
- Leave exact timing to a lightweight external Termux scheduler.
- Install recurring cron rows by merging them with the existing crontab; never
  replace unrelated jobs owned by another bot.
- Keep the guide sync sequential and one-shot; its current source cost is two
  small catalogue requests, not one request per activity.
- Keep SUMA to one independent 08:05 one-shot with two bounded sequential
  public HTML GETs; store only bounded semantic trigger keys and never raw pages.
- Avoid continuous parsing, transformation, or monitoring.
- Do not optimize speculatively, but reject designs with obvious background
  cost.

### Memory

- Process small responses and compact records.
- Do not retain full source histories in memory.
- Limit concurrency to the small number of approved sources.
- The current guide catalogue fetch is sequential; do not add concurrency until
  a demonstrated need justifies it.
- Avoid heavy frameworks and model runtimes.

### Network

- Assume requests can time out, disconnect, or return incomplete data.
- Make only the bounded requests required by scheduled collection, the morning
  collection, or an authorized on-demand preview.
- CAMS uses one public JSON response capped at 128 KiB. Production may reuse
  its validated mutable last-good copy when the remote file is unavailable;
  accepted-cycle reconstruction reads only the separate accepted snapshot.
  Preview reads and writes a disposable private copy. Raw NetCDF never reaches
  or persists on Android.
- Reuse connections when simple and safe.
- Never retry indefinitely.
- The 16:30 guide sync performs one `GET /v2/service/` capped at 256 KiB and one
  `GET /v2/provider/` capped at 128 KiB against the exact approved SimplyBook
  HTTPS host, sequentially, with a 15-second request timeout. It requires
  `application/json`, valid JSON, valid identifiers and reciprocal
  service/provider relationships. `200 text/html`, empty/malformed structures,
  redirects outside the host, timeouts, and partial relationships are failed
  observations: preserve last-good state and publish no catalogue claim. Do not
  add cookies, CSRF bootstrap, HTML scraping, a browser, an inner retry storm, or
  N-per-service availability requests.
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
  explicit state. Later AEMET checks request only the CAP warning product
  hourly at :51 from 07:51 through 23:51 and remain independent of beach and
  environment delivery. AEMET pending state never adds SafeBeach requests, and
  beach confirmation never suppresses an AEMET CAP checkpoint.
- The 05:30 Agenda Guardamar refresh may inspect at most twelve same-host
  detail links with no more than three requests in flight. The 05:10 municipal
  refresh makes one HTML request and downloads MUPI only after its official
  URL changes. Neither stores downloaded pages or media. Today's bounded title
  set is translated only by the 06:00/06:30/07:00 preparation commands and
  stored in a bounded atomic cache. The 07:30 digest never calls Gemini.
- The 05:10 municipal refresh may also read one bounded AM Guardamar WordPress
  REST post list (at most twelve posts and 300 KiB). It stores only normalized
  future public-event facts and reuses an unchanged post's `id` and `modified`
  facts without another extraction. The same municipal refresh reads one
  bounded recent Turismo WordPress metadata index for generic official
  programme articles, considers at most three candidates, and fetches details
  only for changed/new candidates. Each changed/new article gets one normal
  evidence-bound text extraction and, only when deterministic date-leading
  blocks prove missing current/future occurrence dates, at most one targeted
  recovery extraction over a smaller official-text slice containing only those
  missing date sections. Unchanged verified version-3 articles require neither
  detail reads nor model calls. The same refresh may read one bounded
  Ayuntamiento news index and at most two recent fiesta detail pages. Only a
  new or changed event-specific official poster is downloaded, with a 4 MiB
  bound, and it receives exactly two blind structured vision readings; an
  unchanged verified article requires no poster download and no model call.
  No arbitrary municipal image is sent to vision. The 05:10 refresh may read
  one Todo Cultura metadata page, bounded
  to 100 records and 300 KiB, and up to
  eight bounded detail records in at most two REST reads of four records and
  300 KiB each, while sending at most three selected programme
  sections to extraction. It keeps a five-minute cursor
  overlap, at most 100 lightweight candidates and 45 covered dates. Unchanged
  covered dates cause no full-detail or LLM work. The 10:10–10:40 invocations
  attempt each event catalog at most once per local day.
- Telegram operations share one bounded JSON client restricted to the official
  API host. Sends retain their workflow-specific delivery policy. Idempotent
  known-message edits and pins retry transient failures at most twice and
  honor only server delays that fit a 60-second per-wait bound. New guide
  messages retry only explicit rate-limit rejections; ambiguous delivery is
  recorded to prevent an automatic duplicate.
- Electricity checks confirmed publication before any source access. The first
  complete ESIOS response for a target date is atomically normalized to one
  private local snapshot; later invocations reuse it instead of repeating the
  API request. Preview and publication share one non-blocking local lock. No
  raw response or token is stored. The publication marker also retains one
  Telegram message ID for the persistent PVPC explanation anchor.
- Mayor, municipal-agenda, resident-news, Gemini, and the direct Groq fallback
  enforce exact/allowlisted HTTPS hosts, expected MIME types, and bounded
  responses. Groq may follow only an eligible Gemini provider failure for the
  four bounded text operations in ADR 0085 plus the two resident-news text
  operations in ADR 0087. Factual event extraction and image reading remain
  Gemini-only. Neither provider retries inside this layer.
- Resident news runs only at 11:11, 15:11 and 18:11 Europe/Madrid. Each run
  performs one RSS read and classifies at most eight unseen title/description
  records in one AI call. It may inspect at most three queued candidates to
  bypass missing, duplicate, or temporarily unreachable sources, but still
  makes at most one final AI composition call and sends at most one public post.
  A transient source failure records only a tiny bounded attempt marker and
  rotates behind never-tried candidates; eligible items expire after 48 hours.
  After downtime, unseen RSS entries already older than 48 hours are recorded
  stale before classification so they consume no AI budget. The first valid
  feed seeds silently. State is capped at 128 compact records; raw pages are
  never stored.
- A next-day La Redonda market assertion may add one bounded Mayor-channel
  HTML read only when the reviewed calendar says tomorrow is a market day.
  Gemini/Groq market classification is attempted only when that fresh page
  contains market-related text. A terminal next-day delivery state is checked
  before publication construction, so the 20:25 recovery does not repeat this
  source/model work after a confirmed or uncertain 19:25 delivery. The shared
  planning-events loader remains local-only. No raw page, classifier output,
  additional retry loop or market-specific state is stored.
- Explicit Mayor-channel events reuse the existing bounded morning page read;
  they add no request, model call, raw-response cache or background process.
- Do not make digest delivery depend on every source succeeding.

### Storage

- Store configuration, minimal daily replacement state, the prepared AEMET
  snapshot from ADR 0029, and the two bounded normalized event
  catalogs accepted in ADRs 0012 and 0028. The municipal catalog may retain
  unexpired prior-poster events
  for at most the next seven days during a month transition.
- CAMS production storage is bounded to one mutable last-good JSON, one accepted
  lifecycle snapshot, and cycle-addressed candidates awaiting acceptance.
  Superseded candidates are pruned after acceptance; preview copies live only
  in a temporary directory and are removed at process exit.
- Store at most one complete normalized ESIOS target day with its official
  indicator and geographic scope, separately from the electricity publication
  marker. Replace it only after a complete validated response for another day.
- Keep logs rotated or otherwise bounded.
- Keep at most the current and previous accepted urban-timetable PNG for each
  municipal line. Temporary PDFs and candidate images are removed before the
  one-shot process exits.
- Keep one current and one previous normalized airport schedule/fare snapshot.
  Store no raw Bus Sigüenza HTML or PDF.
- Keep one `state/guide.json` normalized last-good catalogue plus the bounded
  seasonal-notice marker. Store no raw SimplyBook response or source history.
- Do not archive raw responses by default. The normalized CAMS JSON lifecycle
  snapshots above are the explicit bounded exception required for semantic
  comparison and crash-safe acceptance.
- Do not cache raw source responses or municipal information. Only normalized
  source-language event facts, bounded provenance, and the incremental Todo
  Cultura metadata allowed by ADR 0033 may enter the two event catalogs.
- Use small atomic JSON files for independent publication workflows; SQLite is
  unnecessary for the MVP.

## Preferred technology direction

- Python available in Termux
- Python `tzdata` package because some Termux builds do not expose the Android
  timezone database to `zoneinfo`
- Termux `poppler` utilities only for changed one-page municipal timetable PDFs,
  changed Bus Sigüenza tariff PDFs, the exact bounded FPCV Guardamar convocatoria
  PDFs approved by ADR 0101, and bounded in-memory text extraction from
  the current CCE bulletin used by the 112 watcher
- Termux `openssl-tool` command only to read the Bus Sigüenza leaf AIA after
  the documented missing-issuer verification failure
- `asyncio` for bounded network concurrency
- standard-library HTTP for the current small source and delivery set
- aiogram or aiohttp only if a later requirement clearly justifies them
- Python standard-library facilities where they are sufficient
- small atomic JSON state files per independent workflow

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
- Per-sport or per-activity daemons, state files, cron rows, or source polling
  when one account-level guide sync can serve the catalogue
- Continuous OCR, computer vision, or media processing
- Local AI models, embeddings, vector databases, general cloud generation, or
  cloud AI outside the bounded municipal tasks, ADR 0087 resident-news tasks,
  and the single direct Groq secondary provider accepted in ADR 0085
- Unbounded retries, caches, queues, concurrency, logs, or data retention
- Dependencies that duplicate a clear standard-library solution without
  material benefit

## Degraded operation

Unstable infrastructure is normal, not exceptional:

- valid data from available sources may still produce a partial digest;
- an unavailable optional section should be omitted;
- an unavailable guide catalogue preserves its last-good baseline and does not
  prevent static guide self-healing;
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

## Product-award runtime budget

The product-award feature has one daily one-shot cron invocation and reads only
the existing `state/product_awards.json` before source access.

- During the three-day cooldown: zero award/retailer HTTP requests.
- After registry exhaustion: zero award/retailer HTTP requests.
- A due run uses one finite category scan. It may inspect later categories only
  when the first valid category winner repeats the previous retailer and a
  different-retailer alternative is being sought.
- Retailer preference adds no state field, second scan, queue or persistent
  cache. The previous retailer is derived best-effort from the last published
  event ID already stored.
- Award evidence, exact retail identity and current price remain mandatory.
- An exact reviewed product photo is the normal presentation. The selected
  candidate may try only a small explicit list of approved official image
  sources; there is no runtime image search or discovery.
- Category selection itself remains media-neutral: image pages are not read
  until one product has already won selection, except during an explicit
  operator preview.
- Product media still cannot make an otherwise valid product ineligible. Only
  after every reviewed image source is exhausted may delivery degrade to a
  no-image Rich Message.
- Consum image selection prefers allowlisted official `media[]` URLs; no
  synthetic filename guessing or eligibility-time image download is allowed.
- ALDI may parse embedded Next.js JSON but never executes JavaScript. Explicit
  `hasError=true` is a product-page failure; a healthy page with missing
  `apiData` is contract drift.
- Exact Carrefour/DIA product pages may use the reviewed browser-navigation
  HTTP header profile required by their public SSR surfaces. This remains one
  bounded HTML GET with exact markers and product-card-scoped price parsing;
  no browser, JavaScript, cookie session or catalogue crawl is permitted.
- Telegram tries each reviewed image source remotely in order. Only an explicit
  remote-media rejection may trigger the existing bounded local image
  download/upload for that source. Deterministic failure may advance to the next
  reviewed exact image source; no-image delivery is the final fallback only
  after all reviewed image paths fail. Ambiguous delivery always stops.
- Every HTTP operation remains bounded by the existing host allowlists,
  timeouts and response-size limits.
- No browser/Playwright, OCR, LLM, search engine, database, daemon, retailer
  quota, discovery queue, raw-response cache or retailer-specific recurring job
  is allowed.
- State remains cooldown/dedup/cursor/uncertain-delivery only; no migration is
  required for retailer preference.
- Product-award logs remain bounded and a due no-publication run records one
  concise final reason.

