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

The morning publication builder performs at most one bounded HTTPS GET. The
adapter parses ordinary table text with the Python standard library, filters
exactly `GUARDAMAR DEL SEGURA`, rejects malformed rows and ignores rows marked
`SUSPENDIDA`.

Only normalized current/future Guardamar sessions are stored in the small atomic
`state/blood_donation.json`; raw HTML and province-wide rows are never cached.

The same morning snapshot has two consumers:

1. the Morning Digest includes a session occurring today as the normal event
   `Сегодня можно сдать кровь 🩸`;
2. a short-lived 16:45 `Europe/Madrid` cron command checks the same local
   snapshot for a session tomorrow and, if present, sends one standalone alert.

The 16:45 command performs no network request. A snapshot from another local
calendar day is not reused, so a failed morning source refresh fails closed
instead of publishing stale donation information.

The alert window is bounded to 16:45–17:59. Missed alerts are not replayed later
that evening or on the event day. The snapshot stores only one `alerted_for` date to prevent duplicate delivery.
A definite Telegram send failure clears that date; an ambiguous send keeps it
to avoid an automatic duplicate.

For the reviewed Guardamar venue `Centro Sanitario Integrado (зона педиатрии)`,
both the alert and digest use the exact operator-provided Google Maps link:
`https://maps.app.goo.gl/DXW3LqEmCNCjf9JX8`.

No street address or source footer is added to the public message.

## Consequences

- one small HTML GET on a normal morning publication day;
- zero source requests at 16:45;
- no browser, PDF, OCR, AI, daemon, queue or generic notification framework;
- cancellations explicitly marked `SUSPENDIDA` are not published;
- source failure suppresses donation output for that day rather than using a
  previous-day snapshot;
- the feature adds one short cron invocation solely to achieve the reviewed
  16:45 publication time.
