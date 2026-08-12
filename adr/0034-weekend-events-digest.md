# 0034: Friday-evening weekend events digest

- Status: Accepted
- Date: 2026-08-12

## Context

The Morning Digest looks only at the current day, so weekend plans reach
readers only on the day itself. The 2026-08 product review
(`research/2026-08-12-product-review-and-growth.md`) identified a
forward-looking weekend view as the highest-value addition that requires no
new source: both bounded local event catalogs already store dated events up
to 45 days ahead, and the recurring-market rules are pure local calendar
logic. The feature-slot rule in `docs/kb/05_Features.md` requires an explicit
decision before adding a product feature.

## Decision

Add one optional Friday-evening publication, «Афиша выходных», built only
from the two existing normalized catalogs plus the recurring market rules:

- One short-lived `weekend` command collects Saturday and Sunday events by
  reusing the date-parameterized catalog readers, merges and deduplicates
  them with the existing `_merge_events` rules, and renders each day with the
  shared bounded event-section renderer extracted from the Morning Digest.
- No new network source is consulted. The Mayor channel, SafeBeach, AEMET,
  and Policía Local are not part of this message.
- Missing translations for weekend titles are prepared inline through the
  existing bounded policy-versioned cache; a Gemini outage degrades titles to
  normalized Spanish exactly as in the morning flow.
- An empty verified weekend produces no message.
- Publication is guarded by one small atomic state file
  (`state/weekend.json`) keyed to the target Saturday, with the same
  non-blocking lock and success-only marker pattern as the electricity
  feature. External Termux cron runs Friday `18:00` with bounded retries at
  `18:20` and `19:00`; a confirmed success makes later invocations no-ops.
- `weekend-preview` prints the message without Telegram or state changes.

## Consequences

- Benefits: forward-looking value from data the bot already maintains; zero
  new sources; at most two additional bounded translation batches per week,
  leaving Gemini free-tier usage unchanged in practice.
- Costs: one more cron row, one more small state file, and a second consumer
  of the event renderer that morning-layout changes must keep in mind.
- Follow-up: observe whether Saturday-morning readers need a repeat and
  resist adding one without evidence.

## Alternatives considered

- Extending the Friday morning digest with a weekend block — rejected: it
  would grow the canonical one-screen morning layout and mix time horizons.
- A rolling seven-day agenda — rejected: violates the short-message
  principle and duplicates the official monthly sources wholesale.
