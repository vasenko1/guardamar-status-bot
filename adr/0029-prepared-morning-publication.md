# ADR 0029: Prepare morning data before publication

## Context

The 07:30 message must be delivered with the maximum verified information on a
weak Termux device. A transient AEMET 429 and a Gemini title-translation 503
previously delayed or emptied the complete message even though independent
local event facts were already available.

## Decision

- Keep the two existing atomic event catalogs as the durable source facts.
- Fill a bounded atomic title-translation cache at 06:00, 06:30, and 07:00.
  Cache keys include source identity, exact source title, and policy version.
  Missing translations fall back to the verified Spanish title with whitespace
  and all-uppercase presentation normalized; no event fact is invented.
- Fetch and normalize AEMET once at 07:15 into a private same-day snapshot.
  The 07:30 run accepts it only while it is at most 60 minutes old. If no valid
  snapshot exists it may make one normal live request, except while the
  preparation lock is held.
- AEMET is an optional section of the complete publication. Its failure cannot
  suppress verified holidays, traffic, or events. An empty greeting alone is
  never published.
- Revalidate cached warning expiry when rendering. The later beach replacement
  may use the same-day AEMET snapshot only as fallback after a fresh failure.
- After SafeBeach or the Mayor channel triggers the single later replacement,
  refresh event catalogs once, prepare only missing translations, and collect
  the other current sources. These sources alone do not trigger replacement.
- Bound the Telegram message by dropping complete lowest-priority event records
  from the end; never truncate HTML or split the digest.

## Consequences

Publication no longer depends on Gemini or on a successful AEMET response at
exactly 07:30. State remains small JSON files with atomic replacement and no
new dependency, database, daemon, raw provider response, or secret persisted.
The added cron jobs are short-lived and ready cache hits perform no network
request.

This decision supersedes the no-stored-translation clauses in ADRs 0007, 0012,
and 0028, and the mandatory-AEMET fallback wording in ADR 0021.
