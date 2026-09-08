# ADR 0054: Make every AEMET update a self-contained current status

## Status

Accepted and implemented; amends the presentation rule in ADR 0031

## Context

Operational updates retained useful history, but a cancellation message first
repeated the complete active-warning layout and then appended one heading per
cancelled interval. Read next to the morning digest and earlier replies, this
could look as though the same warning was both active and cancelled.

## Decision

- Render one AEMET update heading and one affected-zone row per message.
- Group known cancellations by their target day and show them first.
- Say that AEMET cancelled a warning, never imply that the weather itself was
  cancelled.
- Follow cancellations with the complete currently active, displayable set
  under `Сейчас действует`.
- When the valid current set is empty, state that no other active warning
  remains. If an unknown current label cannot be rendered safely, omit that
  conclusion rather than claiming there are no warnings.
- Keep sending a new reply for a material change so Telegram produces a timely
  notification; prior messages remain an audit trail.

## Consequences

The newest message can be understood without reconstructing earlier replies.
No source requests, schedules, state fields, dependencies, or delivery rules
change.
