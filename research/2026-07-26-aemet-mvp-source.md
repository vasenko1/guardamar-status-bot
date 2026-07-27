# AEMET Source Selection for the First MVP Slice

## Question

Can one official, lightweight source provide Guardamar weather and warnings?

## Sources checked

- [AEMET OpenData API specification](https://opendata.aemet.es/AEMET_OpenData_specification.json),
  accessed 2026-07-26
- [AEMET Guardamar municipal forecast](https://www.aemet.es/es/eltiempo/prediccion/municipios/guardamar-del-segura-id03076),
  accessed 2026-07-26
- [AEMET warning interpretation](https://www.aemet.es/es/eltiempo/prediccion/avisos/ayuda),
  accessed 2026-07-26

AEMET is Spain's responsible state meteorological authority.

## Findings

- AEMET OpenData requires an API key and uses a two-step request: product
  metadata followed by the returned download URL.
- Guardamar del Segura uses municipality code `03076`.
- The daily municipal product supplies today's minimum, maximum, and forecast
  wind.
- AEMET lists no observation station in Guardamar. It lists Rojales station
  `7261X` as the nearest, 5.3 km away.
- Conventional observations contain recent temperature and wind data.
- Guardamar belongs to warning zone `Litoral sur de Alicante`.
- The current CAP warning product is available for Comunitat Valenciana area
  `77`.
- AEMET defines CAP `Minor` severity as no warning; actual warning levels are
  `Moderate` (yellow), `Severe` (orange), and `Extreme` (red).
- AEMET permits reuse with attribution.

## Recommendation

Approve these three structured AEMET products for the first slice:

1. Guardamar daily municipal forecast
2. Recent Rojales observation
3. Comunitat Valenciana CAP warnings filtered to Guardamar's zone

Treat a Rojales observation as current only for three hours and always label
its location. Treat an unavailable warning product as unknown, never as “no
warnings.”

Confidence is high for authority, codes, and product availability. Payload
parsers should remain covered by fixtures because upstream schemas can change.

Observed 2026-07-27: the current CAP product was delivered as an uncompressed
TAR archive containing XML files. ZIP and single-XML responses remain possible,
so the adapter supports all three bounded in-memory formats.
