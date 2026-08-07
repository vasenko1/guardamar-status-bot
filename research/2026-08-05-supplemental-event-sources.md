# Supplemental Guardamar event sources, 5 August 2026

## Todo Cultura Vega Baja

`https://todoculturavegabaja.es/` exposes WordPress REST types including
`mec-events`. Structured occurrence fields are absent, but the latest
Guardamar item reproduces the dated Ayuntamiento programme in its rendered
content. On 5 August the full normalized article was about 36,000 characters,
while the section headed `Miércoles 5 de agosto` was about 3,100 characters.

The inspected Guardamar pages reproduce an Ayuntamiento monthly programme and
identify the organizer. They corroborate these August youth workshops:

- 8 August, `19:00–21:00`: drums;
- 15 August, `19:00–21:00`: electric guitars;
- 22 August, `19:00–21:00`: electronic music;
- 29 August, `19:00–21:00`: singing;
- all at Centro Social Juvenil.

Decision: make one bounded REST request per municipal refresh, split the
article at Spanish date headings and pass only the requested day's section to
the existing text extractor. Do not crawl detail pages or send the full month
to Gemini. The supplement must not override conflicting official HTML or
Agenda Guardamar facts. Disappearance from the site is never interpreted as
cancellation.

Follow-up on 7 August: the generic newest youth-centre result did not contain
the 8 August section, while a date-specific drums result did. A single REST
search for `Guardamar 8 de agosto` with at most three full candidates returned
the exact dated record without extra detail-page requests. That record states
`19:00–21:00`, ages 12–30, and `Inscripciones: Centro Social Juvenil y
Whatsapp 609 00 67 54`; it does not state a price. The adapter therefore binds
those explicit participation facts to the matching occurrence and does not
infer free admission. `Más información` alone remains a general contact, not
registration.

## Giglon

`https://www.giglon.com/todos?city=GuardamardelSegura` exposes commercial
ticket listings and fixed or `desde` prices. No stable documented public API
was found; the listing uses session-dependent internal requests.

Decision: do not build a brittle city-calendar scraper. A Giglon event may
provide a ticket link and its explicitly displayed price after the event has
already been established by an event authority. It is not cancellation or
municipal schedule authority.

## Agenda Guardamar

The inspected official guided-tour page publishes one or more session links,
the regular price, meeting point and approximate two-hour duration. Session
links contain `webfecha` and `webhora`; these fields allow the adapter to bind
the purchase URL to the correct occurrence and reject a mismatched link.
