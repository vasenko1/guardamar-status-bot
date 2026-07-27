# ADR 0011: Gemini traffic translation fallback

## Status

Accepted

## Context

Policía Local publishes irregular Spanish traffic notices without a stable
schema. Full automation needs Russian compression for new formats, but a model
must not invent or decide safety facts. The core digest must continue without
AI or when a free quota is unavailable.

## Decision

- Keep deterministic parsers first; known notices never call a model.
- For an unknown freshly fetched official traffic page, optionally call the
  pinned stable `gemini-3.5-flash-lite` model using `GEMINI_API_KEY`.
- Send bounded public page text and require a strict JSON schema containing an
  exact Spanish evidence quotation, Russian message, unchanged street names,
  and start/end month and day.
- Publish only when application code proves the evidence occurs in the source,
  contains traffic-restriction language, includes every street unchanged,
  covers the current local date, exposes its date numbers, and produces at
  most 180 characters.
- On missing key, quota, timeout, invalid response, ambiguity, or failed
  validation, omit the traffic section.
- Do not use Gemini for any other digest section.

## Consequences

The bot can safely handle some new official notice formats without manual
translation. The Gemini API becomes one optional network dependency, but
weather and all existing deterministic behavior remain independent. Free-tier
availability is not assumed.

## Alternatives rejected

- Automatically trust translated prose: unsafe for dates and closures.
- Send every known notice to Gemini: wastes quota and reduces determinism.
- Run a local model: too heavy for the target Android device.
