# ADR 0033: Rolling incremental event supplement

## Status

Accepted and implemented; same-date candidate selection amended by ADR 0044; Guardamar standalone scope amended 2026-09-20

## Context

An exact-date Todo Cultura query can recover useful registration and price
facts, but it repeats the same municipal programme every day and learns the
next edge of the week too late. Running a weekly batch would create a burst and
could lose the rolling boundary. The Termux device must keep requests, model
calls, state and recovery simple.

## Decision

- Keep the official municipal and Agenda Guardamar catalogs and their existing
  45-day horizon. Todo Cultura remains a lower-priority supplement.
- Maintain a rolling inclusive seven-day enrichment window. Every municipal
  refresh considers today through today plus six days; advancing one day adds
  only the new edge date.
- Read one bounded WordPress metadata page. Persist only a five-minute-overlap
  modification cursor, at most 100 lightweight candidates, and at most 45
  covered date strings inside the existing atomic municipal catalog.
- Select at most six dated detail candidates in bounded REST batches and admit
  at most three programme inputs per refresh. Ignore metadata without a
  discoverable date.
- Classify Todo Cultura event-card identity from its own title/permalink as
  `local`, `foreign`, or `unknown`. A card whose event identity names only
  another municipality is discarded before detail download even if its article
  body mentions Guardamar. A multi-municipality card is local only when
  Guardamar is explicitly one of the card's primary localities.
- Keep the existing municipal-programme path for attributed Guardamar agenda
  reproductions. A local standalone card may enter a separate bounded
  Guardamar-scoped structured extraction path; unknown standalone cards fail
  closed. Standalone metadata dates only bound the eligible extraction window
  and are never assumed to be event occurrences. A valid empty structured
  result marks that card checked and publishes nothing, preventing one
  ambiguous article from poisoning the bounded queue; transport/model failures
  still retain prior state for a later retry.
- Within the same rolling date, prefer explicit local cards and more specific
  date sets before the existing participation/admission usefulness score.
  Preserve the bounded 100-candidate fairness buffer rather than replacing it
  with a newest-only queue.
- Treat the newest candidate as authoritative among duplicate programme
  reproductions for the same date. This date-wide shortcut is superseded by
  ADR 0044: distinct same-date candidates are processed independently and
  exact section hashes, rather than the date alone, identify duplicates.
- Advance the cursor and covered dates only after all selected sections have
  normalized successfully and the atomic catalog is written. On any source,
  model, validation or write failure, preserve the previous facts and state.
- During the existing 10:10–10:40 update window, attempt each event catalog at
  most once per day, independently of SafeBeach success. This saves newly
  published ordinary event facts for later publications but does not itself
  trigger a Telegram replacement.
- Add no daemon, database, raw-response archive, new dependency or new cron
  row.

## Consequences

The first run may fill several dates, while unchanged later runs normally read
only the small metadata delta. The next day processes only a newly entering
edge date. The bounded overlap protects equal-time and delayed updates, and
the morning plus late refresh provide two opportunities without seven repeated
catalog calls during beach retries.

The public WordPress index is supplemental and may omit a date from its title
and excerpt. Such an item is intentionally not downloaded unless a later
metadata revision exposes a date; official sources retain completeness
authority. Foreign-city event cards no longer consume detail slots or enter the
Guardamar catalog merely because their article body mentions Guardamar.
Explicit multi-city cards that include Guardamar remain eligible, while an
unknown standalone article is omitted. More than 100 simultaneous changed
eligible items could require a later scheduled run; the bounded fairness model
continues to prevent a steady stream of newer pages from starving older pending
work.

## Alternatives rejected

- Re-fetch a full seven-day article set daily: redundant network and LLM cost.
- Build the whole next week on one weekday: creates a burst and a week-boundary
  failure mode.
- Poll every five minutes with every beach retry: redundant and source-heavy.
- Store raw articles or a generic event cache: unnecessary state and staleness.
