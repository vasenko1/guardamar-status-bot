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
- the first full-article extraction is best-effort input to the completeness
  gate. Individually invalid candidates are discarded; even when all initial
  candidates are invalid, that is treated as zero accepted events so the single
  bounded recovery still gets a chance to run. The recovery extraction itself
  remains strict and must yield evidence-valid facts;
- when the first official-text extraction misses required dates, at most one
  targeted recovery call is allowed. Recovery no longer sends the whole article
  through the Todo-specific standalone prompt: it builds one bounded official
  text slice from the missing date sections and reuses the ordinary
  evidence-bound municipal programme text extractor;
- the date-section slice contains the date-leading block and following semantic
  blocks up to the next explicit date, so a heading-only date does not lose its
  event description. Recovered facts are accepted only when their exact
  `start_date` is one of the requested missing dates;
- if any required date is still missing after that bounded recovery, the
  article is rejected as incomplete and no new article state is accepted;
- the Turismo programme-text extractor version is raised to 3. Version-1 and
  version-2 article facts are not trusted or retained during this migration, so
  both the original partial Rosario snapshot and the later fail-closed v2
  attempt are revalidated;
- unchanged version-3 articles still reuse last-good verified facts with no
  detail read or model call.

This remains date-level completeness, not an attempt to invent or count acts
inside a date block. Todo Cultura and other official sources may still add
distinct same-day occurrences through the existing merge path. The generic
adapter remains text-first and adds no OCR, browser, dependency, daemon, or
scheduler.


## 26 September 2026 amendment: section-context evidence in scoped recovery

Production diagnostics of the scoped Rosario recovery showed that the model was
returning useful official facts, but the generic evidence validator rejected
most of them for structural reasons:

- detail sentences often inherit their date from the preceding explicit
  WordPress date heading, so the exact event quotation itself may not repeat the
  date;
- zero-padded morning times such as `08:00` and `06:00`, including
  `desde las 08:00`, were not accepted by the time-evidence matcher;
- the model sometimes prepended a parent programme heading such as
  `XLI Encuentro de Auroros:` even when that prefix was absent from the exact
  evidence quotation;
- the generic multi-month programme prompt did not tell recovery that all
  missing dates, including a September date in an October-heavy result, were
  required.

The scoped recovery contract now stays evidence-strict while accounting for
that source structure:

- recovery receives the already known missing dates explicitly in the model
  prompt and states that the schema `month` field must not limit a
  multi-month programme;
- date evidence may be inherited only when the exact `evidence_es` quotation
  is contained inside the deterministic WordPress section belonging to that
  same explicit date. Evidence from another date section cannot satisfy it;
- the time-evidence matcher accepts a zero-padded single-digit hour and the
  explicit Spanish form `desde las HH:MM`;
- only inside scoped Turismo recovery, an unsupported colon-prefixed parent
  title may be reduced to its evidence-supported suffix. Unsupported words are
  removed rather than trusted;
- all ordinary title, time, place, exact-quotation and final exact-date
  completeness checks remain in force.

The recovery budget remains one model call. No new source, browser, OCR,
scheduler, retry loop or persisted event type is added.


## 26 September 2026 amendment: bounded Ayuntamiento poster backstop

Production after the section-context repair still rejected the Rosario Turismo
article as incomplete. The municipal catalog remained healthy, but on
26 September it still contained only the 17:00 Bingo from Todo Cultura; the
official 19:50 traslado and 20:00 Santa Misa/presentation rows were absent.

Further retries against the same generic Turismo text would add complexity
without improving the source contract. The first-party Ayuntamiento news page
already exposes the Rosario programme article, and that article links one
event-specific official programme image containing the exact rows and times.
A separate backstop therefore reads the lightweight Ayuntamiento HTML index and
considers at most two recent current-year fiesta/feria-shaped articles.

The backstop remains text-first. If deterministic date-leading semantic blocks
exist in the article HTML, they use the same evidence-bound programme text
normalization and exact-date completeness checks. Only when that text is absent
or incomplete may the adapter use an image, and the image must satisfy all of
the following:

- same official Ayuntamiento host;
- under `/wp-content/uploads/`;
- supported image MIME/extension;
- programme-like filename (`prog` / `programa`);
- at least one non-numeric semantic filename token shared with the article
  title, preventing a generic year-only programme image from qualifying.

A changed/new event-specific poster is read twice independently. The two
validated readings must agree completely: the verified intersection must have
the same event count as each reading, otherwise the article remains fail-closed.
Within that complete agreement, occurrences match on date, start time and
sufficient title identity. Separately timed acts on the same date remain
separate occurrences. The poster may span multiple months; the
schema month field is compatibility metadata only.

The adapter stores only bounded per-article metadata and normalized future
facts. An unchanged semantic article fingerprint reuses last-good facts without
another image read or model call. Transient source/model failure retains a
compatible last-good article; a verified changed article with no current facts
supersedes old facts. No browser, generic arbitrary-image OCR, dependency,
daemon, scheduler, retry loop or new event model is introduced.
