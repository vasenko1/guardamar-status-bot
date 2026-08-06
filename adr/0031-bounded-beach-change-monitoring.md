# ADR 0031: Bounded beach safety change monitoring

- Status: Proposed
- Date: 2026-08-06

## Purpose

Add a quiet, bounded follow-up monitor for material beach-safety changes after
the daily beach section has been published. The monitor is not a real-time
emergency service and does not replace lifeguard instructions, beach signage,
or official closure notices.

This document defines the product concept and implementation boundaries. It
does not authorize implementation by itself.

## Scope

The monitor runs only when all of these conditions are true:

- the local date is inside the accepted beach season, from 20 June through
  14 September, inclusive;
- the beach service is operating at the time of the check;
- the check is one of the bounded scheduled invocations defined below.

Monitor every valid, active Guardamar beach returned by the municipality-linked
SafeBeach page. ADR 0032 also retains all six known zones for the daily digest,
so the later full digest can become the monitor's complete baseline without a
second selection policy.

The monitor runs even when the morning digest had no beach section. A source
failure then costs only one bounded request: it produces no group message and
does not alter known state.

## Service hours and initial schedule

The official Guardamar lifeguard specification describes these normal service
hours:

- June and September: 11:00–19:00 on the staffed beaches;
- July and August: 10:00–20:00 on the staffed beaches.

The Ayuntamiento may change operational days or hours. To keep the first
version simple, start one hour after the service opens and check every two
hours. The last window starts one hour before the published closing time:

- 20–30 June and 1–14 September: 12:00, 14:00, 16:00, and 18:00;
- July and August: 11:00, 13:00, 15:00, 17:00, and 19:00.

Each window has a scheduled confirmation opportunity five minutes later. It
makes a second SafeBeach request only when the primary check stored a candidate
change; otherwise it exits after reading local state. These are short scheduled
invocations, not a resident polling process. The primary final check therefore
runs one hour before the published closing time.
The schedule can be changed later from cron after observing actual update
behavior; it must not expand into continuous polling.

Source checked on 2026-08-06:
`https://www.guardamardelsegura.es/wp-content/uploads/2023/10/20231005_9-PROYECTO-DE-GESTION-SOCORRISMO-PLAYAS.pdf`

## Daily baseline

Use the later full digest's beach data as the first baseline when available.
Otherwise, the first valid monitoring response of the day creates the baseline
without treating newly available flag information as a change. An explicit
jellyfish-positive value remains a safety candidate and follows the normal
two-sample confirmation rule. Save:

- local date;
- identifier of the current full digest message, when one exists;
- every valid, active Guardamar beach observed that day;
- last explicit valid flag color for each beach;
- last explicit valid jellyfish state for each beach, when the source provides
  one.

A beach first observed later in the day is added silently with its current flag
as that beach's baseline. The appearance of its record or flag information is
not an urgent transition. An explicit jellyfish-positive value is handled as a
candidate, not silently discarded. Subsequent explicit changes are monitored
normally. Confirmed safety values advance as notifications are published.

A missing beach record, missing field, stale page, invalid response, or source
failure is an unknown value. It never overwrites the last explicit valid
state.

## Changes that generate a notification

Only confirmed transitions for an observed Guardamar beach qualify:

1. a non-red flag changes to red;
2. a red flag changes to an explicit current yellow or green flag;
3. SafeBeach explicitly reports jellyfish present, including the first valid
   observation of that hazard that day;
4. a jellyfish-present state changes to an explicit no-jellyfish state.

The following are not urgent updates and produce no group message:

- a beach record or flag field appears after being unavailable at the start of
  the day; its current flag becomes the silent baseline;
- a beach record or flag field disappears;
- a green flag changes to yellow or yellow changes to green;
- a timestamp, sea temperature, wind, wave, or other descriptive field changes;
- an unknown jellyfish state becomes explicitly negative.

This distinction prevents data availability from being mistaken for a safety
transition.

## Confirmation and false-positive protection

Every candidate transition must be present in both samples of the same
five-minute window:

1. the first check stores a pending candidate but sends nothing;
2. the confirmation check must return the same explicit new state;
3. only then is the notification published and the saved state advanced.

