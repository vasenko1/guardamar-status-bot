# Product Awards quality-pool implementation review — 2026-10-03

## Scope

Post-implementation review of the ADR 0095 quality-first registry rebuild before
opening the implementation PR.

Reviewed runtime:

- `src/telegrambot/product_awards.py`.

Reviewed tests:

- `tests/test_product_awards.py`;
- `tests/test_product_awards_delivery.py`;
- `tests/test_product_awards_main.py`.

Reviewed durable records:

- ADR 0083;
- ADR 0093;
- ADR 0095;
- Product Awards source/research KB entries.

## Review result

The change stays within the intended narrow boundary:

- no state schema change;
- no cron change;
- no queue;
- no browser/Playwright;
- no JavaScript execution;
- no cookie/session state;
- no catalogue crawl;
- no AI;
- no Carrefour/DIA image contract.

The old 27 September exact HTML mechanism is restored only for Carrefour and
DIA current-product verification.

## Findings corrected during review

### OCU coffee sample vs subgroup wording

The first implementation draft used `sample_size=29` together with a source
category phrased as if all 29 products were the Nespresso-with-caffeine group.

Historical source evidence says the 29-product study covered Nespresso/Dolce
Gusto products, while AROM'ARTE Intenso's 85/100 leading result is specific to
the Nespresso-with-caffeine subgroup.

Fix:

- source category now describes the overall capsule comparison;
- award result separately states that 85/100 was the best result among
  Nespresso-with-caffeine products.

This prevents an editorial statement from silently changing the source
population.

### Dormant Producto del Año renderer

After ADR 0095 removed all Producto del Año registry entries, the first draft
left the old PDA renderer/methodology and constants reachable in runtime.

That was unnecessary compatibility surface and a future policy footgun.

Fix:

- remove the Producto del Año renderer;
- remove its methodology block;
- remove unused PDA source constants;
- convert synthetic unit-test fixtures to eligible OCU fixtures;
- retain an explicit registry test that no production candidate uses
  `source_kind=producto_del_ano`.

A future reintroduction would now require an explicit code and source-policy
review rather than a registry-only edit.

### Stale command-test fixture

One command-level test fixture still named `producto_del_ano` because its
synthetic source name differed from the other fixtures.

Fix: convert that fixture to OCU as well. The runtime was already clean.

## Registry review

Proposed production registry remains seven broad categories:

1. NALTROS Brut / OCU / ALDI;
2. Realfooding Gazpacho / OCU / Carrefour;
3. Oleoestepa DOP Estepa / OCU / Carrefour;
4. AROM'ARTE Intenso / OCU / DIA;
5. Anís Chinchón Dulce / MAPA / Carrefour;
6. Ambar Especial / World Beer Awards / Consum;
7. Mahou Sin Filtrar / World Beer Awards / Masymas.

Five retailer families are represented without quotas.

Mercadona and Lidl are deliberately absent because the currently reviewed leads
do not satisfy the same broad-category source/rank plus exact-current-retail
gate. This is preferable to lowering source quality for cosmetic diversity.

## State review

Production state immediately before this change contains:

- schema version 1;
- category cursor 0;
- last delivery day 2026-09-29;
- published Mahou Sin Filtrar event/selection;
- no uncertain delivery.

The four removed Producto del Año events were never confirmed published.

The rebuilt registry still has seven categories and retains Mahou with the same
event and selection keys, so:

- cursor 0 remains valid;
- published-event dedup remains valid;
- previous retailer still derives as Masymas;
- no migration or state rewrite is required.

A unit test encodes this exact production-state shape.

## Carrefour/DIA adapter review

The restored adapter uses only the production-proven 27 September contract:

- browser-navigation request headers on exact retailer HTML only;
- lightweight service headers remain on award authorities;
- explicit HTTPS host allowlists;
- existing 15-second and HTML-size bounds;
- exact reviewed identity markers;
- exact title scoped to the nearest `Añadir` product-card boundary;
- zero-price cart/header values rejected;
- reviewed unavailable/out-of-stock markers rejected;
- no image URL returned.

This does not constitute browser automation.

The price parser can see repeated document/product titles. It sorts exact-title
occurrences by distance to the matching `Añadir` boundary, which keeps the
actual product card ahead of a document-header occurrence. A focused unit test
models the DIA/Carrefour `0,00 €` header trap and validates the real card
price.

## Award-source review

### OCU

The generic OCU renderer no longer assumes cava. It uses only reviewed fields:

- sample size, when pinned;
- category;
- exact reviewed result text;
- current retailer price.

The methodology text states only that admitted results are physically tested
and that laboratory/sensory details vary by product category.

### MAPA

The MAPA path is one small deterministic renderer for an explicitly named
official national category winner. No score or podium is invented.

### World Beer Awards

Existing renderer and source contract are unchanged.

## Media review

Carrefour and DIA return `image_url=None`.

This intentionally uses ADR 0093's media-optional delivery contract and avoids
adding image-host/rights complexity during a registry correction.

Consum, Masymas and ALDI media behavior is unchanged.

## Resource review

The rebuild adds no recurring work.

On cooldown days source cost remains zero.

On due runs the restored Carrefour/DIA candidates use one bounded award read and
one bounded exact retailer HTML read only when reached by the existing selector.
Retailer preference may inspect later categories as already accepted in ADR
0093.

## Test coverage added

Focused tests now cover:

- exactly seven production categories;
- no Producto del Año production candidate;
- expected five retailer families;
- exact Carrefour/DIA navigation headers;
- product-card price scoping over a `0,00 €` header/cart value;
- unavailable exact card rejection;
- exact marker drift rejection;
- text-only Carrefour/DIA offers;
- generic OCU sample/category/result rendering;
- MAPA winner rendering without invented scores;
- current production state compatibility and Masymas previous-retailer
  derivation.

Existing Product Awards tests continue to cover:

- retailer preference;
- source/rank ordering;
- ALDI page-error/drift distinction;
- Consum media selection;
- no-image Telegram degradation;
- uncertain-delivery safety.

## Validation still required

GitHub does not provide a reliable PR CI gate for this repository.

Before production checkout changes, the Termux deploy gate must run against the
exact reviewed commit:

1. compileall;
2. all focused Product Awards tests;
3. full repository unittest suite;
4. read-only live Product Awards preview;
5. inspect the restored Carrefour/DIA prices and award-source markers;
6. only then fast-forward production.

The live preview is especially important because the exact retailer HTML
contracts are intentionally fail-closed and may have drifted since the
27 September production probe.

## Final review assessment

No blocking design or static code-review finding remains.

The change is a source-policy/registry correction with two small proven retailer
adapters, not a new discovery architecture.
