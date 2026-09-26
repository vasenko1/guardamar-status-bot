# ADR 0062: Evidence-complete municipal event programmes

Date: 2026-09-12

## Status

Accepted.

## Context

The 11 September weekend publication for 12–13 September omitted real
municipal activities and the Fiestas del Campo finale. A duplicated, long
Todo Cultura reproduction could return a nonempty but partial model result;
the date cursor then made the omission durable. The monthly municipal MUPI
contained a too-small inset of the festival's complete programme. A library
exhibition date range also produced false weekend access despite closed hours.

## Decision

- Keep one normalized event catalog shared by morning and weekend selectors.
- Before advancing a Todo programme date, account for every independent timed
  row. Recover missing small rows individually; use a strict deterministic
  parser only for quoted activities with explicit date, time and venue. Retain
  prior facts and do not advance the cursor on incomplete extraction.
- Persist explicitly named future same-weekday repeats from a verified row,
  validating the stated month and actual weekday, even beyond the seven-day
  polling window and even if another row's model extraction fails.
- Add a bounded, credential-free public Turismo WordPress article/poster read
  for the Campo festival. Prefer explicit dated article facts to conflicting
  combined vision candidates. Keep fireworks and chocolate untimed when the
  primary publication supplies no exact time. Poster/model failure cannot
  erase the complete article-stated programme.
- Use official library opening weekdays to filter exhibition ranges. Preserve
  old snapshots safely until a new hours read succeeds.
- Treat primary-source changes/cancellations as updates; lack of an item in a
  supplemental feed alone is never cancellation.

## Consequences

There is no new dependency, raw source cache, general event platform or
additional morning fetch. A municipal sync may perform more bounded model
calls when a programme is incomplete, but it now fails closed instead of
publishing a partial catalogue as complete. Article-specific extraction is
deliberately narrow and evidence-bound; other festivals require their own
source audit before extension. Operational verification must compare the
published output with an independently collected calendar, not merely the
poster examples supplied by a user.


## 26 September 2026 amendment: Todo detail dates and queue progress

A production miss during the Virgen del Rosario programme exposed a second
incremental-coverage failure mode. Todo Cultura had already indexed the local
Bingo page, but its REST excerpt described the whole patronal period
`19 September–18 October`; the actual occurrence, `26 September`, was stated
inside the full event document. The excerpt endpoints therefore ranked the page
outside the current seven-day window. Repeated incomplete programme reads also
rolled back progress for unrelated successful candidates, keeping the bounded
queue sticky.

The existing bounded Todo supplement is retained, with these clarifications:

- REST title/excerpt dates are discovery hints, not authoritative occurrence
  dates. When a downloaded local detail page contains explicit Spanish dated
  section headings, those detail dates replace the metadata hints.
- One of the existing six detail slots is ordered first for the oldest
  unchecked local candidate inside the 44-day horizon. The six-detail,
  four-document-per-request and three-programme limits do not increase.
- Dated standalone detail pages expose the same deterministic timed
  `event_rows` used by municipal programmes. Existing row completeness,
  recovery and source-proven session grouping therefore apply without a new
  event model or grouping path.
- On an incomplete extraction, deterministic discovery facts such as the
  detail-derived dates and checked status may persist. Processed dates/chunks
  advance only for candidates whose selected programme completed; failed
  candidates retain their prior extraction progress. Hard transport/model
  exceptions still fall back to the previous Todo snapshot.
- Parser version 20 performs a narrow migration from version 19: it preserves
  the immediately preceding raw-session-row work and existing extraction
  progress while rechecking dated candidates once for detail-date provenance.
  Older parser states keep the existing full reopen behavior.

This amendment changes neither publication budgets nor editorial grouping.
Todo Cultura remains supplemental; primary official festival-programme coverage
is a separate source-adapter concern.


## 26 September 2026 amendment: bounded official Turismo programme articles

The Rosario audit also confirmed that the monthly cultural agenda is not the
only first-party event publication surface. Turismo Guardamar regularly
publishes separate WordPress articles for complete or multi-day programmes,
including Virgen del Rosario, Moros y Cristianos, Hogueras, Feria del Comercio
and Fiestas del Campo.

The existing Campo adapter remains unchanged because it has stronger
programme-specific deterministic rules and poster corroboration. A separate
bounded text-first adapter now covers the wider article class:

- one recent-post metadata request reads at most 20 official Spanish posts;
- only current-year, programme-shaped titles with an explicit relevant date in
  title/excerpt are candidates;
- the existing Campo article is excluded from this generic path;
- at most three candidate articles are considered per sync;
- unchanged candidates reuse their last verified article events without a
  detail read or model call;
- changed/new candidates fetch one bounded first-party detail page and use the
  existing evidence-bound official-text extractor;
- a candidate is accepted as a programme only if its complete extracted article
  contains at least two independently validated events before current/future
  filtering;
- only occurrences from today through the existing 44-day planning horizon are
  retained;
- temporary index/detail/model failures preserve still-relevant last-good facts;
- no generic image OCR, browser, credential, daemon or extra scheduler is added.

This extends discovery, not editorial policy. Verified programme occurrences
enter the existing normalized event model with one `programme_title`; Todo
Cultura may still enrich or time-match the same occurrence through the normal
merge path.


## 26 September 2026 amendment: first-party programme completeness gate

The first production refresh of the generic Turismo programme adapter exposed a
second omission class: the Rosario article was discovered and stored, but the
initial structured extraction preserved only the 15 October conference among
the still-relevant occurrences. Because the article state was then cached as
unchanged, the partial result would otherwise have become durable.

Generic first-party programme articles now have an explicit completeness gate:

- the raw WordPress `content.rendered` is scanned deterministically for dates
  that lead semantic content blocks such as paragraphs, list items, or
  headings; introductory date ranges are not treated as occurrence proof;
- only explicit block-leading dates from today through the existing 44-day
  horizon are required for current completeness;
- every required date must have an extracted event whose `start_date` equals
  that date; one broad multi-day event cannot satisfy several explicit
  occurrence dates;
- when the first official-text extraction misses required dates, at most one
  targeted recovery call reuses the existing Guardamar standalone extractor
  with exactly those missing dates;
- if any required date is still missing after that bounded recovery, the
  article is rejected as incomplete and no new article state is accepted;
- the Turismo programme-text extractor version is raised to 2. Version-1
  article facts are not trusted or retained during this migration, so the
  production partial Rosario snapshot must be revalidated instead of silently
  reused;
- unchanged version-2 articles still reuse last-good verified facts with no
  detail read or model call.

This remains date-level completeness, not an attempt to invent or count acts
inside a date block. Todo Cultura and other official sources may still add
distinct same-day occurrences through the existing merge path. The generic
adapter remains text-first and adds no OCR, browser, dependency, daemon, or
scheduler.
