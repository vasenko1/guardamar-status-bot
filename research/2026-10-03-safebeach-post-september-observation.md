# SafeBeach activity after September

Checked 2026-10-03.

> Historical note (2026-10-10): the 15 October guard and four-window October
> cadence recorded below were superseded by ADR 0106 after later service-horizon
> evidence and a production late-start observation. The 3 October source
> observation itself remains valid evidence.

## Question

Does Guardamar's public SafeBeach source still publish current operational
beach data after the bot's former 30 September request cutoff?

## Observation

The public Guardamar SafeBeach page was still live on 3 October 2026. It
showed a same-day operational flag for Platja Centre / Babilònia with a
10:00 update time, while several other Guardamar zones were waiting for beach
data rather than exposing a carried-forward summer value.

This is enough to reject 30 September as a reliable internal cutoff for
SafeBeach requests. It does **not** prove that all Guardamar beaches remain
staffed, that the same subset is active every day, or that 15 October is an
official lifeguard-season end date.

The earlier source review remains applicable: Guardamar beach services use
different calendars, so SafeBeach must stay an independent operational source
and its current records must be validated directly.

## Product consequence

Use a fixed lightweight request guard rail rather than a universal public
"beach season":

- query SafeBeach only from 1 June through 15 October, inclusive;
- use the reduced later-day shoulder cadence during 1-15 October;
- make zero scheduled SafeBeach requests from 16 October through 31 May;
- keep current-date, current-time, active-service and ended-service validation
  unchanged;
- do not add dynamic season detection, background probing or winter heartbeat
  state.

The decision made from this observation was recorded in ADR 0094. It was
superseded on 10 October 2026 by ADR 0106, which moves the internal guard
through 31 October and adds bounded October late-start recovery checkpoints
without changing the meaning of any official municipal season.

## Sources

- Guardamar SafeBeach public page:
  `https://info.safebeach.es/guardamar-del-segura/listado?lng=cas`
- Ayuntamiento Guardamar public site, which exposes the beach-status entry:
  `https://www.guardamardelsegura.es/`
- Prior lifecycle review:
  `research/2026-09-21-dynamic-beach-service-sources.md`
- Prior service-calendar review:
  `research/2026-07-28-guardamar-beach-season.md`