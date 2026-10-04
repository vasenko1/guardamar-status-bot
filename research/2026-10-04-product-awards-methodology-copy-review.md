# Product Awards methodology-copy review — 2026-10-04

## Question

The public Product Awards article already states the selected product, award
result, score/rank, retailer, package, producer and current price. The
expandable methodology quote had begun repeating or obscuring those facts with
generic wording.

The desired contract is narrower: the quote answers only **how the product was
tested or how the competition selects a winner**. It must not repeat the
candidate's product name, result, score/rank, retailer, price, package, sample
count or the editorial `highlight`.

## Source re-check

The production registry currently uses four distinct OCU study families, one
MAPA spirits competition and World Beer Awards. Their procedures are not
interchangeable.

### OCU gazpacho

Official methodology:
https://www.ocu.org/alimentacion/platos-preparados/asi-analizamos-gazpachos

OCU describes a 39-product refrigerated-gazpacho study. The final score weights
are:

- labelling: 10%;
- nutritional evaluation from label information: 40%;
- expert tasting: 50%.

The tasting covers smell, colour and texture before tasting, then mouthfeel and
flavour. The ingredient list is also reviewed for additives and other
technological ingredients.

Runtime copy should explain these criteria but omit the already published
39-product sample size and the selected product's result.

### OCU wine / cava

Official methodology:
https://www.ocu.org/alimentacion/vino/asi-analizamos

Reviewed 2025 cava result:
https://www.ocu.org/organizacion/prensa/notas-de-prensa/2025/cavas191225

OCU splits each wine sample between an independent specialist laboratory and
expert wine tasters. Laboratory work includes alcohol, sugars, volatile and
total acidity, preservatives and additives. Tastings are anonymous, compare
similar wines and use tasting sheets based on the validated OIV method. For the
reviewed cava comparison, tasting is the principal quality criterion.

Runtime copy should describe that process without repeating the 25-product
sample, NALTROS, 94/100 or its placement.

### OCU AOVE

Official methodology:
https://www.ocu.org/alimentacion/aceite-oliva/asi-analizamos

The 2024 AOVE study uses an independent laboratory and includes authenticity,
acidity, fruit-quality indicators, oxidation, conservation and sensory
analysis. Sensory analysis is necessary to classify an oil as extra virgin or
virgin.

Runtime copy should describe laboratory authenticity/quality checks and the
professional sensory panel without repeating the 23-product sample or the
selected oil's result.

### OCU coffee capsules

Official methodology:
https://www.ocu.org/alimentacion/cafe/asi-analizamos/

OCU reviews labelling; laboratory work measures moisture, soluble solids and
caffeine and screens for acrylamide and ochratoxin A. Samples are then prepared
on the same coffee machine under identical conditions for an expert sensory
panel that evaluates colour uniformity, crema consistency/persistence, aroma,
bitterness, astringency, body and defects.

Runtime copy should describe that procedure without repeating the selected
capsule result or retail identity.

### World Beer Awards

Official 2026 competition summary:
https://www.worldbeerawards.com/news/world-beer-awards-2026-winners-announced

Official judging-process page:
https://www.worldbeerawards.com/how-to-enter

The Taste competition is blind and evaluates beer within its declared style.
The competition proceeds through country/style judging, Country Winners and
then international comparisons within the same style before the broader final
round. Design is judged separately from Taste.

Because that judging process is common to the reviewed beer styles, one shared
World Beer Awards methodology block is appropriate. It must not repeat a beer
name, medal or Country Winner result already stated in the article body.

### MAPA spirits 2026

Official competition page:
https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/ultimaedicionbebidasespirituosas

The Ministry's 2026 rules combine sensory evaluation with evaluation of the
producer's submitted documentation. The tasting panel has at least five expert
tasters and a panel leader. The five best sensory samples advance to a final
tasting when they clear the stated threshold. The final result combines the
sensory score (60%) and the jury/documentation score (40%).

Runtime copy should explain this two-part selection process and not restate the
winning product or award title from the article body.

## Implementation decision

Keep Product Awards deterministic and lightweight. Do not add an LLM, another
HTTP request, a runtime scraper, new state or a generic prose generator.

Use a small reviewed methodology registry keyed by
`(source_kind, category_key)`:

- OCU entries are category-specific because their test procedures differ;
- World Beer Awards may use one source-level shared procedure;
- MAPA spirits has its own reviewed procedure;
- an unsupported source/category fails with `CONFIG` instead of silently
  falling back to generic copy.

The methodology block is rendered only from reviewed static text and remains
separate from the candidate-specific article body.

## Regression contract

Tests must ensure that every current production methodology block excludes:

- product name;
- award/result string;
- retailer;
- sample size when present;
- candidate `highlight`.

Tests also pin one or more procedure-specific facts for every current
methodology family so a future refactor cannot collapse the blocks back into
generic language.
