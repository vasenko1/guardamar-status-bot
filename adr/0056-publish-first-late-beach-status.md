# ADR 0056: Publish the first verified late beach status

- Status: Superseded by ADR 0064 on 2026-09-21
- Date: 2026-09-09

## Context

The morning digest may be sent before SafeBeach publishes usable flag data.
Previously, the first later observation silently became the monitoring
baseline. If the flags then stayed unchanged, subscribers never saw that
day's first available beach status.

## Decision

This confirmation-before-first-publication rule is superseded. During the
10:10–10:40 initial SafeBeach cycle, the first valid current response with at
least one verified flag creates the daily beach root immediately. Confirmation
remains required only for later operational changes after the initial cycle.

## Consequences

- A late first flag status is visible without treating it as an alert.
- One transient or incomplete source response cannot trigger a message.
- Later status changes keep the existing confirmation and change-message
  behaviour.
