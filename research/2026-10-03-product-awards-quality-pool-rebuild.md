# Product Awards quality-first pool rebuild — 2026-10-03

## Question

Does the current Consum-heavy Product Awards registry reflect the best
award-winning products available in the target supermarkets, or did technical
integration convenience distort the production pool?

## Conclusion

The current pool is distorted.

The four Producto del Año / Consum categories are technically easy to verify,
but Producto del Año is explicitly the Gran Premio a la Innovación. Its public
methodology is innovation-first rather than a broad product-quality ranking.
Under ADR 0083 it belongs in discovery, not as the sole production authority for
a category.

Sabor del Año is also useful discovery/sensory evidence, especially for DIA and
Lidl products, but its normal published recognition set does not provide the
ordered broad-category winner/podium required by the category-first runtime.

Therefore retailer balance should be repaired by restoring stronger
quality-first sources, not by forcing Mercadona/Lidl candidates into the
registry.

## Current source-policy re-review

### Producto del Año — discovery only

Official source:
https://granpremioalainnovacion.com/

The organizer describes the program as a consumer award for product innovation.
More than 10,000 consumers participate, and candidate products also undergo a
100-person target-audience product test. That additional test is useful evidence
but does not change the award's primary semantic identity: innovation.

Production consequence:

- remove Celta +Proteína;
- remove Takis Blue Heat;
- remove ELPOZO ExtraTiernos;
- remove Nescafé Latte Baileys.

None of these products is declared low quality. They simply lack a qualifying
quality/championship authority under ADR 0083.

### Sabor del Año — discovery only for this workflow

DIA and Lidl expose useful current awarded-product surfaces, and sensory
consumer testing can be meaningful. However the reviewed public result is
normally an unordered recognition family rather than a broad ordered category
winner/podium.

Do not use Sabor del Año merely to make DIA or Lidl appear in the retailer
rotation.

## Restored production-quality categories

### Gazpacho — READY

Authority:
https://www.ocu.org/alimentacion/platos-preparados/informe/gazpachos

OCU compared 39 packaged gazpachos in 2025. Real Fooding is explicitly
`Mejor del Análisis`, scored 90/100, and led both professional tasting and
OCU's healthy-scale assessment.

Current retailer:
https://www.carrefour.es/supermercado/gazpacho-fresco-realfooding-sin-gluten-1-l/R-VC4AECOMM-339275/p

Current exact Carrefour product remains a 1 L Realfooding gazpacho made by
CAÑA NATURE, S.L.U. The exact public product page remains addable and exposes a
current price.

Decision: restore.

### AOVE — READY

Authority:
https://www.ocu.org/alimentacion/aceite-oliva/informe/aceite-oliva-virgen-extra

OCU's 23-product 2024 supermarket analysis explicitly says the ranking is led
by AOVE Oleoestepa, DOP Estepa. The analysis includes laboratory authenticity,
oxidation/ageing and acidity checks plus professional sensory analysis.

Exact OCU product:
https://www.ocu.org/alimentacion/aceite-oliva/comparador/oleoestepa-aove-dop-estepa/196/109027

The exact product is marked `Analizado en el laboratorio`, 1000 ml, PET,
Oleoestepa, Spain.

Current retailer:
https://www.carrefour.es/supermercado/aceite-de-oliva-virgen-extra-oleoestepa-1-l/R-589802552/p

The current exact Carrefour page remains a 1 L Oleoestepa AOVE from D.O.
Estepa, Oleoestepa S.C.A.

Decision: restore without pinning a new numeric score in runtime; use the
reviewed source-native `Mejor del Análisis`/leader result.

### Coffee capsules — READY

Authority:
https://www.ocu.org/alimentacion/cafe/comparador/arom-arte-dia-intenso/273/103038

The exact OCU page still identifies AROM'ARTE (DIA) Intenso as a physically
laboratory-tested 20-capsule Nespresso-original-compatible product.

The reviewed immutable 2024 result table placed this exact product at 85/100,
highest in the Nespresso-with-caffeine group.

Current retailer:
https://www.dia.es/cafe-cacao-e-infusiones/capsulas-compatibles-nespresso/p/273821

DIA still exposes exact SKU 273821,
`Cápsulas de café intenso Dia Arom'arte 20 unidades`, made by Toscaf and
compatible with Nespresso, with a current addable price.

Decision: restore.

### Spirits / anís — READY

