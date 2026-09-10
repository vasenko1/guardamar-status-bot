# CAMS ADS and GitHub pipeline verification — 2026-09-10

## Scope and sources

The production dataset is `cams-europe-air-quality-forecasts` in the
Copernicus Atmosphere Data Store. Request fields were taken from the current
ADS form/API example rather than legacy CDS examples. The current form requires
an explicit `date`; authentication used the standard local `.cdsapirc` only for
the feasibility checks and the repository secret `CAMS_ADS_TOKEN` in Actions.
No credential was written to either repository or logged.

The applicable licence is the current CAMS licence published by ADS. The
derived public product uses the requested modified-information attribution and
states that neither the European Commission nor ECMWF is responsible for it or
its use.

## Real ADS observations

The successful Guardamar subset used north `38.2`, west `-0.8`, south `38.0`,
east `-0.5`, ensemble model, surface level zero and zipped NetCDF. The nearest
returned cell was latitude `38.04999923706055`, longitude
`-0.649993896484375` (the source longitude is represented near `359.35`).

A minimal PM10 forecast request for lead hours 0–2 was accepted and downloaded
in 37.629 seconds. Its ZIP was 1,464 bytes and contained `ENS_FORECAST.nc` with
three times, two latitudes, three longitudes and `pm10_conc` in `µg/m3`.

The real all-variable forecast request for lead hours 0–48 produced one
`ENS_FORECAST.nc`, 19,932 bytes, in about 86 seconds during the local probe.
Its 49 hourly rows contained:

- `pm2p5_conc`, `pm10_conc`, `o3_conc`, `no2_conc`, `so2_conc`;
- `dust`, `pmwf_conc`;
- `apg_conc`, `bpg_conc`, `gpg_conc`, `mpg_conc`, `opg_conc`, `rwpg_conc`.

Pollutants, dust and wildfire contribution use `µg/m3`; pollen uses
`grains/m3`. No missing values were observed in this subset. The current-day
forecast was available from the 00 UTC base. ADS metadata indicated lead hours
0–48 normally become available around 06:45 UTC and 49–96 around 08:30 UTC.

Analysis is available through the previous UTC day. Two previous UTC days
(48 hourly analyses) are requested for the five core pollutants. This is the
smallest simple range that always supplies the 23 hours before local midnight
needed for a trailing 24-hour PM mean, including `Europe/Madrid` DST dates.
The forecast horizon remains 0–48; 96 hours are unnecessary for today's
digest and previous-base fallback.

## GitHub-hosted producer

The public repository is
`https://github.com/vasenko1/guardamar-cams-data`. It makes exactly two ADS
retrieves per run: core analysis history and the all-variable forecast. It
validates archives, fields, units, expected hours and a single nearest grid,
then atomically writes `data/latest.json`. A failure cannot replace the last
good file.

The daily schedule is 07:05 UTC. It is after the observed/advertised 0–48
availability and before the bot's 10:10 Madrid update in both standard and
summer time, while avoiding an additional polling schedule. The Action has a
12-minute job timeout, bounded client retries and non-cancelling concurrency.

Real workflow run `34501386869` completed successfully in 3 minutes. The
published JSON was 30,540 bytes with 97 rows from
`2026-09-08T00:00:00Z` through `2026-09-12T00:00:00Z`. Its analysis ZIP was
8,396 bytes (48.577 seconds request, 1.546 seconds download); its forecast ZIP
was 19,932 bytes (107.571 seconds request, 1.961 seconds download). The raw public
URL returned HTTP 200.

For the real 2026-09-10 series, the bot selected the documented Guardamar grid,
converted today's UTC hours through `Europe/Madrid`, and normalized both air
quality and pollen to no visible line. That is a valid normal-day result, not a
missing-data fallback.

## Runtime boundary

Android receives only the bounded public JSON and stores one private last-good
copy. ICA rolling calculations, pollen thresholds, AEMET presentation
correlation and Russian text remain in `guardamar-status`. The phone has no ADS
secret, NetCDF dependency, scientific stack, scheduled CAMS collector or
operational CAMS alerts.
