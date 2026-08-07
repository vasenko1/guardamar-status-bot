# Event quality audit — 7 August 2026

## Trigger

The 7 August preview contained two `22:00` Alice Wonder rows and a literal,
incomplete night-route row. The tennis tournament had no daily time.

## Accepted source facts

The official Turismo Guardamar August programme publishes Alice Wonder on
7 August at `22:00`, at Castell de Guardamar, regular price `25 €`, within
VI Estival al Castell. The matching Agenda Guardamar occurrence supplies the
official purchase URL but calls its inventory venue
`Estival Al Castell Aforo Ampliado` and labels the price `Preu: 25 €`.

The reviewed municipal August poster publishes `Rutas nocturnas: senderismo y
dinámica grupal` on 7, 14, 21 and 28 August from `22:15–00:15`. The dated
municipal-programme reproduction at Todo Cultura corroborates a free 8 km
route for young people aged 12–30 and states that the instructor determines
the departure point.

The accepted municipal sources publish the tennis tournament from 1 through
8 August at Polideportivo Municipal Guardamar, but no daily match time was
found. The digest therefore preserves the event without inventing a time.

## Root causes

- The municipal and ticket catalogs reached Russian rendering with different
  Alice titles, so bounded title overlap could not identify one occurrence.
- The ticket parser recognized `Regular` but not the page's Valencian `Preu`.
- The poster's night-route record had intentionally retained only facts that
  survived OCR review; later corroborated details had not been applied at
  catalog read time.

## Resolution

- Map only the two exact Alice source titles to one reviewed Russian title and
  exact 7 August facts. Existing merge priority then keeps the municipal place
  and adds the Agenda Guardamar ticket URL.
- Accept the three observed official regular-price labels: `Regular`,
  `Precio`, and `Preu`.
- Apply exact-date night-route details and render its departure instruction as
  plain text rather than a map search.
- Do not broaden generic fuzzy matching or infer a tennis schedule.

## Actionable participation details

The dated programme reproduction explicitly publishes for every August night
route: sports shoes, water and a flashlight, limited places, and registration
phone `633 14 57 75`. An older official Turismo Guardamar youth programme uses
the same organizer phone and the valid `.com` email. The 2026 reproduction
prints a malformed `.gmail.es` address, so the bot uses only the corroborated
phone.

The event model can carry one short practical note, one concrete registration
contact and a limited-capacity flag. These facts are attached only by exact
reviewed occurrence rules. The general LLM extraction contract is unchanged,
and no contact is copied between events. User-facing `регистрация` is rendered
only when a verified action point is present. A generic youth-centre
`Más información` contact does not prove that it is the registration channel
for a particular workshop.
