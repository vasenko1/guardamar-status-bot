# Hidraqua Google Maps street-name compatibility follow-up

- Date: 2026-10-06
- Scope: user-facing location links in Hidraqua water-network notices

## Production observation

A Hidraqua notice for `CI_DIRECCION = "Camí del Dos"` rendered the expected
source-backed label but built this text search for Google Maps:

`Camí del Dos, 03140 Guardamar del Segura, Alicante`

The operator confirmed that Google Maps did not resolve that query to the
intended road, while the same place is resolved under the Spanish form
`Camino del Dos`.

## Source review

The existing Hidraqua source contract remains correct. The public ArcGIS field
`CI_DIRECCION` is the intervention/fault-point address and `CI_CALLES` means
other streets; there is no second field in the reviewed contract that supplies
a Google-specific canonical street name.

The two names are verified language variants of the same Guardamar route:

- Spanish municipal tourism page:
  https://guardamarturismo.com/romeria-de-la-virgen-de-fatima-en-guardamar-del-segura-2026/
  uses `Camino del Dos`.
- Valencian municipal tourism page:
  https://guardamarturismo.com/ca/peregrinacio-de-la-mare-de-deu-de-fatima-a-guardamar-2026/
  uses `Camí del Dos`.

The Valencian form is therefore not bad source data and must not be rewritten
in the public notice merely to accommodate a Maps search-provider alias.

## Decision

Keep Hidraqua labels source-backed and unchanged. For Maps query construction
only, allow a tiny reviewed alias table. The first verified alias is:

`Camí del Dos -> Camino del Dos`

Apply the alias to both the primary intervention address and any matching
`CI_CALLES` link. Unknown Valencian names remain unchanged.

Do not add general Valencian-to-Spanish translation, runtime geocoding, AI,
another network request, or a new dependency. Future aliases must be added only
after the exact same-place naming pair has been verified.

## Regression coverage

Tests require that:

1. the visible label remains `Camí del Dos`;
2. the Maps query uses `Camino del Dos`;
3. an unrelated Valencian street such as `Carrer Pere de Bonvilar` is not
   translated automatically.
