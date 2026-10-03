# Product Awards retailer-balance audit — 2026-10-03

## Question

Why did the current reviewed Product Awards registry become concentrated in
Consum, and does that reflect a real lack of award-winning products at
Mercadona, Lidl, DIA or Carrefour?

## Conclusion

No. The current five-of-seven Consum concentration is primarily a **registry
construction artifact**, not evidence that other supermarket chains lack
award-worthy products.

Two historical choices created the skew:

1. the 28 September exact-rich rewrite favored candidates whose current
   retailer identity, price and media could be refreshed cheaply and
   deterministically from Termux;
2. Consum exposed the cleanest exact-product JSON contract, so several branded
   winners from the same award families were easiest to make production-safe
   there.

Earlier project research had already proved exact Mercadona award-to-SKU joins
and had identified Lidl and DIA as strong retailer surfaces. Those candidates
were not carried into the final rich registry.

The current pool should therefore be rebuilt for editorial balance while
keeping award quality and exact retail evidence as the admission gates.

## A second issue: award-source concentration

The current registry also concentrates on one award family:

- Celta +Proteína;
- Takis Blue Heat;
- ELPOZO ExtraTiernos;
- Nescafé Latte Baileys

all come from Producto del Año 2026.

ADR 0083 says a production source should be primarily about product quality or a
clearly defined championship result; innovation-only awards and unordered
recognition seals are discovery inputs rather than automatic category winners.

Producto del Año is explicitly organized as Gran Premio a la Innovación and
uses a combined concept/product consumer methodology. The four current
candidates must therefore be re-reviewed against the durable source-admission
rule instead of being retained merely because their exact Consum retail
contracts are convenient.

This source-policy audit is independent of the Consum media bug.

## Retailer findings

### Mercadona — strong evidence exists

Mercadona is not absent because Hacendado products fail to win awards.

Historical production research already proved a browser-free Guardamar
Mercadona contract for exact SKU refreshes, including warehouse context
`alc1`, exact product IDs and EAN validation.

Strong reviewed examples include:

- **Queso añejo tostado mezcla Hacendado**, Mercadona SKU `50952`,
  EAN `8480000509529`, made by Queserías Entrepinares. The official World
  Championship Cheese Contest 2026 Top-20 list includes Queserías
  Entrepinares' `Seleccion Tostado Mixed Milk Cheese Extra Aged` as the
  Class 114 Hard Mixed Milk Cheeses winner/finalist. Earlier project probes
  mapped this exact award identity to current Mercadona SKU 50952 and refreshed
  the current retail offer successfully.
- **Valle de San Juan cheeses**: the producer reports eight 2026 World
  Championship Cheese Contest results, including Trufa 99.30 as best in its
  category and several other 97+ products explicitly sold in Mercadona.
  Earlier project research had already resolved multiple exact Mercadona
  product joins.

Not every Hacendado result is strong enough. OCU's 2026 Hacendado fresh
salmorejo is `Mejor del Análisis` but scores only 70/100, below the project's
>=85 comparable-score quality gate. This is evidence that the quality filter
works; it is not evidence that Mercadona lacks strong candidates.

**Audit status:** Mercadona should return to the rebuilt reviewed pool. The
already-proven WCCC exact joins are the first candidates to revalidate.

### Lidl España — strong current discovery surface

Lidl currently maintains a first-party `Productos Premiados` surface covering
cheese, fresh salmon, beef, fish, wine and other products.

Current 2026 evidence includes:

- Sabor del Año 2026 recognition for Lidl fresh salmon;
- Sabor del Año 2026 recognition for Realvalle entrecot and solomillo;
- a current exact Lidl product page for Realvalle Solomillo de ternera;
- multiple current Lidl cheese pages carrying World Cheese Awards recognition,
  including Roncero and Deluxe products.

The current retailer surface is therefore technically and editorially useful.
The remaining production requirement is an exact award-authority-to-current-SKU
join for each chosen candidate. Retailer marketing badges alone do not define
award rank or edition.

**Audit status:** Lidl is a high-priority source for pool rebuilding, not a
chain with insufficient award results.

### DIA España — current own-brand winners are available

DIA currently has a dedicated first-party `Sabor del Año 2026` retail surface
with current ecommerce prices.

Three current own-brand recognitions are:

