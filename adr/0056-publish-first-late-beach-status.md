# ADR 0056: Publish the first verified late beach status

- Status: Accepted
- Date: 2026-09-09

## Context

The morning digest may be sent before SafeBeach publishes usable flag data.
Previously, the first later observation silently became the monitoring
baseline. If the flags then stayed unchanged, subscribers never saw that
day's first available beach status.

## Decision

When there is no existing beach baseline, treat the first usable flags as an
initial status. Confirm it with the next scheduled sample before delivery.
Publish a compact status without change arrows, then store it as the normal
baseline. If confirmation is unavailable, publish nothing and wait for a new
confirmed observation.

## Consequences

- A late first flag status is visible without treating it as an alert.
- One transient or incomplete source response cannot trigger a message.
- Later status changes keep the existing confirmation and change-message
  behaviour.
