# ADR 0013: Mayor channel market exceptions

## Status

Accepted and amended — 2026-10-05

## Context

The Wednesday market has a stable official schedule, but individual dates can
be cancelled or moved. A calendar rule alone can therefore publish misleading
information. The same risk applies when the existing next-day planning message
announces tomorrow's scheduled municipal market.

## Decision

- Read the bounded public HTML preview of `@AlcaldeGuardamar` only when the
  bot is about to assert a deterministically scheduled La Redonda market:
  same-day in the Morning Digest or on the previous evening in
  `Завтра в Гуардамаре`.
- Keep source freshness tied to the actual observation time; pass the market
  date separately when the check is for tomorrow.
- Consider only timestamped text posts from the previous seven days.
- Call Gemini only when a fresh post contains a market-related term. A missing
  AI key therefore does not block the no-relevant-post path.
- Classify the target date, not the word "move": a move **from** the target date
  suppresses it, while a move **to** the target date does not.
- Hide the market only when the classifier returns an exact source quotation,
  an explicit cancellation or move away, and the exact local market date.
  Invalid classifier output is a source failure, not "not cancelled".
- Keep the shared `planning_events` loader local-only. Tomorrow Events applies
  this narrow market exception after it has loaded and merged local planning
  facts; the Mayor/AI dependency does not become a generic planning dependency.
- Do not store posts, translations, or model output.
- If the channel or required validation is unavailable, omit only the market;
  unrelated verified events remain eligible.

## Consequences

The ordinary path adds no collector, cache, database, background process, new
cron, new source, or new state. A bounded Mayor-page request occurs only when a
scheduled municipal market is about to be published: on the market morning and,
for the next-day planning feature, on the preceding evening. Gemini is still
skipped unless fresh market-related text exists.
