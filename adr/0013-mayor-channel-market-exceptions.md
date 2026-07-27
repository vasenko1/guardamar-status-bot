# ADR 0013: Mayor channel market exceptions

## Status

Accepted and implemented

## Context

The Wednesday market has a stable official schedule, but individual dates can
be cancelled or moved. A calendar rule alone can therefore publish misleading
information.

## Decision

- Read the bounded public HTML preview of `@AlcaldeGuardamar` only during a
  Wednesday morning run.
- Consider only timestamped text posts from the previous seven days.
- Call Gemini only when a fresh post contains a market-related term.
- Hide the market only when Gemini returns an exact source quotation, an
  explicit cancellation or move, and the exact local market date.
- Do not store posts, translations, or model output.
- If the channel or required validation is unavailable, omit the market for
  that day. Silence is safer than asserting an unverified occurrence.

## Consequences

The normal path adds one small public-page request on Wednesdays and usually
no Gemini request. Explicit exceptions suppress the event without adding a
collector, cache, database, or background process.
