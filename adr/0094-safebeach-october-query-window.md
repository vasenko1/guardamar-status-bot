# ADR 0094: Bound SafeBeach requests through 15 October

- Status: Accepted
- Date: 2026-10-03
- Supersedes: the annual SafeBeach query-window parts of ADR 0031

## Context

The previous operational guard rail allowed SafeBeach requests only from
1 June through 30 September. That boundary was deliberately conservative and
was not an official universal Guardamar beach-season date.

On 3 October 2026, the public Guardamar SafeBeach page still exposed a current
same-day active beach record with an update time. A hard 30 September cutoff
therefore drops useful live operational data. At the same time, querying
SafeBeach throughout late autumn, winter and spring would add recurring network
work with no demonstrated resident value.

The project already treats SafeBeach as an independent operational source whose
records must be current, active and not ended. It does not need a dynamic
season detector or a universal lifeguard-season model.

## Decision

- Allow scheduled SafeBeach requests from 1 June through 15 October,
  inclusive.
- From 16 October through 31 May, scheduled update and operational-monitor
  invocations make no SafeBeach request.
- During 1-15 October, later operational SafeBeach monitoring uses the same
  reduced four-window cadence used at the seasonal shoulders: 12:00, 14:00,
  16:00 and 18:00, with five- and ten-minute confirmation calls only while a
  candidate change is pending.
- Keep the existing AEMET warning cadence unchanged; extending SafeBeach into
  October must not move unrelated AEMET checks.
- Keep every existing freshness, local-date, active-service and per-record
  validation rule unchanged. Missing or stale records are never carried
  forward as current.
- Do not add automatic season discovery, a background probe, extra state or a
  winter heartbeat. Future evidence may justify changing this fixed guard
  rail, but that is a separate decision.

## Consequences

- The bot covers the observed early-October SafeBeach activity instead of
  stopping on 30 September.
- SafeBeach network cost remains bounded to an additional 15 calendar days,
  with the lower four-window later-day cadence.
- Winter and spring retain zero scheduled SafeBeach HTTP requests.
- The Morning Digest remains independent of SafeBeach.
- No dependency, daemon, state schema or retry loop is added.

## Acceptance criteria

- 15 October 23:59 Europe/Madrid is inside the SafeBeach query window.
- 16 October 00:00 Europe/Madrid is outside it.
- October SafeBeach operational checks use the reduced 12:00/14:00/16:00/18:00
  primary cadence.
- October AEMET warning checks retain their existing 11:00/15:00/19:00 cadence.
- The managed Termux cron block schedules the October SafeBeach shoulder
  invocations needed by the runtime.
- No SafeBeach request is made from 16 October through 31 May.
