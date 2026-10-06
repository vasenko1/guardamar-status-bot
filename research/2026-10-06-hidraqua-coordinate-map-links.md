# Hidraqua coordinate-backed Google Maps links

- Date: 2026-10-06
- Scope: location links in Hidraqua water-network notices

## Problem

Hidraqua may expose a valid local street name that Google Maps does not resolve
reliably as text. The production example was `Camí del Dos`: Hidraqua supplied
the Valencian name, while Google Maps resolved the same road under the Spanish
form `Camino del Dos`.

A per-street alias table or automatic Valencian-to-Spanish translation would
not scale safely. Street names, urbanizations and proper nouns are not a
controlled translation vocabulary, and a guessed text query can point to the
wrong place.

## Existing source contract

The monitor already reads Hidraqua's official public ArcGIS FeatureServer that
backs the provider's public map of works and network affectations. The event
attributes include the intervention address (`CI_DIRECCION`) and other
affected streets (`CI_CALLES`).

The same feature service is spatial data. The monitor can request the feature
geometry together with the existing attributes in the same bounded HTTP call.
No geocoder, second provider or extra request is required.

## Decision

Request `returnGeometry=true&outSR=4326` from the existing Hidraqua query.

For a usable point geometry:

- treat ArcGIS `x` as longitude and `y` as latitude;
- accept only numeric WGS84-range coordinates;
- keep the source-provided street/address text unchanged in the Telegram
  message;
- build the Google Maps link from `latitude,longitude`, not from the street
  string.

If geometry is missing or invalid, keep the source address visible but do not
create a speculative Google Maps search link.

`CI_CALLES` contains additional affected streets but does not provide a
separate point for each street. Render those names as escaped text instead of
creating independent text-search map links that could repeat the same language
or naming failure.

## Why this is the global fix

The link no longer depends on whether Hidraqua writes `Camí`, `Camino`,
`Carrer`, `Calle`, an urbanization name, abbreviations, accents or another
valid local naming variant. The map target comes from Hidraqua's own feature
location.

This removes the need for:

- street alias dictionaries;
- Valencian-to-Spanish translation rules;
- runtime geocoding;
- AI;
- another HTTP request;
- new dependencies or state.

## Failure behavior

Geometry is optional for presentation only. A missing or malformed geometry
must not suppress an otherwise valid water-network alert. It only removes the
map hyperlink. This keeps the existing fail-partial behavior while preventing a
known-bad or guessed location link.

## Regression coverage

Tests cover:

1. WGS84 source geometry becomes a coordinate-based Maps query;
2. the visible label remains the exact Hidraqua address, including
   `Camí del Dos`;
3. missing, non-numeric or out-of-range geometry produces no Maps hyperlink;
4. additional affected streets are not independently text-searched in Maps;
5. existing event grouping, delivery state and source parsing remain unchanged.


## Production read-only verification — 2026-10-06

A read-only probe on the production Termux device at 14:45 CEST confirmed the
source assumptions without changing application state or the working tree.

Layer metadata reported:

- name: `Puntos`;
- type: `Feature Layer`;
- geometry type: `esriGeometryPoint`;
- native extent spatial reference: Web Mercator (`102100` / latest `3857`);
- max record count: 2000.

There were no active Guardamar rows at probe time, so the already-finished
`Camí del Dos` occurrence could not be re-read. A bounded three-row live
sample from the same layer with `outSR=4326` returned
`spatialReference.wkid=4326` and point geometries as numeric `x/y` pairs.
All three sampled coordinates were in valid WGS84 longitude/latitude ranges.

The active Guardamar query returned the same 139-byte empty response with
geometry disabled and enabled, confirming no material overhead when there are
no rows. Geometry therefore stays in the existing bounded request; no second
request is justified.

The production `state/hidraqua.json` SHA-256 was identical before and after
the probe, and the production Git working tree remained clean.

One diagnostic-script-only issue was also observed: the temporary
`/tmp/hidraqua-probe-procs.*` redirection was denied by the Termux
environment, so that particular process-presence check did not execute. It had
no effect on source validation or state, and the probe ran at 14:45, away from
the managed `:00/:30` Hidraqua schedule boundary. Future operator scripts
should use a project-private temporary path or avoid that redirection.
