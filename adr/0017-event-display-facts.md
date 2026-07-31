# ADR 0017: Event display facts

## Status

Accepted and implemented

## Context

An event title alone may not explain what the activity is, where it happens,
or when a user can attend. The monthly poster contains some of these facts,
but the first extraction contract could discard an end time or an explicit
medium such as painting or sculpture.

## Decision

- Format timed events as `{time or range} — {type and title}, {place}`.
- If the official source gives no time, show the event without a time prefix.
- Preserve an explicit activity type or medium in the translated title.
- Preserve an explicit start and end time.
- Include the official place when available.
- Never infer a missing time, type, medium, or place.

## Consequences

The event section remains compact but carries the actionable facts available
in the source. It is not limited to two lines. An unchanged existing poster
keeps its prior valid snapshot; the richer extraction contract applies when
the official poster changes. Events without a published time remain eligible
and are not falsely labelled as all-day.
