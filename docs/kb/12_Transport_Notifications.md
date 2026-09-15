# Transport Change Notifications

## Purpose

Publish one calm, user-facing Telegram message when the already accepted
transport data changes in a way the bot can prove. This workflow is separate
from road closures, mobility measures, emergency disruptions, and the pinned
transport guide itself.

## Schedule and flow

The existing 05:00 `sync-transport` remains the source of accepted transport
data. After that sync succeeds, a short collector reads the accepted urban and
airport state and writes only a small normalized notification baseline/pending
record. A separate one-shot publisher runs at 12:30 Europe/Madrid and sends at
most one aggregated message when a same-day pending change exists.

The first collector run is bootstrap-only: it records current baselines and
publishes nothing. A same-day pending message that is not published at 12:30
expires on the next morning rather than being replayed late.

## Evidence boundaries

### Urban lines 1 and 2

The municipal source is an official PDF. The existing transport sync already
requires a stable changed PDF and renders it to a one-page PNG. Notification
logic compares the accepted rendered-image hash. A PDF hash change with the
same rendered image is silent.

A changed image proves that the published timetable changed visually, but it
does not prove which departure, stop, route, or calendar rule changed. Public
copy therefore says only that the municipality published a new timetable. It
never invents a semantic diff and does not list route stops in the change
message.

### Airport departures

Bus Sigüenza provides structured departures for an exact service date. To avoid
mistaking normal weekday/weekend differences for a timetable revision, the
collector fetches tomorrow's schedule once after the 05:00 sync and stores only
its normalized departure arrays. The next morning it compares that baseline
with the accepted schedule for the exact same service date.

Only then may the public message name added or removed departure times. If the
next-day baseline could not be obtained, that day's exact departure-change
notification is skipped rather than inferred.

### Airport fare

The existing parser intentionally extracts only `TARIFA BASE GENERAL` for
Guardamar del Segura to Aeropuerto. Notifications therefore describe only the
standard ticket (`обычный билет`). Card, pass, senior, discount, or other fare
classes are not parsed, inferred, or mentioned.

The parsed effective date controls the wording: a future tariff says when the
new price will start; an already effective tariff says the standard ticket now
costs the new amount.

## Public format

Every message starts with:

`🚌 Транспорт · изменения`

The body uses normal editorial sentences, minimal bold text, and no warning
icons for routine updates. Multiple supported changes are combined into one
message. The closing sentence links to the existing pinned `Транспорт` section,
and the standard shared `обЪявления Гуардамар` footer is appended through the
common branding helper.

## Delivery safety

The workflow keeps one small atomic JSON state and uses a local exclusive lock.
Before a non-idempotent Telegram send, delivery is marked `uncertain`. An
ambiguous send result is not retried automatically, preventing duplicate public
posts after a crash or lost response. An explicit Telegram rate-limit rejection
remains eligible for a later retry because the message was not accepted.

No daemon, database, browser, OCR, continuous polling, or new external service
is introduced. The only additional source request is one bounded Bus Sigüenza
planner request each morning for the following day's airport baseline.

See `adr/0065-transport-change-notifications.md` for the durable decision.
