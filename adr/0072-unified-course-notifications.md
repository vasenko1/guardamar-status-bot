# ADR 0072: Unified course notifications

- Status: Accepted
- Date: 2026-09-20

## Context

The linked guide now contains course and section facts from several independent
sources: Sporttia, Dinamización Social, the music school, the chess school and
the municipal literary group. Separate sports and recurring-activity
notification modules duplicated delivery state and made future sources require
new notification code.

The product requirement is one domain flow for all courses and sections, while
keeping source adapters independent and avoiding a generic notification
framework. Public messages should be short signals; the durable Telegram card
remains the source of full current information and the only route to external
registration/source links.

## Decision

- Replace the split sports/recurring notification modules with one
  `course_notifications.py` one-shot.
- Source adapters keep their own fetch/validation contracts. The notification
  module projects accepted `guide.json` snapshots into a small normalized
  course record. Adding a source requires only a source adapter plus this
  projection; delivery, grouping and state-machine code is reused.
- The notification process performs no source-network requests.
- Run the daily guide reconciliation at 09:02 Europe/Madrid. It clears a
  success marker before work and writes `last_successful_sync_day` only after
  the linked Telegram cards are reconciled successfully.
- Run course notifications at 09:42 with a same-day retry opportunity at
  11:42. A run with no pending work exits immediately.
- The first run is a silent baseline. A newly added source does not make all of
  its existing courses look new, although a fresh explicit same-day
  registration boundary may still produce its real date event.
- Public semantic message types are:
  1. registration closing today;
  2. registration opening today;
  3. registration-window changes;
  4. genuinely new courses/groups;
  5. other course changes (schedule, venue, audience/level, dates, season,
     participation conditions).
- Registration date events require a source snapshot observed on the current
  Europe/Madrid date. Semantic source diffs also require a fresh observation.
- The old three-days-before deadline reminder is removed. The date policy is
  exact opening day and exact final day. A one-day registration window emits
  only one opening/single-day message.
- `registration_until_full` never becomes an absolute "last chance" claim:
  the closing copy says the main registration period ends and places may still
  be available afterwards.
- New-course output is absorbed into an opening message when the same course
  opens registration that day.
- Disappearance from a source is silent and never means cancellation.
- Every public course name links only to an existing Telegram card in the
  group. Missing card state fails closed; there is no fallback to Sporttia,
  Google Forms, source pages or other external URLs.
- Dinamización workshops may share the aggregate
  `Муниципальные занятия и мастерские` card; no per-workshop Telegram-card
  hierarchy is created solely for notifications.
- Jardín Musical can use its explicit programme registration window. The
  general music-school matrícula is not attributed to a specific course unless
  a resident-facing card can represent that fact without overclaiming.
- One run may publish several semantic messages. Pending state therefore stores
  per-message `pending/uncertain/sent` status. Before each non-idempotent
  `sendMessage`, that item is persisted as `uncertain`. HTTP 429 restores
  only that item to `pending`; an ambiguous failure blocks automatic resend
  while already-sent sibling messages remain marked sent.
- A same-day pending batch is immutable. An unsent non-uncertain batch that
  survives into the next day expires rather than being delivered as stale
  date-sensitive news.
- Keep this domain state separate from transport notifications. Do not create a
  generic event bus, notification service, database, daemon or scheduler.

## Consequences

All current and future course sources share one delivery/state flow and one UX.
Multiple courses with the same semantic event are grouped into one message,
while unrelated meanings are not mixed. The phone adds no source request and
only two tiny local-json one-shots at the scheduled notification times.

The linked guide remains the full-information surface. Notification copy can
stay short and durable external URLs may change without making old
notifications unusable.
