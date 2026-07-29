# ADR 0022: Structured mobility measures

## Status

Accepted

## Context

One official traffic document can contain several periods and simultaneous
effects: closures, access conditions, parking restrictions, lane occupation,
vehicle exceptions, diversions, or public-transport changes. Treating the
whole document as one prose notice lost important facts and produced an
incorrect route for the July festival restriction.

## Decision

- Normalize an official notice into independent active mobility measures.
- Each measure records an action, location, validity dates, and only the
  applicable optional hours, affected users, exceptions, alternative route,
  and destinations.
- Select measures active on the current local date before rendering at most
  two compact lines.
- Preserve street and route names exactly; never infer missing effects.
- Recognize the reviewed festival PDF by its official link and SHA-256. From
  22–29 July it renders the verified Molivent closure and both documented
  access routes. A changed document fails closed until reviewed again.
- For unknown official HTML notices, Gemini may return up to four structured
  measures. Each requires an exact source quotation, explicit active dates,
  unchanged street names, a supported action, and a Russian line of at most
  180 characters. Application code validates and publishes at most two.
- Do not add a PDF parser, OCR dependency, cache, polling job, or database.

## Consequences

The current restriction is accurate and future HTML notices can express
multiple effects without a generic traffic subsystem. Unknown PDFs still
require review; this preserves the existing fail-closed policy and keeps the
Termux runtime small.

## Alternatives rejected

- One document type or one prose summary: cannot represent simultaneous or
  date-dependent measures faithfully.
- A comprehensive transport model: unnecessary for a short city digest.
- Runtime PDF/OCR stack: adds device cost and weakens deterministic evidence
  validation.
