# ADR 0016: 10:07 publication time

## Status

Accepted and implemented

## Context

The 07:30 digest runs before the high-season lifeguard service begins.
SafeBeach therefore usually has no active current-day flag at collection time.
The first message should preferably include the current Platja Centre flag,
while remaining useful and publishable when SafeBeach is late or unavailable.

## Decision

- Invoke the one-shot Morning Digest at `10:07` in `Europe/Madrid`.
- Collect SafeBeach once during that same run, exactly like every other
  approved source.
- Include the flag only when SafeBeach exposes an active, non-ended Platja
  Centre record.
- Continue publishing valid weather and other sections when no active flag is
  available.
- Do not wait, retry SafeBeach in the background, send a second digest, or edit
  the published message as part of this decision.

## Consequences

The first and only daily message is substantially more likely to contain the
current beach flag. Publication is later in the morning, and a delayed
SafeBeach update may still result in a message without a flag. The existing
optional-source failure policy already handles that outcome safely.

## Supersedes

Only the `07:30` time in ADR 0008 is superseded. Its one-shot execution,
success-only state, failure policy, and external scheduling decisions remain
in force.
