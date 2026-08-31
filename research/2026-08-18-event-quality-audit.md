# Event quality audit — 18 August 2026

## Scope

Review three defects visible in the 18 August Morning Digest: an incomplete
handicraft title, an unnatural flamenco title without a ticket link, and an
inconsistent municipal-library hall label.

## Official evidence

- Guardamar Turismo's August programme names the 20:30 event as `BAILE
  FLAMENCO: CEPA Y VERDAD, José Luis Santiago “El Lías”`, sets it at Casa de
  Cultura, publishes a `5 €` price, and directs ticket sales to Agenda
  Guardamar: `https://guardamarturismo.com/agenda-cultural/`.
- The matching Agenda Guardamar detail page publishes the same occurrence,
  price, venue and an occurrence-specific purchase URL for 18 August at
  20:30: `https://www.agendaguardamar.com/espectaculo/1/baile-flamenco-cepa-y-verdad-jose-luis-santiago-el-lias.html`.
- The detail page's JSON-LD is invalid because the quoted stage name is not
  escaped. Its same-page Google Calendar action still contains a valid
  URL-encoded title, local start time and venue. The existing parser therefore
  lost the whole Agenda occurrence and retained only the unlinked price from
  the municipal programme.
- The reviewed dated municipal-programme reproduction for `Labores a la
  fresca` includes the motto `Yo te enseño, tú me enseñas`; the previous
  Russian title omitted it. The source investigation remains documented in
  `research/2026-08-06-cultural-programme.md`.
- The official programme uses both `Hall Biblioteca Municipal` and similar
  word orders for the library exhibition space. They refer to the same venue
  label.

## Display decisions

- Preserve `Cepa y Verdad`, `José Luis Santiago` and `El Lías` as proper names
  and render the event kind explicitly as a flamenco show.
- Preserve the handicraft event's full motto in Russian.
- Canonicalize municipal-library hall variants to `Biblioteca Municipal
  (Hall)` before both display and map-link construction.
- Recover an Agenda event from its official same-page calendar action only
  when title and exact local start timestamp are both valid. Existing
  occurrence-specific ticket URL validation remains unchanged.
