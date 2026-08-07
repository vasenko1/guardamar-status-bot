# ADR 0033: Rolling incremental event supplement

## Status

Accepted and implemented

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
- Download at most three selected full articles in one bounded REST request.
  Ignore metadata without a discoverable date and send only newly covered
  dated sections, capped by the existing text limit, to structured extraction.
- Treat the newest candidate as authoritative among duplicate programme
  reproductions for the same date. A later `modified_gmt` reopens its hinted
  dates; unchanged copies do not repeat full downloads or model work.
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
authority. More than 100 simultaneous changed Guardamar items could require a
later scheduled run, but ascending cursor order prevents permanent loss under
the accepted bounded workload.

## Alternatives rejected

- Re-fetch a full seven-day article set daily: redundant network and LLM cost.
- Build the whole next week on one weekday: creates a burst and a week-boundary
  failure mode.
- Poll every five minutes with every beach retry: redundant and source-heavy.
- Store raw articles or a generic event cache: unnecessary state and staleness.
