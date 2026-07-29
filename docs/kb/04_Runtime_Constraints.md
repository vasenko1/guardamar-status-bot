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

The optional operator listener may keep one bounded Telegram `getUpdates`
long poll solely for allowlisted private `/preview`. It must not schedule
publication, poll data sources until a command arrives, use a webhook, or
persist update history.

One short daily deployment check may fetch the tested GitHub `deploy` branch.
It must exit immediately when no update exists and must not become a resident
deployment agent or self-hosted CI runner.

## Resource policy

### CPU and battery

- Collect once at 07:30. In season, allow only seven quick SafeBeach checks
  from 10:10 through 10:40 and at most one later full recollection.
- Leave exact timing to a lightweight external Termux scheduler.
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
- Make only the bounded requests required by the morning collection or an
  authorized on-demand preview.
- Reuse connections when simple and safe.
- Never retry indefinitely.
- Do not make digest delivery depend on every source succeeding.

### Storage

- Store configuration, minimal daily replacement state, and the bounded
  monthly event snapshot accepted in ADR 0012.
- Keep logs rotated or otherwise bounded.
- Do not archive raw responses by default.
- Do not cache raw source responses or municipal information except the
  normalized monthly event snapshot accepted in ADR 0012.
- Use one small atomic JSON file; SQLite is unnecessary for the MVP.

## Preferred technology direction

- Python available in Termux
- Python `tzdata` package because some Termux builds do not expose the Android
  timezone database to `zoneinfo`
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
- Local AI models, embeddings, vector databases, or cloud AI outside the
  bounded Gemini traffic fallback accepted in ADR 0011
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
