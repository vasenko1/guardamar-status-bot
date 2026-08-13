# 0039: Reviewed corrections and translations as one validated data file

- Status: Accepted
- Date: 2026-08-12

## Context

Every monthly poster review previously required editing Python:
`_apply_reviewed_corrections` carried reviewed occurrences and the
known-bad-OCR title filter as code, `_apply_reviewed_daily_schedules`
hardcoded day-of rules, and `event_translations` embedded the reviewed
Russian titles. The 2026-08 product review identified this as the largest
recurring maintenance cost — the August retirement of expired July entries
was a multi-file code change for what is conceptually a data update.

## Decision

- One reviewed data file, `src/telegrambot/reviewed.json`, ships inside the
  package (declared package data) and holds the three data-shaped parts of
  the correction pipeline: exact normalized-title Russian translations,
  per-poster reviewed occurrences with their drop filter (gated on the
  exact poster filename and official upload path), and bounded day-of
  schedule rules (`match` substrings, equality `requires` with a `today`
  sentinel, optional weekday/saturday/sunday visit windows where `null`
  omits the day, and a whitelisted `set` of replacement fields).
- `reviewed.py` validates strictly at load — types, ISO dates, real
  zero-padded `HH:MM` times, bounded lengths, no unknown fields, and no
  boolean smuggled in where a number or flag is expected. A structural
  failure rejects everything, but each section is validated independently
  so one defect stays contained: a translation typo must never switch off
  a poster's known-bad-OCR filter.
- Rejection is fail-closed per section rather than merely skipped. When a
  poster's data cannot be read, its drop filter is unavailable, so
  poster-only events are withheld — they cannot be told apart from the
  rows the filter exists to remove — while text-corroborated facts
  survive. When schedules cannot be read, uncorrected source facts stand.
- The committed file itself is a test subject: the suite validates it on
  every run, so a malformed data commit fails CI and never reaches the
  device. Monthly poster review becomes a data-only commit.
- Genuinely conditional logic (detail inheritance, merge precedence, date
  filtering) stays in code; the file holds facts, not behavior.

## Validation obligations

Because a data-only edit reaches published output without a code review,
the loader refuses anything it would otherwise resolve by defaulting:

- unknown *and* missing keys at every object level, so neither a typo nor
  a deletion can silently disarm the field it was meant to set. An
  explicit empty list stays valid, because it states an intent that an
  absent key cannot;
- duplicate JSON keys, which the parser would resolve to the last one and
  quietly discard the earlier definition;
- match and drop substrings shorter than three characters or carrying
  surrounding whitespace, because a substring that short selects nearly
  every title — one stray space in a drop clause empties the whole event
  section, and in a match term it rewrites every event;
- a schedule rule with no `requires`, which would apply on every date;
- a rule that assigns hours while also declaring `weekday_windows`, since
  the window is applied last and would silently win;
- an occurrence whose end date precedes its start, which would match no
  day and disappear without complaint.

A deliberate limitation: a plausible-but-wrong year such as `2062` still
validates. It fails silent — the occurrence simply never renders — and any
bound would be arbitrary, so it is left to the annual review rather than
encoded as a rule the file cannot justify.

## Consequences

- Benefits: monthly review edits one JSON file; expired entries are
  deleted as data; CI guards the format; the correction pipeline's tests
  keep running against the interpreters, so behavior parity is enforced.
- Costs: a small schema to know (documented by the validators and the
  shipped example), and one more packaged file.
- Follow-up: the Mayor channel's small reviewed-title map added by ADR
  0034 is a candidate for the same file once it grows past a couple of
  entries.

## Alternatives considered

- A general correction DSL in JSON — rejected: encoding arbitrary logic in
  data recreates the maintenance problem with worse debuggability; the
  current rule shapes cover every observed correction.
- Loading corrections from `state/` at runtime — rejected: corrections are
  reviewed content that must travel through CI and deploy like code, not
  operator-mutable device state.
