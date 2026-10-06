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
