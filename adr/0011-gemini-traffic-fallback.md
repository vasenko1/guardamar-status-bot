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
- Send bounded public page text and require up to four independent structured
  mobility measures. Each contains a supported action, exact Spanish evidence,
  Russian message, unchanged street names, active dates, and only applicable
  optional conditions.
- Publish only when application code proves the evidence occurs in the source,
  contains traffic-restriction language, includes every street unchanged,
  covers the current local date, exposes its date numbers, and produces at
  most 180 characters per measure. Publish at most two active measures.
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
