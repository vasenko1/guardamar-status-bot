# ADR 0102: Local clock-change notices

Date: 2026-10-05

## Status

Accepted.

## Context

Guardamar residents benefit from a short reminder before mainland Spain changes
its civil clock and from a confirmation in the following Morning Digest. The
bot already has a daily 18:00 next-day celebration/holiday publisher with
crash-safe dated delivery state and a 07:30 Morning Digest. Adding a remote
calendar source, a second state machine, or a dedicated scheduler would add
cost for a fact that the installed Europe/Madrid timezone database already
contains.

Spanish Real Decreto 236/2002 defines the current mainland transition as the
last Sunday of March at 02:00, advanced by sixty minutes, and the last Sunday
of October at 03:00, delayed by sixty minutes. Runtime code should nevertheless
follow the installed Europe/Madrid timezone rules rather than duplicate those
calendar dates, so an eventual tzdata rule change can propagate without a
hardcoded annual table.

## Decision

- Add one pure local clock-change fact derived from `ZoneInfo("Europe/Madrid")`.
- Compare the UTC offset at consecutive local midnights. Ordinary days return
  immediately. Only a day whose offset changes is scanned minute by minute in
  UTC to recover the exact before/after wall-clock labels.
- The day-before notice reuses the existing 18:00 `celebration-alert`
  command, Telegram delivery reservation and state file. The command name and
  state path remain unchanged for compatibility.
- The day-of confirmation is calculated before rendering and passed as one
  optional `MorningDigest.clock_change` fact to the existing 07:30 digest.
- A clock change and a holiday/celebration due on the same date are combined
  into one 18:00 Telegram publication.
- Add no runtime HTTP request, AI call, cache, daemon, dependency, new cron or
  new persistent state.
- Do not schedule work inside the skipped/repeated transition hour.
- Keep the existing one-shot availability contract: if the phone is offline at
  18:00, the pre-day notice can be missed; the independent 07:30 Morning Digest
  still carries the day-of fact. A permanent extra daily retry is not justified
  for two transitions per year.

## Consequences

On the 363 ordinary days of a typical year, the check is two local offset
lookups. On a transition day the bounded minute scan performs roughly one day's
worth of in-memory datetime conversions and no I/O. The feature follows the
same delivery safety and operational failure modes as the existing calendar
notice rather than creating a parallel lifecycle.

The legal source documents the resident meaning of the transition; the runtime
source of truth for actual wall-clock behavior is the installed Europe/Madrid
timezone data.