Authority:
https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/galardonados-bebidas-espirituosas

MAPA names `Anís Chinchón de la Alcoholera Dulce, Indicación Geográfica
Chinchón`, González Byass Distribución, as the 2026 national winner of Premio
Alimentos de España Mejor Bebida Espirituosa con Indicación Geográfica.

Current retailer:
https://www.carrefour.es/supermercado/anis-chinchon-dulce-1-l/R-538001406/p

Carrefour still exposes exact `Anís Chinchón dulce 1 l`, 35% vol,
I.G.P. Chinchón, González Byass.

Decision: restore.

## Existing categories retained

### Sparkling cava — NALTROS / ALDI

Keep the reviewed OCU candidate and its retryable ALDI product contract.
The current ALDI page is still in a product-specific error state, so the
candidate fails closed until ALDI restores a current exact product payload.

### International Lager — Ambar Especial / Consum

Keep the World Beer Awards 2026 country-winner/gold category result and exact
Consum product.

### Classic Pilsener — Mahou Sin Filtrar / Masymas

Keep the World Beer Awards 2026 result and exact Masymas product. This event is
already confirmed published in production state and remains necessary for
deduplication and previous-retailer derivation.

## Why Mercadona is not inserted now

This is not evidence that Mercadona lacks award-winning products.

Earlier research proved browser-free exact Mercadona SKU contracts and several
strong cheese/tuna leads. However:

- broad cheese: the reviewed primary WCCC overall podium does not match the
  Mercadona cheeses; inserting a convenient Mercadona class winner would
  bypass the broad-category source ordering;
- tuna in olive oil: OCU #1 is Sal de Plata / ALDI at 86/100 while exact
  Hacendado / Mercadona is #2 at 85/100; #2 cannot be promoted until #1 is
  either current or reliably unavailable.

Keep Mercadona as an active research target; do not manufacture a registry slot.

## Why Lidl is not inserted now

Lidl España has an excellent retailer-side `Productos premiados` discovery
surface and many current award-labelled products.

The currently easy 2026 leads are mostly Sabor del Año or retailer badges. They
do not yet provide the source-native broad-category ranking required by ADR
0083. A strong championship lead such as World Steak Challenge may be useful
when the exact winning product is currently sold again, but the reviewed Lidl
case was seasonal/promo stock rather than current permanent availability.

Keep Lidl as an active research target.

## Proposed registry after rebuild

1. sparkling_cava — NALTROS / OCU / ALDI;
2. gazpacho — Realfooding / OCU / Carrefour;
3. aove — Oleoestepa DOP Estepa / OCU / Carrefour;
4. coffee_capsules — AROM'ARTE Intenso / OCU / DIA;
5. spirits_anis — Anís Chinchón Dulce / MAPA / Carrefour;
6. international_lager — Ambar Especial / World Beer Awards / Consum;
7. classic_pilsener — Mahou Sin Filtrar / World Beer Awards / Masymas.

Retailers represented: ALDI, Carrefour, DIA, Consum, Masymas.

This is not a quota. Carrefour has three candidates because three independent
strong category results currently join cleanly to exact Carrefour products.

## Runtime implementation boundary

Restore only the already production-proven exact HTML behavior from the
27 September implementation:

- Carrefour/DIA retailer pages get browser-navigation request headers;
- award authorities keep lightweight headers;
- exact marker validation remains mandatory;
- price is parsed from the exact product-title card nearest `Añadir`;
- header/cart `0,00 €` is ignored;
- unavailable/out-of-stock exact cards fail closed;
- no catalogue search;
- no browser runtime;
- no cookies;
- no JavaScript;
- no images for Carrefour/DIA.

Do not restore the old queue/discovery architecture.

## State impact

Production state on 3 October contains only Mahou Sin Filtrar as a confirmed
published event, with category cursor 0 and no uncertain delivery.

The four removed Producto del Año candidates were never confirmed published.
The replacement registry remains seven categories, so no state migration is
needed. Mahou remains present, preserving previous-retailer derivation as
Masymas under ADR 0093.

## Follow-up research

Continue source-first research for:

- Mercadona exact category-valid candidates;
- Lidl exact championship/category winners;
- a second healthy ALDI product independent of NALTROS;
- additional Masymas candidates;
- seasonal Carrefour turrón closer to Christmas.

Do not expand Consum first merely because its JSON contract is convenient.
