# ADR 0078 — Lightweight blood-donation alert and same-day event

Date: 2026-09-24
Status: Accepted

## Context

The Centro de Transfusión de la Comunitat Valenciana publishes the Alicante
blood-donation programme as a small public HTML table. Guardamar rows include
the exact date, venue and opening hours needed by residents.

The useful product behavior is intentionally narrow:

- tell the group on the previous afternoon so people can plan;
- repeat the fact only once more as a normal event in the Morning Digest on the
  actual donation day.

A browser, PDF parser, AI extraction, frequent polling, database or new service
would add cost without improving those two uses.

## Decision

Use the direct official Alicante HTML endpoint:

`https://oficina20.san.gva.es/gportal-ctcvcol-portlet/listaColectas.jsp?provincia=0007`

The existing morning publication lifecycle checks only the timestamp of the
last successful blood-donation snapshot. It performs one bounded HTTPS GET only
when at least seven local calendar days have elapsed (or no snapshot exists).
The adapter parses ordinary table text with the Python standard library,
filters exactly `GUARDAMAR DEL SEGURA`, rejects malformed rows and ignores
rows marked `SUSPENDIDA`.

Only normalized current/future Guardamar sessions are stored in the small atomic
`state/blood_donation.json`; raw HTML and province-wide rows are never cached.

The weekly snapshot is discovery state, not publication authority. At 16:45
`Europe/Madrid`, the short-lived alert command first checks local state. If
there is no known Guardamar session tomorrow, it exits without a source
request. If tomorrow is known, it performs exactly one fresh bounded control
GET and sends the standalone alert only if that current response still contains
the session. A cancellation, disappearance or date change suppresses the
message; changed hours or venue are taken from the fresh response.

The successful 16:45 control GET replaces the same normalized snapshot. The
Morning Digest may show today's session only when that snapshot was observed
today or on the previous local calendar day. This lets the next morning reuse
the confirmed 16:45 facts while preventing an older weekly discovery snapshot
from becoming a public same-day event by itself.

The alert window is bounded to 16:45–17:59. Missed alerts are not replayed later
that evening or on the event day. The snapshot stores only one `alerted_for` date to prevent duplicate delivery.
A definite Telegram send failure clears that date; an ambiguous send keeps it
to avoid an automatic duplicate.

For the reviewed Guardamar venue `Centro Sanitario Integrado (зона педиатрии)`,
both the alert and digest use the exact operator-provided Google Maps link:
`https://maps.app.goo.gl/DXW3LqEmCNCjf9JX8`.

No street address or source footer is added to the public message.

## Consequences

- about one scheduled discovery GET per seven days rather than one per day;
- zero 16:45 source requests on days with no known tomorrow session;
- exactly one fresh 16:45 control GET when a known session is due tomorrow;
- no browser, PDF, OCR, AI, daemon, queue or generic notification framework;
- cancellations explicitly marked `SUSPENDIDA` are not published;
- source failure suppresses donation output for that day rather than using a
  previous-day snapshot;
- the feature adds one short cron invocation solely to achieve the reviewed
  16:45 publication time.
