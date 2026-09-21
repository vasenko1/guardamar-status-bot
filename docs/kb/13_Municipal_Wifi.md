# Municipal Wi-Fi guide

## Purpose

The linked city guide exposes one durable `📶 Бесплатный Wi-Fi` card directly
from the `📌 Полезное о Гуардамаре` root. Wi-Fi is not a place and does not
have its own daemon or cron job. The existing daily `telegrambot.guide sync`
owns both source observation and card reconciliation.

The current architecture decision is ADR 0074. ADR 0068 is superseded. Dated
source verification remains in
`research/2026-09-16-municipal-wifi-source.md`.

## Reviewed baseline

The accepted baseline contains seven municipal Wi-Fi locations:

- Escola de Música, C/ Mercat, 2 — `WiFi4EU`, no password;
- Casa de Cultura, C/ Colón, 60 — `WiFi4EU`, no password;
- Avda. Los Pinos — `WiFi4EU`, no password;
- Plaza de la Constitución — `vegafibra_gratis` / `vegafibra`;
- Paseo Marítimo · Avda. de Europa — `vegafibra_gratis` / `vegafibra`;
- Sala de Estudios 24/365, C/ Mayor, 69 — `wifi_1EO9C` / `vegafibra`;
- Biblioteca Pública, C/ San Jaime, 5 — `wifibiblioteca` / `biblimar`,
  `biblioteca infantil` / `menjallibres`, and `vicenteramos` /
  `menjallibres`.

The baseline card is retained when no dynamic snapshot has been accepted.

## Source lifecycle

The official landing page is:

`https://www.guardamardelsegura.es/wifis-municipales/`

At most once per local day, the existing guide sync:

1. performs one bounded GET of that landing page;
2. requires exactly one linked HTTPS PDF under the municipal
   `/wp-content/uploads/` path;
3. compares the linked asset URL with the last accepted asset;
4. when unchanged, does no PDF download and sends no notice;
5. when changed, downloads the bounded PDF and extracts its text with the
   already-installed Poppler `pdftotext -layout`;
6. accepts only a complete deterministic snapshot of the same seven reviewed
   point identities and the same network topology: one network per point,
   except exactly three at Biblioteca;
7. stores changed SSID/password values only after the full snapshot validates;
8. reconciles the existing public Wi-Fi card through the normal pinned-guide
   graph;
9. only after that reconciliation succeeds, sends one public group notice
   linking directly to the updated Wi-Fi card.

A source, PDF, parser, schema, or card-reconciliation failure preserves the
last accepted public card and sends no public change notice.

## Delivery safety

The public change notice is a non-idempotent Telegram `sendMessage`. Before
sending it, the guide state records the pending asset as uncertain. An explicit
Telegram rejection clears that uncertainty so a later normal guide sync may
retry; an ambiguous network/server result leaves the uncertainty marker and
does not blindly resend a message that may already be visible.

No private operator message is part of this lifecycle.

## Deliberate limits

The automatic parser updates values only inside the reviewed topology. A new or
removed municipal point, a new or removed network, an external asset host, or
an unrecognized document structure fails closed rather than partially rewriting
resident-facing credentials.

Do not add OCR, image parsing, AI, Selenium, another cron row, another state
file, a resident Wi-Fi worker, ETag history, or a generic document parser.

Replacement of PDF bytes under the exact same linked URL remains an accepted
blind spot. Add a content fingerprint only after production evidence shows that
the municipality actually replaces this document in place.
