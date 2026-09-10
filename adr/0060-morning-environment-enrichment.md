# ADR 0060: One optional morning environment enrichment

## Decision

Meteosalud (`idComarca=770303`, Litoral sur de Alicante) and the CAMS
European Air Quality Forecasts dataset are optional inputs of the one-shot
morning digest only.  They have no operational-update state, scheduler or
later-day polling.  A source failure omits only its own compact line.

One ADS request uses the current ensemble surface product, a 0.1-degree
Guardamar bounding box, and PM2.5, PM10, O3, NO2, SO2, mineral dust, wildfire
PM10 and the six supported pollens.  ADS's current realtime process has no
`date` input, so the normalizer selects today's `Europe/Madrid` timestamps.
It requests analysis alongside forecast solely to supply the preceding 8/24
hours necessary for the official MITECO moving windows; forecast values remain
the values reported for today.

ICA bands and worst-pollutant selection follow MITECO's 2020 ICA methodology:
one hour for NO2/SO2, trailing eight hours for O3, and trailing 24 hours for
PM10/PM2.5.  The digest is deliberately quiet through `Regular` and displays
only `Desfavorable` or worse.  High pollen is >50 grains/m³ for alder, birch,
grass and mugwort, >200 for olive; ragweed is presence-only at >=3 grains/m³.

AEMET `Polvo en suspensión` remains an independent CAP warning.  CAMS mineral
dust may only qualify wording inside that same-day warning; it never creates,
changes or confirms an AEMET warning.
