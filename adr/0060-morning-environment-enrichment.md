# ADR 0060: Off-device CAMS morning enrichment

## Decision

Meteosalud (`idComarca=770303`, Litoral sur de Alicante) and the CAMS
European Air Quality Forecasts dataset are optional inputs of the morning
digest. A source failure omits only its own compact line.

Scientific processing runs once daily in the public
`vasenko1/guardamar-cams-data` GitHub repository, not on Android. Its daily
07:17 UTC attempt and 08:17 UTC fallback avoid GitHub's start-of-hour load
window. A successful attempt makes two small ADS retrieves over one Guardamar bounding box: the
previous two UTC days of ensemble surface analysis for the five ICA pollutants,
and the current 00 UTC ensemble forecast at lead hours 0–48 for those
pollutants, mineral dust, wildfire PM10 and six pollens. It validates the real
NetCDF fields, selects the nearest grid point and atomically publishes one
versioned JSON. A failed Action leaves the last good JSON unchanged.

The bot makes one bounded public-JSON read at 07:30 and stores a private atomic
last-good copy. A previous-day forecast is accepted only if it covers today's
complete local day and rolling history. While it remains in use, the bot checks
at 10:10, 10:25 and 10:40 and then only at the first invocation of existing
operational windows. A newer base refreshes the current full message; accepting
today's UTC cycle stops all further CAMS checks that day. Invalid, stale,
non-covering or unavailable remote data falls back to a valid local copy and
never blocks the digest. There is no CAMS token, scientific Python dependency,
ADS request or CAMS polling process on Android.

ICA bands and worst-pollutant selection follow MITECO's 2020 ICA methodology:
one hour for NO2/SO2, trailing eight hours for O3, and trailing 24 hours for
PM10/PM2.5.  The digest is deliberately quiet through `Regular` and displays
only `Desfavorable` or worse.  High pollen is >50 grains/m³ for alder, birch,
grass and mugwort, >200 for olive; ragweed is presence-only at >=3 grains/m³.

AEMET `Polvo en suspensión` remains an independent CAP warning. CAMS mineral
dust may only qualify wording inside that same-day warning; it never creates,
changes or confirms an AEMET warning.

The generated JSON and repository carry the required modified-CAMS attribution
and European Commission/ECMWF responsibility disclaimer. This decision
supersedes the direct ADS/NetCDF-on-Termux portion of the original implementation.
