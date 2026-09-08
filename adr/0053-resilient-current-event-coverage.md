# ADR 0053: Preserve current dated activities and official exhibitions

## Status

Accepted and implemented

## Context

On 8 September the Todo Cultura metadata response intermittently exceeded the
150 KiB transport limit, although the already bounded request contained at
most 100 compact records. The source also supplied a fully dated Centro Social
Juvenil programme which a title-only exclusion discarded. Separately, the
official Turismo agenda clearly listed current exhibition ranges, but the
optional structured reader could omit them or return only invalid candidates.

## Decision

- Keep the existing single metadata request, 100-record maximum and strict
  response validation, but raise its byte ceiling to 300 KiB. This changes no
  request frequency, candidate count, model budget or stored history.
- Retain a one-day Centro Social Juvenil occurrence when the source provides an
  explicit date, time and place. The existing rule still rejects unsupported
  multi-day non-exhibition ranges and one-day rows explicitly classified as a
  routine municipal service.
- Deterministically recover exhibition title, explicit date range and venue
  from the `EXPOSICIONES` section of the official Turismo text agenda. Merge
  these official facts with structured results, and use them as a partial
  fallback if every structured candidate is invalid.
- Increment the official-text extractor version so an existing phone snapshot
  is refreshed once after deployment.

## Consequences

The phone uses at most an additional 150 KiB of transient memory during the
same one-shot request and performs no extra network call. Current exhibitions
no longer depend entirely on model completeness. Concrete youth activities
can appear in the digest, while vague ranges and explicitly routine service
rows remain excluded.
