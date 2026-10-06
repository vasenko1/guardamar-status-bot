# ADR 0104: Mercadona WCCC admission and DIA retailer rebalance

- Status: Accepted
- Date: 2026-10-06
- Implementation: Product Awards registry/adapter change; production validation pending
- Refines: ADR 0083, ADR 0093, ADR 0095, ADR 0096
- Research: `research/2026-10-06-product-awards-mercadona-wccc-dia.md`

## Context

ADR 0095 rebuilt Product Awards around quality-first, source-native results and
explicitly rejected retailer quotas. That seven-category pool is credible, but
Carrefour still carries three entries while Mercadona has no production
candidate despite being a major local retailer.

Fresh review found one Mercadona candidate that clears a stronger bar than an
ordinary medal: Queserías Entrepinares' `Seleccion Tostado Mixed Milk Cheese
Extra Aged` is the Class 114 entry in the official 2026 World Championship
Cheese Contest Top-20 Championship Round. The reviewed result establishes it as
the class winner advancing into the final field rather than merely one of many
class medalists.

A read-only production probe against Guardamar warehouse `alc1` also proved
the exact current Mercadona retail identity for SKU `50952`: EAN
`8480000509529`, Hacendado title, Queserías Entrepinares supplier, published
state, no active unavailability markers, variable-weight current pricing and
exact official product photos.

Separately, the already-reviewed MAPA 2026 winner Anís Chinchón Dulce is
currently represented by exact DIA SKU `275359`. Production validation found
that the MAPA presentation page fails TLS verification in Termux while the
official BOE award order is healthy and contains the exact order/product/maker
identity. The award identity is unchanged; BOE becomes the runtime award
evidence and DIA remains the current retail evidence.

Lidl research did not find a current Spain SKU that simultaneously proves a
source-native number-one result, exact awarded-product identity and current
Spanish retail availability. The live Lidl search endpoint is unsuitable as an
exact verifier because its result set does not reliably filter by the query.

## Decision

### 1. Admit WCCC only through a narrow exceptional contract

Add `source_kind=wccc`, but do not admit generic World Championship Cheese
Contest class medalists or every Best of Class result.

For this production candidate the reviewed admission contract is:

- exact source-native Class 114 identity;
- exact Entrepinares cheese/maker identity;
- class-winner status established in the reviewed result;
- inclusion in the official 2026 Top-20 Championship Round.

The runtime pins the official Top-20 page markers so source drift fails closed.
The public renderer says that the product won its class and entered the Top-20;
it must never call the product the world champion.

### 2. Add one exact Mercadona product adapter

Use only:

`GET https://tienda.mercadona.es/api/products/<id>/?lang=es&wh=alc1`

No catalogue search, postcode discovery, browser runtime, AI, fuzzy matching or
secondary Mercadona state is introduced.

A Mercadona offer is publishable only when the exact configured product still
passes all of these checks:

- exact product ID and EAN;
- exact configured display title;
- exact reviewed brand marker and supplier marker;
- `published=true`;
- empty/current `status`;
- `unavailable_from=null`;
- empty `unavailable_weekdays`;
- variable-weight and approximate-size contract remains present;
- positive current piece price, positive per-kilogram price and positive unit
  size in kilograms.

Exact `photos[].regular/zoom/thumbnail` assets are accepted only from
`prod-mercadona.imgix.net`. Missing media may still degrade through ADR 0096;
media failure never weakens identity or price checks.

### 3. Append the Entrepinares category; do not reorder the registry

Append `hard_mixed_milk_cheese` after the existing seven categories.

This preserves the positional meaning of every existing `category_cursor`
value. The new event and selection identities are new and independent; no
existing category/event key is renamed.

### 4. Preserve Anís identity; use BOE award evidence and DIA retail evidence

Keep exactly:

- `selection_key=spirits_anis:2026`;
- `event_id=spirits_anis:mapa-2026:chinchon-dulce`.

Use official BOE order `APA/744/2026` as the runtime award contract, requiring
the exact order identifier, `Anís Chinchón de la Alcoholera Dulce` and
`Gonzalez Byass Distribucion`. Keep the current retail contract on exact DIA
SKU `275359`, requiring the exact product title plus González Byass and Spain
markers. The existing González Byass official image contract remains.

### 5. Preserve runtime semantics

Do not add or change:

- retailer quotas or scoring;
- selector passes or rank demotion;
- Product Awards state schema;
- cooldown semantics;
- cron cadence;
- publication count;
- runtime AI/browser dependencies;
- Lidl code without an eligible current candidate.

ADR 0093 retailer preference continues to operate exactly as before.

## Failure and rollback behaviour

Every new network/identity ambiguity fails closed for that candidate and the
existing bounded category scan may continue according to ADR 0093.

No state migration is required. Existing cursor values `0..6` keep the same
category meaning because the eighth category is appended. The persisted cursor
ring is deliberately capped to the seven rollback-safe slots: category 6 wraps
to 0 and the appended category 7 advances to 1. The selector still scans all
eight categories from any valid cursor, but the new code never writes cursor
`7`, which the previous seven-category reader would reject.

Rolling back therefore requires only reverting code. No Product Awards state
rewrite, cron change or Telegram repair is inherent to this ADR.

## Validation gate

Before production fast-forward:

- compile the package/tests;
- pass the focused Product Awards suite;
- pass the full repository suite;
- prove wrong Mercadona EAN/brand/supplier/title, unavailable state and invalid
  price fail closed;
- prove WCCC requires the Top-20/Class 114/exact-cheese markers;
- prove the renderer does not claim a world championship;
- prove Anís preserves event/selection identity while BOE order APA/744/2026
  supplies exact award evidence and DIA SKU 275359 supplies current retail;
- prove the first seven category positions remain unchanged and no confirmation
  can persist category cursor 7;
- run a read-only live Product Awards preview on Termux and confirm neither
  Product Awards state nor Telegram is mutated.

Production validation remains pending until that exact gate has passed.
