# Product Awards Mercadona/WCCC and DIA expansion review — 2026-10-06

## Scope

This review closes the retailer-balance follow-up from ADR 0095 without adding
retailer quotas or weakening source quality. It asks only whether a new
Mercadona candidate and an existing DIA retail match satisfy the same
source-native award and exact-current-retail rules already used in production.

## Entrepinares / Mercadona

### Award authority

Official World Championship Cheese Contest evidence:

- Top-20 page:
  https://worldchampioncheese.org/2026-wccc-top-20-finalists/
- Contest methodology:
  https://worldchampioncheese.org/about/

The 2026 Top-20 page identifies:

- Class 114 — Hard Mixed Milk Cheeses;
- `Seleccion Tostado Mixed Milk Cheese Extra Aged`;
- maker `Queserías Entrepinares S.A.U.`;
- company `Queserías Entrepinares`;
- Valladolid, Spain.

The Top-20 page explicitly describes these 20 cheeses as the field still in the
running for the contest's top prize. The reviewed contest result therefore
supports the exceptional admission rule used here: Class 114 winner plus
Championship Round/Top-20, not generic class medalist admission.

The methodology page describes a technical judging system that starts from 100
points and deducts for defects in flavor, body/texture, salt, color, finish,
packaging and other appropriate attributes. Gold, Silver and Bronze go to the
three highest-scoring entries in each class.

### Retail authority

The production Termux read-only probe used only:

`https://tienda.mercadona.es/api/products/50952/?lang=es&wh=alc1`

Observed exact Guardamar-warehouse facts:

- SKU: `50952`;
- EAN: `8480000509529`;
- display name: `Queso añejo tostado mezcla Hacendado`;
- brand: `Hacendado`;
- supplier: `Queserías Entrepinares S.A.U.`;
- `published=true`;
- `unavailable_from=null`;
- `unavailable_weekdays=[]`;
- variable-weight/approximate-size pricing;
- observed piece estimate about EUR 6.19 for about 370 g;
- observed bulk/reference selling price EUR 16.74/kg;
- two exact-SKU official product photos.

The production adapter must read these values fresh. The observed prices are
evidence, not hardcoded publication values.

The API's product-photo structure uses official
`prod-mercadona.imgix.net` URLs. The new adapter accepts only that exact media
host and still permits ADR 0096 no-image degradation.

## Anís Chinchón / DIA

The award identity remains the existing MAPA 2026
`spirits_anis:mapa-2026:chinchon-dulce` candidate.

Current exact DIA page:

https://www.dia.es/cervezas-vinos-y-licores/cremas-licores-y-brandy/p/275359

Reviewed page facts:

- SKU `275359`;
- `Anís dulce Chinchon 1 L`;
- country Spain;
- responsible company González Byass S.A.;
- current add-to-cart surface.

The award event and selection keys therefore remain unchanged. Only the current
retailer evidence moves from Carrefour to DIA.

## Lidl negative result

A corrected request to Lidl Spain's current `/q/api/search` endpoint returns
HTTP 200, but probes for Perlenbacher, Irish Angus, Dawn Meats, Roncero and
related identities produced largely unrelated result sets. The searched text
could survive only as request/tracking metadata.

That endpoint is therefore not an exact-product verifier. Current alternative
Lidl candidates also failed at least one required condition: source-native
number-one result, exact awarded-product identity, or current Lidl Spain SKU.

No Lidl adapter is justified in this change.

## Architecture conclusion

Implement only:

1. one exact Mercadona product GET;
2. one deterministic WCCC source renderer/methodology;
3. one appended Entrepinares category;
4. one Anís retailer-evidence switch to exact DIA SKU 275359.

Do not change selector logic, retailer preference, state schema, cooldown, cron,
AI/browser dependencies or add a dead Lidl adapter.
