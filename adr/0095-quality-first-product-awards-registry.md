# ADR 0095: Quality-first Product Awards registry rebuild

- Status: Implemented in main; production validation pending
- Date: 2026-10-03
- Refines: ADR 0083, ADR 0093

## Context

ADR 0083 admits a Product Awards source only when its reviewed result is
primarily about product quality or a clearly defined national, European or
world championship result. Innovation-only awards and unordered recognition
sets are discovery inputs, not production category rankings.

The 28 September rich registry drifted away from that source policy while
optimizing for exact retailer contracts. Four of seven current categories use
Producto del Año 2026 through Consum because Consum exposes a particularly easy
exact-product JSON API.

A fresh re-review confirms that Producto del Año is the Gran Premio a la
Innovación. Its own public methodology describes selection around product
innovation and consumer purchase interest; the additional product test does not
turn the award into a broad quality championship. Sabor del Año likewise
provides useful sensory/discovery evidence but normally exposes an unordered
recognition set rather than one broad-category winner/podium.

The resulting registry concentration also creates an editorial problem:
repeated Consum publications can look like retailer promotion even when the
technical reason is simply that Consum was easy to integrate.

Earlier project work already built and production-probed four stronger
quality-first/category-first contracts that were later displaced by the rich
registry rewrite:

- Realfooding Gazpacho / OCU / Carrefour;
- Oleoestepa DOP Estepa AOVE / OCU / Carrefour;
- AROM'ARTE Intenso coffee capsules / OCU / DIA;
- Anís Chinchón Dulce / MAPA / Carrefour.

Their retailer HTML adapters were proven on the production Termux device on
27 September 2026 with bounded server-rendered HTML and no browser runtime,
cookies, JavaScript execution, OCR or catalogue crawl.

## Decision

### 1. Remove Producto del Año from the production registry

Remove the four current Producto del Año categories:

- Celta +Proteína;
- Takis Blue Heat;
- ELPOZO ExtraTiernos;
- Nescafé Latte Baileys.

Do not mark them published and do not migrate them into another award family.
They may remain research/discovery leads if a separate qualifying quality source
later proves the exact product.

The runtime renderer may retain dormant compatibility code temporarily if
removing it would enlarge an otherwise unrelated change, but production tests
must assert that no registry candidate uses `source_kind=producto_del_ano`.

### 2. Restore four previously reviewed quality-first categories

Restore:

1. **Gazpacho** — OCU 2025, Realfooding, 90/100, `Mejor del Análisis`,
   39 gazpachos, current exact Carrefour 1 L product.
2. **AOVE** — OCU 2024 23-product analysis, led by Oleoestepa DOP Estepa,
   current exact Carrefour 1 L product.
3. **Coffee capsules** — reviewed OCU 2024 physical comparison,
   AROM'ARTE (DIA) Intenso, 85/100, exact current DIA 20-capsule SKU.
4. **Spirits / anís** — MAPA 2026 national winner,
   Anís Chinchón de la Alcoholera Dulce, exact current Carrefour 1 L product.

Keep the existing NALTROS/OCU, Ambar/WBA and Mahou/WBA categories.

The resulting reviewed registry has seven broad categories across five
retailers: ALDI, Carrefour, DIA, Consum and Masymas.

### 3. Do not impose retailer quotas

Mercadona and Lidl are not added merely to balance retailer counts.

A candidate must still satisfy the source-native category/rank rules and exact
current retail identity. Current Mercadona cheese leads are strong award/retail
evidence but do not replace the higher broad-cheese source podium. Lidl's
awarded-product surface remains valuable discovery evidence, but current
Sabor-del-Año recognition is not a broad ordered category result under ADR 0083.

Retailer balance is improved by selecting stronger eligible sources, not by
lowering the evidence bar.

### 4. Restore only the proven Carrefour/DIA exact-HTML adapter

For `retailer_kind in {"carrefour", "dia"}`:

- use the already-proven browser-navigation HTTP header profile only for the
  exact retailer product HTML;
- keep award-authority requests on the lightweight service headers;
- keep exact HTTPS host allowlists, 15-second timeout and existing HTML size
  bound;
- require all reviewed exact-product markers;
- parse price only inside the exact-title product-card segment ending at its
  `Añadir` control;
- ignore zero-price cart/header values;
- reject cards with reviewed unavailable/out-of-stock markers;
- return a text-only `RetailOffer` with no retailer image.

Do not restore the old queue/discovery architecture, generic catalogue search or
any browser runtime.

### 5. Keep media optional and conservative

Carrefour and DIA candidates are text-only in this change.

Their first-party pages expose images, but earlier legal/terms review did not
establish a clean reuse basis. ADR 0093 makes media optional, so no media
adapter or image allowlist is needed merely to rebuild the registry.

### 6. Use source-specific deterministic editorial semantics

OCU renderer must be generic enough for reviewed physical comparisons rather
than hard-coded to cava.

For OCU candidates it may use only reviewed candidate facts:

- comparison size when known;
- broad source category;
- exact award/result string;
- product identity.

Do not infer a numeric score when it is not pinned in the reviewed candidate.

Add one small MAPA renderer/methodology path for the official national
winner-only spirits category.

No free-form prose fields, LLM generation or generic award renderer are added.

### 7. Preserve state without migration

The production state schema remains version 1.

The four removed Producto del Año events have never been confirmed published,
so removing them requires no history rewrite.

Mahou remains in the registry, so ADR 0093 can still derive the previous
retailer as Masymas from the existing last published event.

The registry remains seven categories, and the current production
`category_cursor=0` remains valid.

## Validation

Before deployment, tests must prove:

- no production registry candidate uses Producto del Año;
- restored category/event IDs and retailer kinds are exact;
- award-source requests retain lightweight headers;
- Carrefour/DIA exact retailer requests use navigation headers;
- exact retailer markers remain mandatory;
- product-card price parser ignores a header/cart `0,00 €`;
- product-card unavailable markers fail closed;
- restored Carrefour/DIA offers are publishable with `image_url=None`;
- generic OCU rendering handles cava, gazpacho, AOVE and coffee without
  inventing facts;
- MAPA spirits rendering is deterministic;
- current production state shape with Mahou published and cursor 0 remains
  readable;
- retailer preference still treats Mahou/Masymas as the previous retailer;
- focused Product Awards tests and the full repository suite pass on Termux;
- a read-only live preview validates every restored exact retailer page before
  the production checkout changes.

## Consequences

The pool becomes more editorially credible without adding runtime machinery.

Consum falls from five current registry entries to one (Ambar). Carrefour has
three entries because three independent quality-first categories currently have
strong exact Carrefour matches; this is evidence-driven, not a quota.

Mercadona and Lidl remain active research targets. They should enter only when a
source-native quality/championship candidate satisfies the same category and
exact-retail gates.