If either request fails, the beach disappears, fields become unknown, or the
two samples disagree, the candidate is discarded without changing the known
state. A later window may detect it again.

Missing data must never mean that a red flag was removed or jellyfish
disappeared. A red-flag removal requires an explicit current yellow or green
flag. Jellyfish disappearance requires an explicit negative source value.

## Telegram delivery

Confirmed changes from the same window are combined into one compact message.
The message is sent as a reply to the current full daily digest so that the
context is preserved and subscribers receive a normal notification. The
original digest is not silently edited. If no usable daily message identifier
was saved, send the safety update as a standalone group message rather than
discarding it.

Recommended wording:

```text
🔴 Изменение на пляжах
На Roqueta поднят красный флаг — купание запрещено.

Источник: SafeBeach · 13:05
📣 обЪявления Гуардамар
```

```text
🏖 Изменение на пляжах
На Roqueta красный флаг заменён на жёлтый.

Источник: SafeBeach · 17:05
📣 обЪявления Гуардамар
```

```text
🪼 Изменение на пляжах
SafeBeach отмечает медуз на Roqueta.

Источник: SafeBeach · 13:05
📣 обЪявления Гуардамар
```

Do not write that an official restriction has been lifted merely because a
red flag changed. A separate sanitary or municipal prohibition may still be
active.

## State and duplicate prevention

Use one small, atomically replaced JSON state file. It contains only:

- the local date and full-digest message identifier, when one exists;
- all Guardamar beaches observed so far that day;
- last explicit valid flag and jellyfish states;
- a pending first-sample candidate and timestamp;
- fingerprints of notifications already sent that day.

Reset the state on the next local date. Do not store raw HTML, build a status
history, or add a database. Repeated cron invocations and service restarts must
not resend an already published transition.

## Failure behavior

- SafeBeach transport, schema, type, date, or validation failures remain
  silent in the group.
- A failure does not clear pending known safety state or manufacture a change.
- The monitor does not retry internally; the paired scheduled invocation is
  the only confirmation request.
- Operator diagnostics may be written to the local log. Private bot feedback
  can be considered separately and is not required for the first version.

## Runtime and source load

The normal design adds four SafeBeach requests on an eligible June/September
day and five on a July/August day. A second request is added only for a detected
candidate, giving a theoretical maximum of eight or ten requests when every
window observes a possible change. Together with the existing bounded morning
checks, this remains a small load and requires no new dependency, browser,
daemon, or extra AEMET request. The public source has no published numerical
quota, so requests must remain conditional, non-concurrent, and free of
internal retries.

## Acceptance criteria

- No monitoring request runs outside 20 June–14 September.
- No monitoring request runs outside the scheduled service-hour windows.
- Monitoring can establish a silent baseline when the morning beach section
  was absent.
- Every valid active Guardamar beach returned by SafeBeach can be monitored.
- A newly observed beach or flag is enrolled silently and does not generate a
  flag notification.
- Availability changes and green/yellow transitions never notify the group.
- Red-flag and explicit jellyfish transitions require two matching samples.
- A confirmation invocation makes no network request when no candidate is
  pending.
- Missing or invalid data never clears a known red flag or jellyfish state.
- Multiple confirmed transitions in one window produce one message.
- The same transition is not sent twice after retries or restarts.
- State is reset by local date and written atomically.

## Out of scope

- continuous or minute-by-minute monitoring;
- treating SafeBeach as an emergency alert system;
- monitoring ordinary flag changes, weather, waves, or sea temperature;
- merging AEMET, Policía Local, mayoral, or sanitary alerts into this monitor;
- notifications caused only by source recovery or data loss.

Official urgent notices from the Ayuntamiento, mayor, Policía Local, or health
authority can be designed as a separate source-specific feature. They must not
be inferred from a SafeBeach data gap.

## Consequences

- Subscribers receive only high-value changes with a low false-positive rate.
- The phone performs a small, predictable number of network requests.
- A real change may be reported after the next two-hour window and changes
  outside service hours may not be reported. This is an intentional tradeoff
  for low noise, low load, and source reliability.
- If this proposal is accepted for implementation, the architecture,
  features, runtime constraints, roadmap, and decision log must be updated.
