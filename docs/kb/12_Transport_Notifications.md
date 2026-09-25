# Transport Change Notifications

## Purpose

Publish short resident-facing notices only when already accepted transport data
proves a meaningful change. Each named route links directly to its current
Telegram route card. This workflow stays separate from road closures,
temporary mobility measures and emergency disruptions.

## Schedule and flow

The 05:00 `sync-transport` job remains the source of accepted transport data
and immediately collects notification events. The one-shot publisher runs at
08:42 Europe/Madrid.

A notification batch may contain several semantic messages. Current public
families are:

- schedule/service-period changes;
- route/stop changes, only when a future source can prove them;
- fare changes.

Changes of the same family are grouped into one message. Different meanings
are not mixed merely to force one daily message.

State stores per-message `pending/uncertain/sent` delivery status. Telegram
has no idempotency key, so each item becomes `uncertain` before
`sendMessage`. HTTP 429 returns that item to pending; an ambiguous result
blocks automatic resend while already-sent sibling messages remain committed
inside the batch.

## Current coverage

### Urban lines 1 and 2

Official municipal PDFs are downloaded, stabilized and rendered to the
accepted timetable image. A changed rendered image proves that the timetable
changed visually. A PDF/hash metadata change with an identical image is
silent.

The code does not OCR or semantically infer exact departures/stops from the
image, so public copy says only that a new timetable was published.

Reviewed cards also have a deterministic service period:

- July and August: daily;
- September through June: Monday-Saturday, with the documented Sunday
  timetable.

A real transition between these reviewed periods can notify even if the image
did not change. If a new PDF has not been reviewed, no period claim is made and
the card does not reuse an old hard-coded route summary as if it were current.

### Airport Alicante-Elche

Bus Sigüenza provides structured departures for an exact service date. The
collector stores tomorrow's departure arrays and compares them the next morning
only against that same date, so normal weekday/weekend differences cannot
become false change notifications.

The fare parser tracks only the verified standard `TARIFA BASE GENERAL`
Guardamar-airport amount. Discounts, cards, senior fares and other tariff
classes are not inferred.

### Alicante

The Guardamar ↔ Alicante card is refreshed during the same 05:00 transport
sync. The bounded Avanza/Costa Azul public planner is the single source for the
exact service date, departures and basic one-way fare. The adapter uses normal
HTML GET/POST requests; it does not require a browser.

Today and tomorrow are queried in both directions. Tomorrow is stored as the
comparison baseline and is compared only with the same service date on the
next morning, so normal weekday/weekend differences do not create false
alerts. A first baseline is silent.

The timetable is accepted only when the requested route/date and a bounded
departure table validate. Price is optional: if its markup cannot be validated,
the current timetable remains publishable without a price. Missing/invalid
source data is never treated as a cancellation or fare change.

Alicante does not currently emit a synthetic seasonal-period event: different
daily arrays are not enough evidence to label a summer/winter transition.

### Elche

The Guardamar ↔ Elche card uses the same bounded Avanza/Costa Azul HTML
planner as Alicante. Today and tomorrow are queried in both directions during
the existing 05:00 transport sync. Tomorrow is retained only as the same-date
comparison baseline for the following morning. The first baseline is silent.

Price is shown only when both directions expose a validated fare. Missing or
invalid source data never proves cancellation or a fare change.

### Orihuela

The Guardamar ↔ Orihuela card uses Bus Sigüenza's exact-date search. Today and
tomorrow are queried during the existing 05:00 transport sync; each accepted
date must contain both Guardamar→Orihuela and Orihuela→Guardamar departure
panels. The operator result does not echo the submitted service date, so the
adapter explicitly sends and tests the exact `FECHASALIDA` request field and
does not pretend that the response contains a date marker that is not there.

The ordinary one-way fare comes from the official CE-714 tariff PDF and only
from the validated `TARIFA BASE GENERAL` Guardamar↔Orihuela row. Tariff
changes are accepted only after stable PDF content and successful parsing. A
replacement tariff with a future effective date does not remove an already
verified currently-effective fare from the card before that date. Tomorrow is
retained only as the same-date comparison baseline, and the first baseline is
silent.

Neither Elche nor Orihuela synthesizes a seasonal-period event from ordinary
daily timetable differences. The currently reviewed official evidence is not
strong enough for a reusable recurring boundary: CE-714 line 1 is described
as having winter/summer weekday frequencies without an exact period boundary,
and the available Avanza summer dates are specific to 2026.

### Other transport cards

Hospital de Torrevieja, the south/Torrevieja-Zenia-Pilar route and Universidad
de Alicante remain useful linked cards but do not currently have accepted
comparable state in the bot. They therefore emit no change notifications. A
future reliable bounded adapter can project route events into the same
`transport_notifications.py` flow without creating a new notification
subsystem.

## Link and evidence rules

Notification state stores stable route keys such as `line_1` or `airport`,
not Telegram URLs. Immediately before delivery the publisher resolves the
current message ID from `PinnedGuideState` and builds the internal Telegram
link. Missing or uncertain cards fail closed; there is no external-planner
fallback.

A missing source row or card never proves cancellation. Temporary diversions
and event closures belong to the existing mobility/emergency path.

See `adr/0065-transport-change-notifications.md`,
`adr/0081-alicante-date-specific-timetable.md` and
`adr/0082-elche-orihuela-date-specific-timetables.md`.