- Burrata fresca DIA Selección Mundial 150 g — consumer score reported as 8.59;
- Yogur natural con azúcar de caña DIA Láctea — 9.26;
- Tarta de queso DIA Caprichoso 250 g — 8.53.

The Sabor del Año methodology is blind sensory consumer testing, which is more
directly quality/taste-oriented than an innovation-only seal. Before production
admission, the source semantics still need to be represented honestly: it is a
consumer sensory recognition, not automatically an overall #1 across all
supermarket products.

**Audit status:** DIA is a strong candidate family for expansion after one
source-semantic and exact-SKU review.

### Carrefour — strong candidates already existed

Earlier category-first research had a production-quality Carrefour match:

- Realfooding Gazpacho, OCU exact product, 1000 ml, laboratory analysed and
  reported at 90/100 in the reviewed comparison;
- Carrefour currently still lists the exact 1 L Realfooding gazpacho on its
  supermarket surface with a current price.

A second seasonal example is De Nuestra Tierra Turrón de Alicante, OCU
`Mejor del Análisis` at 85/100, subject to current seasonal stock proof.

**Audit status:** Carrefour should be restored as a normal pool contributor
rather than treated as absent.

### ALDI

NALTROS currently fails because exact ALDI product 190300 resolves to a
product-specific Next.js error shell. That does not invalidate ALDI as a
retailer family: independent control ALDI product pages remain healthy, and
earlier research found award-bearing ALDI cheeses.

**Audit status:** keep NALTROS retryable, but research another exact current
ALDI award candidate instead of relying on one fragile product.

### Consum

Consum remains technically valuable because exact product JSON exposes product
code, often EAN, current price and media. The problem is not that Consum
candidates are weak; it is that the registry accidentally lets one technically
easy retailer dominate the editorial sequence.

**Audit status:** retain valid Consum candidates, fix their media contract, but
do not use Consum technical convenience as the reason to admit more candidates
than other chains.

### Masymas / Juan Fornés

Masymas is locally relevant and Mahou Sin Filtrar already proved one exact
current path. It can contribute to diversity, but shared-brand or other
masymas-chain evidence must never substitute for exact Juan Fornés retail
identity.

## Rebuild policy

The registry rebuild should use **quality first, diversity second**.

### Admission

A candidate still requires:

1. an approved award/comparison source whose semantics fit ADR 0083;
2. exact product identity;
3. current official retailer evidence;
4. current price;
5. a valid first-party image contract for Rich Message publication.

No retailer gets a lower quality threshold merely to improve balance.

### Research order

When several new categories/sources are available for investigation, prioritize
underrepresented retailers in this order until the pool is healthy:

1. Mercadona — revalidate the already-proven WCCC joins;
2. Lidl España — resolve Sabor del Año/WCA candidates to exact current product
   pages;
3. DIA España — validate Sabor del Año source semantics and exact SKUs;
4. Carrefour — restore Realfooding gazpacho and review seasonal turrón;
5. ALDI — add a second healthy award product independent of NALTROS;
6. Masymas — research another exact local-chain candidate;
7. Consum — keep current valid candidates but do not expand it first.

This is a **research priority**, not a retailer quota.

### Pool-health review

Do not impose a numeric retailer quota or arbitrary minimum retailer count.
Periodically inspect whether one retailer dominates because its API is easier
rather than because the reviewed evidence is stronger.

If evidence only supports one retailer for a period, publication continues.
The bot should prefer another retailer when one is valid but must never go
silent merely to preserve diversity.

## Selection semantics

ADR 0092 implements retailer preference in one bounded scan. The first valid
same-retailer category winner is held only as an in-memory fallback while later
categories are checked. A different-retailer winner is preferred; otherwise
the stored fallback publishes.

This solves presentation order without another selector pass or retailer state.
It does **not** solve an imbalanced registry, which is why the pool rebuild is
required independently.

## Implementation boundary

This audit changes documentation/research only.

Before Product Awards runtime code is changed, the implementation plan should
include:

- Consum media repair;
- explicit ALDI error-state handling;
- one-scan best-effort retailer diversity with an in-memory fallback;
- no-image publication after deterministic media-path failure;
- a reviewed registry rebuild using the retailer priorities above;
- re-review of Producto del Año candidates against ADR 0083 source admission.

No generic retailer crawler, browser, AI discovery loop or background job is
needed.
