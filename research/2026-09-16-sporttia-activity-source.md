# Sporttia municipal activity source validation

## Date

2026-09-16

## Production Termux probe

One GET was made to:

`https://sporttia.com/centros/ayuntamiento-guardamar-del-segura`

Result:

- HTTP `200`;
- `Content-Type: text/html`;
- 17,448 bytes downloaded with gzip;
- 93,536 bytes decoded;
- 0.386 s total;
- `ETag` and `Last-Modified` present;
- 15 `play.sporttia.com/activities/<id>` rows in the one HTML response;
- all current target schedules, season dates, venues and explicit
  registration windows present without visiting activity pages.

JSON-LD describes the centre and a FAQ summary but does not contain the
complete course schedule. The page only preconnects to `api.sporttia.com`;
it exposes no concrete catalogue endpoint that would justify reverse
engineering. It also advertises an alternate `.md` representation, but
the proven HTML is already small enough that another probe is unnecessary.

## Important source semantics

The page labels the catalogue as activities with open registration. A
course disappearing after its registration window closes is therefore
not evidence that the course itself stopped. The automation keeps each
last-good target row through its explicit season end unless a newer row
with the same source ID replaces it.

The generic `Abierta` label is not used. The live page simultaneously
labels inclusive multisport as open while its own detail text says new
registration begins on 1 October 2026. Only explicit
`NUEVAS INSCRIPCIONES` date intervals are eligible for resident-facing
registration text.
