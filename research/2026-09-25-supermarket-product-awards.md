# Supermarket product awards: source and implementation research

## Question

How should the Guardamar Telegram bot build one long-lived editorial stream of
award-winning supermarket own-brand products while staying cheap, deterministic
and easy to extend across unrelated award bodies?

The intended product is not an OCU-only feature. OCU is the first source, but
the same stream should later be able to include cheese, wine, olive oil, jamón
and other products from different competitions without creating a separate
publication subsystem for every category.

## Sources and systems checked

### OCU

- Owner: Organización de Consumidores y Usuarios.
- Discovery surface used by the prototype: `https://www.ocu.org/ocu-salud`.
- Reviewed report:
  `https://www.ocu.org/alimentacion/platos-preparados/informe/salmorejos`.
- Access/probes: September 2026.
- Why useful: OCU publishes explicit comparative-test result labels and
  product/brand names in human-readable HTML.

### World Cheese Awards / Guild of Fine Food

- Owner: Guild of Fine Food.
- Directory surface:
  `https://gff.co.uk/directory/?type=product`.
- Access/probes: September 2026.
- Why useful: official result directory with explicit medal terminology.
- Current limitation observed during the POC: the 2026 year/results were not
  yet present in the directory on 25 September 2026, so there was no real 2026
  private-label result set to validate against.

### Retailer catalogues tested during the POC

- Mercadona public catalogue/Algolia path.
- ALDI España public search.
- Lidl España public search.

These were evaluated only for optional price/image enrichment, not as award
authorities.

### Runtime AI experiment

The first POC also tested Gemini structured extraction with OpenRouter as the
existing secondary provider. This was an implementation experiment, not an
award source.

## Product scope

The user-facing concept is one occasional stream:

- one day an OCU-tested Hacendado product;
- another day a cheese with a World Cheese Awards medal;
- later a wine, olive oil, jamón or another supermarket own-brand product from
  a credible independent competition.

The stream should feel like useful editorial discovery, not advertising and not
a technical bot card.

The system should smooth bursts rather than publish several awards at once.
The accepted schedule is one discovery run followed by at most one queued
publication per day.

## Retailer/private-label ownership allowlist

The POC established a conservative own-brand allowlist:

- Mercadona: Hacendado.
- Consum: Consum, Consum Eco, Consum Kids, Kyrey, Vitality.
- ALDI: La Tabla, Milsani, Cucina, Moser Roth, GutBio.
- Lidl: Roncero, Deluxe, Milbona, Chef Select, Crownfield, Freshona, Gelatelli,
  Vemondo, J.D. Gross, Favorina, La Cestera, Realvalle, Ocean Sea.
- Carrefour: Carrefour, Carrefour Classic, Carrefour Extra, Carrefour Original,
  Carrefour Sensation, Carrefour El Mercado.
- Valencian Masymas / Juan Fornés: Alteza, Deleitum.

Do not infer own-brand ownership from a retailer name, manufacturer name or
seller relationship. Extend the allowlist only after a retailer-owned source
or other strong evidence establishes the relationship.

When labels overlap, prefer the most specific exact label. For example,
`Carrefour Extra` is not reduced to the parent `Carrefour`.

## OCU findings

### Result semantics

Keep OCU wording semantically exact:

- `Mejor del Análisis` means the best result in the specific OCU comparative
  analysis. It is not a generic medal or a universal category championship.
- `Compra Maestra` is a value/balance distinction. Do not describe it as the
  highest-quality product merely because it is selected by OCU.

These two outcomes may coexist in one comparison and may belong to different
products.

### Salmorejo case used for live validation

The 2026 OCU salmorejo report provided a strong real test case:

- private label: Hacendado;
- retailer: Mercadona;
- product: salmorejo fresco de Hacendado;
- result: Mejor del Análisis;
- score: 70/100;
- comparison size: 30 salmorejos;
- the source also states that it was the best-rated product in the professional
  tasting.

The report was repeatedly fetched and parsed during development. The important
lesson is that these core facts are already explicit enough for deterministic
source parsing; a language model is not necessary to decide what the award is
or which private label owns the result.

A price published inside an OCU report is optional source metadata. If parsed,
render it explicitly as a price stated in that study. It is not evidence of the
current shelf price.

### Discovery choice

For production discovery, use OCU food report URLs under
`/alimentacion/.../informe/`.

Do not depend on OCU news articles as a second discovery stream for the same
test. A report is a cleaner stable unit and avoids duplicate news/report
representations of one comparison.

A current-year report is accepted only when the adapter can establish the
report year and parse an explicit accepted result next to an allowed private
label. Ambiguous layout changes fail closed and leave the item eligible for a
future retry.

## World Cheese Awards findings

WCA is still a good future source, but it should not be generalized before
there is current real data to validate.

The official directory exposed the concepts needed by a future adapter:

- current/result year;
- product identity;
- explicit award level such as Super Gold, Gold, Silver or Bronze.

Important semantic rule: a medal tier is not automatically "first place in the
category". Never invent a category win unless the official result explicitly
says so.

Implementation should wait until 2026 results exist in the official directory.
At that point, capture the actual HTML/query contract and define the adapter's
stable event key from the real result representation.

## Optional catalogue-enrichment experiment

The POC tested live retailer catalogue lookup because a current price and exact
product photo would make posts more attractive.

The experiment showed why this must not be a core dependency.

### Mercadona

A live Salmorejo search returned at least two different current SKUs with the
same visible product name:

- SKU 39901: Salmorejo fresco Hacendado;
- SKU 39966: Salmorejo fresco Hacendado.

The OCU article did not expose enough package-size identity to choose between
those SKUs without guessing. Therefore a seemingly straightforward
"exact-name" match can still attach the wrong current price or image.

### ALDI and Lidl

Public search endpoints were technically usable during the POC, but that does
not solve the general identity problem. Catalogue availability and naming are
retailer-specific.

### Other retailers

No equally reliable low-cost exact-SKU price path was established for Consum,
Carrefour or Valencian Masymas during the POC.

### Conclusion

Do not make live retailer catalogue lookup part of award discovery or
publication eligibility.

If enrichment is revisited later:

- it must be optional;
- it must prove exact SKU identity;
- ambiguity means no enrichment;
- no result may be blocked because price/photo is missing;
- source-published award facts remain authoritative.

## What the LLM POC taught us

The first implementation intentionally explored whether one universal model
call could turn arbitrary award pages into a common candidate contract.

It worked often enough to prove the product idea, but repeated live runs exposed
several distinct failure classes.

### Entity-role instability

For the same OCU Salmorejo source and same code, Gemini returned:

- `private_label = Hacendado` in some runs;
- `private_label = Mercadona` in another run.

The source evidence itself still correctly contained
`salmorejo fresco de Hacendado (Mercadona)`.

This forced the code to stop trusting the model for brand ownership.

### Product-name instability

Later repeated runs returned both:

- `salmorejo fresco de Hacendado`;
- only `Hacendado`.

When event identity depended on the model's product wording, one real award
became two event IDs. A deterministic `product_key` layer was added to repair
this, but that layer existed only because the model had been put in charge of
source interpretation.

### Editorial validation mismatch

A Russian editorial note could correctly transliterate or translate a Spanish
product name while a literal validator expected the Spanish token. Correct
prose was therefore rejected even though the verified facts were present.

### Provider availability

A final live editorial preview hit:

1. Gemini read timeout;
2. OpenRouter fallback HTTP 403;
3. complete failure of the award path before publication preview.

The award source itself was healthy.

### Architecture conclusion

The failure pattern was not one isolated bug. Each repair created another
generic layer:

- model field validation;
- deterministic private-label repair;
- product-key recovery;
- source retry semantics for rejected model output;
- editorial-result validation;
- secondary-provider behavior.

That is unnecessary for sources whose award facts are explicitly published.

The experiment should be retained as evidence not to reintroduce universal LLM
extraction into this feature.

## Accepted architecture

Use one shared engine plus small source adapters.

A source adapter owns source-specific interpretation. The shared engine owns
only common operational behavior.

### Adapter contract

Each adapter provides:

- `name`;
- `discover(year)`: bounded current item identifiers;
- `load(item_id, year)`: one deterministic parse returning an
  `AwardSourceItem`.

The item contains zero or more verified `ProductAwardCandidate` records.

### Candidate contract

Current common fields:

- source kind;
- source-defined event key;
- source URL;
- retailer;
- private label;
- product name;
- result;
- award body;
- result year;
- optional score;
- optional source-published price;
- optional sample size.

The source adapter defines the stable `event_key`. The common engine hashes
`source_kind + event_key` into the persistent event ID.

This is intentionally different from a universal normalized product identity.
The source that knows the award representation is the right place to define
what constitutes one event.

### Per-source baseline

State records initialized source names independently.

When a new adapter is deployed:

1. its first successful discovery marks the existing item IDs as seen;
2. historical results are not queued;
3. already active sources keep their state unchanged;
4. later new items from that adapter enter the shared queue normally.

This is important for incremental expansion: adding wine awards in the future
must not reset OCU or publish an archive of old wine medals.

### Shared queue and delivery

The queue is global across sources.

- Discover at 13:50 Europe/Madrid.
- Publish at 14:20.
- FIFO is sufficient for the MVP.
- At most one award post per local day.
- A burst from several sources is naturally spread across later days.
- Published and uncertain event histories permanently block duplicate enqueue.
- Ambiguous Telegram send stays uncertain and is never automatically resent.
- Explicit deterministic send failure may safely requeue for a future day.

### Rendering

Rendering is deterministic and source-semantic.

OCU needs explicit wording for `Mejor del Análisis` and `Compra Maestra`.
A future medal source may use a generic medal sentence only when that wording
does not overstate the award.

Do not add a language model merely to make the prose less repetitive. The
volume of awards is low, and small reviewed templates are cheaper and safer.

### Runtime footprint

The desired no-change run is:

- one bounded discovery request per active source family;
- no browser;
- no OCR;
- no PDF;
- no AI;
- no retailer catalogue query;
- one small JSON state;
- no resident award process.

## Implementation recipe for the next award source

Before coding:

1. Identify the official/authoritative result source.
2. Record the exact result semantics. A `Gold`, `95 points`, `Best Buy`
   and category winner are not interchangeable.
3. Prove a bounded anonymous request from the Termux environment.
4. Find a current-item list or another cheap change-detection surface.
5. Find a stable source-native item/event identity.
6. Confirm how the exact product brand is represented.
7. Confirm private-label ownership independently.

Then implement:

1. `discover(year)` returning bounded item IDs.
2. `load(item_id, year)` with strict host/content/size bounds.
3. A fail-closed parser for only the facts the source explicitly supplies.
4. A source-native `event_key`.
5. Candidate mapping into the common contract.
6. Tests for:
   - current positive result;
   - third-party brand rejection;
   - old-year rejection;
   - ambiguous product rejection;
   - duplicate item/event behavior;
   - known award-tier semantics;
   - parser breakage leaves the item retryable.
7. A read-only live probe.
8. Registration in `SOURCE_ADAPTERS` only after the live probe passes.
9. A first production discovery proving silent baseline for the new source.

Do not create a new queue, cron, publisher, state file or notification
framework for the new source.

## Candidate future source families

These remain research candidates, not production commitments:

- World Cheese Awards / Guild of Fine Food;
- wine competitions with official searchable result databases;
- olive-oil competitions;
- jamón/cured-meat competitions;
- Great Taste and similar food-award directories.

Prioritize sources that have official structured or stable HTML results and
clear product identity. A prestigious award with an expensive or ambiguous
source is lower priority than a slightly less broad award with a clean,
verifiable public result surface.

## Status and next validation

Architecture: accepted.

Implementation: PR #195.

Production deployment: not yet approved at the time of this note.

Before merge/deploy, the deterministic branch still needs the normal final
read-only live preview and full regression review. That preview must work with
Gemini, OpenRouter and Telegram credentials unset.

---

## Horizontal retailer and rich-editorial expansion — 25 September 2026

### Scope after the second research pass

The first proof of concept intentionally constrained the feed to supermarket own brands. The broader useful scope is now:

- private-label products;
- retailer-exclusive products whose exact commercial identity can be proven;
- ordinary branded products that have won a credible award and whose exact SKU is currently listed by a supported Spanish supermarket.

Public wording must preserve those distinctions. A listed or retailer-exclusive product must never be described as an own brand unless ownership is independently proven.

The user-provided Salmorejo article is deliberately not stored as a project template or copied into this research. It is only a quality bar: a publication should contain enough verified material to explain what was tested, how the result was obtained, why the product stood out, and — when exact current retail identity is proven — the current price and an exact product photo.

### Target retailer set

The primary set should be seven Spanish supermarket chains:

1. Mercadona;
2. Lidl España;
3. ALDI España;
4. Consum;
5. Carrefour España supermarket;
6. Masymas / Juan Fornés Fornés in Comunidad Valenciana and Murcia;
7. DIA España.

DIA is a justified addition rather than generic chain expansion.

DIA has a live official page for its 2026 Sabor del Año products with exact private-label products and current prices:
https://www.dia.es/l/productos-premiados-dia

Eroski and SPAR remain possible later additions. They are not needed for the first expansion.

### Retail catalogue capability

#### Mercadona

Public product URLs use a numeric product identity under:
https://tienda.mercadona.es/product/<id>/<slug>

The earlier POC proved that public catalogue/search data can expose exact Mercadona SKU IDs, prices and product images.

The critical identity finding remains: SKU 39901 and SKU 39966 both exposed the visible name Salmorejo fresco Hacendado. Therefore visible-name equality is never enough. An exact Mercadona product ID or another exact variant discriminator is required before current price or photo can be attached.

Decision: technically usable, but the strictest matching rules are required. If the award source does not distinguish same-name SKUs, publish without live Mercadona enrichment rather than guess.

#### Lidl España

Lidl has the strongest retailer-side award discovery surface found:
https://www.lidl.es/c/premiados/a10092875

On 25 September 2026 it exposed awarded groups across fresh salmon, beef, cheeses, fish, wine and other products, with current availability and often price/package data.

Observed examples included Realvalle Entrecot de vacuno, approximately 300 g at 7.49 EUR, and Realvalle Solomillo de ternera, approximately 250 g at 9.95 EUR.

Exact product pages can expose stable product paths and multiple images. Example:
https://www.lidl.es/p/la-bien-pinta-vino-blanco-d-o-rueda-verdejo/p11037304

Decision: Lidl should serve both as a retailer evidence source and a cheap retailer-first discovery surface. A retailer award badge is a discovery hint; when possible, the independent award authority must still verify the award semantics. Never transfer Lidl Great Britain or Lidl Ireland results to Lidl España merely because a private-label name matches.

#### ALDI España

Current exact ALDI pages expose a stable numeric product ID, exact name, package, current price and multiple images. They may also state the award.

Observed examples:
- LA TABLA Queso curado, 300 g, 3.35 EUR, explicitly described as Super Gold at World Cheese Awards:
  https://www.aldi.es/producto/queso-curado-181600.html
- LA TABLA Queso de oveja ahumado V de Navarra, 250 g, 4.29 EUR in the observed offer, explicitly described as bronze:
  https://www.aldi.es/producto/queso-de-oveja-ahumado-v-de-navarra-601233500.html

Decision: technically strong for exact-SKU price/photo verification. The competition authority should remain preferred for medal semantics. Preserve geographic price caveats published by ALDI.

#### Consum

Consum is one of the best technical retailer surfaces found.

Official ecommerce pages expose:
- stable Código producto;
- often EAN;
- exact volume/package;
- current price and unit price;
- product images.

Observed examples:
- CONSUM AOVE 0.5 L, code 7414787, 3.60 EUR;
- CONSUM ECO AOVE 0.5 L, code 7304397, EAN 8414807543455, 4.75 EUR;
- CONSUM Gouda tierno 350 g, code 7419021, EAN 8414807557421, 2.82 EUR.

Decision: use Código producto as stable retailer identity and EAN, when present, as the strongest cross-source product key. Consum is ready for an enrichment adapter even if award discovery still comes from OCU or a specialist competition.

#### Carrefour España

The public Carrefour supermarket surface renders product names, package variants, prices and images and asks for a postcode to resolve local availability.

A current Carrefour Extra AOVE category exposed several different sizes and variants:
https://www.carrefour.es/supermercado/la-despensa/aceites-y-vinagres-carrefour-aceite-de-oliva-virgen-extra/F-1y9wiZ10siZp646/c

Critical trap: Carrefour.es also contains marketplace products sold by third parties. A marketplace card is not evidence that a product is a Carrefour supermarket shelf item.

Decision: restrict to the supermarket surface plus a configured postcode/store context; reject third-party marketplace seller cards; prefer exact EAN/REF or another stable first-party product ID; include package size in identity.

#### Masymas / Juan Fornés Fornés

The masymas name is used by several independent supermarket businesses. For this project the target is the Valencian/Murcian chain operated by Juan Fornés Fornés, S.A.

Official online store:
https://tienda.masymas.com

Official FAQ:
https://masymas.com/es/index.php?catid=11&id=135&option=com_content&view=article

The FAQ states that product details can be viewed without registration and that online products use the same prices, offers and promotions as physical Masymas stores.

The current shop is JavaScript-driven. This research pass did not yet prove a stable anonymous JSON product contract.

Alteza is a shared distribution/private-label brand. An award for an Alteza product alone does not prove that the same SKU is currently sold by Juan Fornés.

Decision: keep Masymas in scope because it is locally relevant and has a real online catalogue. Before coding, perform one bounded browser-free network/API probe. Require an exact Juan Fornés SKU/EAN/current product card before saying that an awarded Alteza item is currently available there. Never substitute another masymas company's catalogue.

#### DIA España

DIA has an unusually useful current award surface:
https://www.dia.es/l/productos-premiados-dia

Observed 2026 examples:
- Burrata fresca Dia Selección Mundial 150 g — 2.19 EUR;
- Tarta de queso Dia Caprichoso 250 g — 2.75 EUR.

The page explicitly ties the products to Sabor del Año 2026 and current ecommerce sale.

Decision: add DIA to the retailer set. Use the page for exact retail identity/current sale and as a discovery hint; verify award semantics through the award authority or another authoritative result source before registering an automated award adapter.

#### Alcampo / Auchan — researched, then excluded

Official Alcampo ecommerce was technically viable: the research found stable
numeric product paths, price/unit price, package, image and legal product
details. The observed Auchan Salmorejo 1 L card also provided a clean example
of joining an OCU result to an exact retailer product.

However, technical suitability is not enough for this local feature. Alcampo
has low practical relevance for the Guardamar audience because there is no
nearby store that most residents can conveniently use.

Decision: **exclude Alcampo / Auchan from the active retailer scope**. Do not
use it for runtime private-label matching, retailer enrichment, current-price
refresh, photos or award publication. Keep this section only as historical
research so the source is not re-evaluated from scratch later.

### Award-source vertical review

#### OCU

Status: implemented source adapter; retain and enrich.

The 7 July 2026 Salmorejo report proves that OCU can support a much richer deterministic article. It explicitly supplies:
- 30 products;
- labeling and composition review;
- OCU health-scale evaluation;
- blind professional chef tasting;
- appearance, smell, taste and texture dimensions;
- exact result and score;
- professional-tasting distinction;
- health classification;
- source-published price.

A source-specific renderer can use those facts without a language model.

#### Sabor del Año

Status: high-value source family; authoritative deterministic discovery contract still needs to be proven before registration.

The 2026 result set includes direct supermarket products from Lidl and DIA. Public result reporting records 89 recognised food products in 2026, including Lidl fresh salmon, Lidl entrecôte and tenderloin, DIA natural yoghurt, DIA Selección Mundial burrata and DIA Caprichoso cheesecake.

Semantic rule: this is consumer sensory recognition. Do not rewrite it as an objective category championship or first place unless the award authority explicitly publishes such a rank.

Retailer pages are excellent identity/current-sale evidence but should not become the sole award authority when a dedicated award result is available.

#### World Cheese Awards / Guild of Fine Food

Status: high-priority future source; 2026 adapter must wait.

Official dates:
- judging: 12 November 2026 in Córdoba;
- Gold, Silver, Bronze and Super Gold results: public directory within 24–48 hours;
- trophy winners: 16 November 2026.

Therefore no 2026 parser should be shipped on 25 September 2026. Probe and implement against the real November result format.

Do not confuse World Cheese Awards with World Championship Cheese Contest.

#### World Championship Cheese Contest 2026

Status: current source candidate.

Official 2026 Top 20 includes class 114 Hard Mixed Milk Cheeses, Seleccion Tostado Mixed Milk Cheese Extra Aged, Queserías Entrepinares, Valladolid.

This proves current Spanish supplier relevance but does not prove a Mercadona SKU. The complete result database needs a bounded source probe and exact retail evidence.

#### GourmetQuesos 2026

Status: strong Spanish cheese source candidate.

Official 16th GourmetQuesos data records more than 800 samples, 65 judges, two qualifying phases, 20 categories and 60 finalists. Judging includes rind, colour, texture, aroma, flavour, aftertaste and persistence.

This is excellent rich-article context when an exact winner can be joined to an exact supermarket SKU.

#### MUNDUS VINI

Status: technically strong wine source candidate.

Official result cards expose tasting edition, medal, submitter, country, wine category, quality level, denomination, vintage, alcohol, grape variety, bottle volume and recommended retail price.

A current 2026 example submitted by Lidl Stiftung is 2025 Hacienda Uvanis Tinto Joven, MUNDUS VINI Summer Tasting 2026, DO Navarra, Garnacha, 0.75 L, RRP 4.99 EUR.

Important rule: submitted by Lidl Stiftung does not prove current sale in Lidl España. A Spain-specific current Lidl card must match the exact wine, especially vintage, denomination and bottle size. Wine must never be matched only by label-family name.

#### Great Taste

Status: broad future source, second wave.

Guild of Fine Food publishes searchable Great Taste results. The directory includes retailer/private-label products from multiple countries.

Decision: accept only exact Spain retail SKU/EAN/current listing; never infer Lidl España or ALDI España availability from a UK/Ireland result.

#### NYIOOC World Olive Oil Competition

Status: promising AOVE source; exact retail match required.

The 2026 official NYIOOC news surface records a Gold for Casa Juncal from Aceites Oro Bailén Galgón 99 and identifies it as a medium-intensity Picual AOVE.

This becomes a supermarket article only when the exact award-winning commercial product/variant is proven to be the same current retailer SKU. Supplier relationship alone is insufficient.

#### MAPA — Alimentos de España Mejores Jamones

Status: authoritative vertical source candidate.

The Ministry's 2026 results record 51 samples and winners including Jamón Serrano 24 - Monte Nevado and Jamón de bellota 100 % ibérico Guillén. The official method uses expert sensory panels and separate categories.

This can create rich editorial context but still needs exact retail mapping before naming a supermarket.

#### MAPA — Alimentos de España AOVE

Status: authoritative award, unsafe for automatic supermarket-SKU transfer.

The 2025–2026 competition admits bulk AOVE from a homogeneous lot of at least 10,000 kg and uses organoleptic plus physical/chemical evaluation.

Permanent negative rule: a winning mill/producer is not evidence that every supermarket bottle produced by that company won. A supplier relationship must never transfer this award to a retail SKU without explicit commercial identity.

#### Producto del Año — Marca Distribuidor

Status: useful watch source; stable official scheduled result surface still needs validation.

The 2026 distributor-brand results include retailer brands such as Lidl and Alteza. This is attractive because retailer identity can be explicit in the award.

For Alteza, exact Juan Fornés retail evidence remains mandatory because the label is shared across a wider purchasing/distribution structure.

### Award-to-retail identity gate

Award evidence and retailer evidence are separate authorities.

Accept a join, strongest first, when:
1. exact EAN/GTIN matches;
2. exact retailer SKU/product ID is explicitly tied to the awarded commercial product;
3. exact commercial name plus variant plus package/vintage plus maker match, no competing same-name SKU exists, and category-specific identity rules pass.

Reject when evidence is only:
- manufacturer/supplier equality;
- brand equality;
- retailer relationship with the producer;
- product-family name;
- fuzzy text similarity;
- same visible name with multiple SKUs;
- same private-label brand in another country;
- Carrefour marketplace listing from a third-party seller;
- bulk/lot award with no explicit commercial retail mapping.

No LLM or generic fuzzy matcher may override these rules.

### Category-specific identity

Wine:
- exact label/cuvée;
- vintage when stated;
- DO/IGP/DOP or equivalent;
- bottle size;
- grape/variant where needed;
- EAN preferred.

Cheese:
- exact commercial name;
- milk/type;
- maturation/age;
- flavour variant;
- format/weight when relevant;
- maker.

AOVE:
- exact commercial brand/variant;
- cultivar, campaign or style when part of award identity;
- producer/bulk-lot award alone is insufficient.

Jamón/cured meat:
- exact commercial name;
- ibérico percentage;
- feed/category such as bellota or cebo;
- recognised quality figure;
- cured-age/product variant;
- whole piece vs sliced format when the award distinguishes it.

Fresh meat/fish:
- preserve the range/cut scope the award actually names;
- do not pretend one tray size won when the award covers the broader range.

Olives:
- exact variety/filling/salt/flavour variant and package when available.

### Current price lifecycle

Because the shared queue may delay publication for several days, do not freeze a current retailer price at award-discovery time.

Preferred flow:
1. award adapter proves the award;
2. retailer evidence resolves an exact stable retailer product ID/EAN;
3. immediately before publication, perform one bounded exact-SKU refresh;
4. if still current, use refreshed price and availability;
5. if price cannot be safely refreshed, omit the current-price sentence;
6. never substitute a search-engine, aggregator or stale cached price.

When a retailer varies price/stock by store or postcode, preserve that context. Use one explicit configured Guardamar retail context, not device/user geolocation.

Retail identity may be necessary to claim that a third-party award product is currently sold by a chain. Live price itself remains optional.

### Product photos

Exact product images are technically exposed by several current retailer surfaces:
- Lidl;
- ALDI;
- Consum;
- Carrefour supermarket;
- DIA;
- Mercadona after exact SKU resolution.

Masymas still requires the internal store contract probe.

Rules:
- only an exact matched SKU/product;
- allowlisted HTTPS retailer or award-authority media host;
- bounded image content type and size;
- no Google/image-search result and no generic brand image;
- if exact image is unavailable, publish text-only.

Technical accessibility does not automatically grant republication rights. Before Telegram media is enabled for a retailer, record a terms/licence review for that media source. If the required reuse is not permitted or is unclear, retain the source link and publish text-only.

Photo failure must never invalidate a verified award article.

### Rich deterministic editorial contract

The current ProductAwardCandidate is too narrow to consistently produce the desired article quality.

Future source records should be able to retain a small reviewed set of verified facts such as:
- award body and edition/year;
- exact medal/result/tier;
- category/class;
- score/points;
- number of compared products or entries;
- number/type of judges or consumer testers;
- judging method;
- source-backed standout result;
- source-backed nutrition/quality classification;
- exact product identity attributes;
- producer/maker;
- source-published study price;
- separately refreshed current retailer evidence.

Do not add a free-form generic prose extractor. Each adapter should expose only source facts whose semantics are known.

Renderer strategy:
- OCU: comparison size, method, score, tasting result, health-scale result and exact current retail price when safely matched;
- Sabor del Año: consumer sensory recognition and exact awarded range/product, without inventing category ranking;
- cheese contests: medal/place/class, competition scale and published judging criteria;
- MUNDUS VINI: medal/edition, vintage, DO, grape and bottle identity;
- MAPA jamón: official category, sample scale and expert sensory process;
- AOVE: exact commercial award identity and cultivar/style only when tied to the retail product.

The renderer remains deterministic. A small source-renderer registry is cheaper and safer than runtime LLM editorial writing.

### Discovery architecture

Use two complementary directions while retaining one shared queue.

Award-first:
- OCU;
- World Cheese Awards once 2026 results exist;
- World Championship Cheese Contest;
- GourmetQuesos;
- MUNDUS VINI;
- NYIOOC;
- suitable MAPA awards;
- Great Taste later.

Retailer-first:
- Lidl España Productos premiados;
- DIA Productos premiados;
- ALDI exact product/award editorial pages.

Retailer-first pages provide a small already-relevant candidate set. The bot then verifies the award against its authority before queue eligibility. This avoids scanning huge global directories for thousands of irrelevant products.

### Recommended implementation sequence

1. Keep OCU as the first production adapter and complete its production-device read-only preview before deployment.
2. Before production state exists, broaden the model so award identity and retail evidence are separate and private_label is no longer universal.
3. Add retailer evidence adapters incrementally, starting with the clearest current contracts: Consum, ALDI, Lidl, DIA, then Carrefour with a marketplace guard.
4. Perform dedicated bounded probes for Mercadona exact product JSON/API and Masymas / Juan Fornés internal JSON/API.
5. Enrich the OCU fact model and renderer so it can create article-depth deterministic copy.
6. Add one genuinely new award family only after a live current source probe. WCCC/GourmetQuesos and MUNDUS VINI are current candidates. World Cheese Awards 2026 waits for November.
7. Add Telegram photo delivery only after exact media identity and source-specific terms/reuse review.

Do not create retailer-specific cron jobs. Catalogue reads occur only while verifying a candidate or immediately before publication.

### Architecture re-review

ADR 0083 remains correct at the engine level:
- one source-adapter award engine;
- one queue;
- per-source first-run baseline;
- maximum one article per day;
- no universal LLM parser;
- source-native award event identity;
- retail enrichment must never rewrite award identity.

The assumption that every candidate is a private label is too narrow.

The durable flow is:

award evidence -> exact retail identity/evidence -> shared queue -> publication-time exact-SKU refresh -> rich deterministic renderer

Award identity remains stable when price, stock or photo changes.

A price/photo failure degrades the article instead of fabricating a replacement. Failure to prove that the awarded product is the same retail product must fail closed for any claim that it is currently sold by that chain.

### Verified URLs from the horizontal pass

Award-authority/result surfaces:

- OCU 2026 Salmorejo report:
  https://www.ocu.org/alimentacion/platos-preparados/informe/salmorejos
- OCU Salmorejo methodology:
  https://www.ocu.org/alimentacion/platos-preparados/asi-analizamos-salmorejos
- World Cheese Awards 2026 information and dates:
  https://gff.co.uk/for-producers/world-cheese-awards/
- World Cheese Awards 2026 result publication terms:
  https://gff.co.uk/world-cheese-awards-policies/terms-conditions/
- World Championship Cheese Contest 2026 Top 20:
  https://worldchampioncheese.org/2026-wccc-top-20-finalists/
- GourmetQuesos 2026 official results/context:
  https://www.gourmets.net/salon-gourmets/2026/catalogo-expositores/grupo-gourmets/16-gourmetquesos-campeonato-de-los-mejores-quesos-de-espana-2026
- MUNDUS VINI results:
  https://www.meininger.de/en/tastings/mundus-vini/results
- MUNDUS VINI current Lidl-submitted Spanish example:
  https://www.meininger.de/en/wine/awarded-wines/2025-hacienda-uvanis-tinto-joven-0
- NYIOOC current Casa Juncal result/news:
  https://news.nyiooc.org/release/aceites-oro-bailen-galgon-99-wins-four-golds-and-a-silver-at-2026-nyiooc
- MAPA 2026 jamón award:
  https://www.mapa.gob.es/en/alimentacion/temas/promo-alimentos/premios-alimentos/ultima_edicion_jamones
- MAPA 2025–2026 AOVE competition:
  https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/ultima-campana-aceites

Retailer evidence/discovery surfaces:

- Lidl España awarded products:
  https://www.lidl.es/c/premiados/a10092875
- Lidl exact wine example:
  https://www.lidl.es/p/la-bien-pinta-vino-blanco-d-o-rueda-verdejo/p11037304
- ALDI exact Super Gold cheese example:
  https://www.aldi.es/producto/queso-curado-181600.html
- ALDI exact bronze cheese example:
  https://www.aldi.es/producto/queso-de-oveja-ahumado-v-de-navarra-601233500.html
- Consum exact product/EAN example:
  https://tienda.consum.es/es/p/aceite-de-oliva-virgen-extra-ecologico/7304397
- Carrefour supermarket AOVE category:
  https://www.carrefour.es/supermercado/la-despensa/aceites-y-vinagres-carrefour-aceite-de-oliva-virgen-extra/F-1y9wiZ10siZp646/c
- Masymas / Juan Fornés FAQ:
  https://masymas.com/es/index.php?catid=11&id=135&option=com_content&view=article
- Masymas / Juan Fornés online shop:
  https://tienda.masymas.com
- DIA 2026 awarded products:
  https://www.dia.es/l/productos-premiados-dia
Excluded-retailer historical evidence:

- Alcampo / Auchan was technically verified during research but is intentionally
  out of scope for Guardamar-local product-award publication because of low
  practical local accessibility.

Discovery-only evidence that is not yet approved as a scheduled award authority:

- 2026 Sabor del Año result reporting:
  https://www.foodretail.es/food/sabor-del-ano-2026distingue-a-89-productos-de-alimentacion.html

Do not silently promote a discovery-only article into a production authority.
A future implementation must still prove the responsible award body's own
stable public result contract.

### Photo-rights follow-up

The technical ability to fetch an exact product image is not sufficient to
republish it in Telegram.

Current legal/terms checks on 25 September 2026 found explicit restrictions on
copying, reproduction, distribution or public communication of site content
without prior permission for several target retailers:

- Lidl España;
- Consum;
- Carrefour España;
- DIA España;
- Masymas / Juan Fornés Fornés.

Juan Fornés' own legal notice states that the information, graphic design and
code are protected and expressly excludes reproduction, distribution,
transformation and public communication of all or part of the site content.
Its app terms likewise reserve exploitation rights in photographs and other
content.

The safe product decision is therefore stronger than the earlier generic
"review terms before use" rule:

- retailer product photos are **disabled by default**;
- technical image URLs may still be inspected for identity verification;
- a Telegram product photo is enabled only for a source where an explicit
  licence, permission, press/media asset policy or other sufficiently clear
  reuse right has been documented;
- uncertainty means text-only publication;
- never copy a retailer product image merely because the HTTP URL is public.

This does not affect use of factual catalogue data such as exact product
identity, package and current price when obtained through a permitted public
surface.

### Masymas domain/company negative test

Do not treat an arbitrary site containing the masymas name as evidence for the
target Valencian/Murcian retailer.

A live investigation found that supermasymasonline.com belongs to HIJOS DE
LUIS RODRÍGUEZ S.A. in Asturias, not JUAN FORNÉS FORNÉS S.A. A current Alteza
product found there therefore cannot establish current availability in the
Guardamar-area Masymas chain.

The target company identity must be Juan Fornés Fornés, S.A.; its official
online-store and masymas.com surfaces are the accepted starting point.

### Final no-change cost rule

The horizontal expansion must not become eight daily catalogue scans.

Normal discovery remains award-first or retailer-award-list-first. Retailer
catalogues are queried only when a relevant candidate exists:

1. discover a bounded award/result item or a bounded retailer award lead;
2. verify the independent award semantics;
3. resolve one or a few exact retailer SKU candidates;
4. enqueue only after the retail relationship can be stated correctly;
5. immediately before publication, refresh only the already-resolved exact SKU
   for current price/availability.

Thus a quiet day should add almost no retailer catalogue traffic. No per-retailer
cron, full catalogue crawl, browser session or continuous stock monitor is
introduced.

### Same-day price volatility proof

DIA provided a useful live proof that award discovery price must not be treated
as publication price.

The official 2026 awarded-products page and exact product cards expose stable
numeric product IDs:

- Burrata fresca Dia Selección Mundial 150 g:
  `/quesos/fresco/p/263576`;
- Tarta de queso Dia Caprichoso 250 g:
  `/yogures-y-postres/postres-tradicionales/p/307308`.

Within the same research day, fresh indexed/opened representations already
showed changed prices for these exact products. The specific values are not a
durable project constant; the important result is that exact retail price can
change between discovery and later rendering even when product identity is
stable.

This directly validates ADR 0084's publication-time exact-SKU refresh.

### OCU is already horizontal across retailers

OCU must not be modelled as a Mercadona-specific source.

Current 2026 OCU material includes, among other examples:

- Hacendado / Mercadona Salmorejo as Mejor del Análisis;
- Carrefour Extra Black nata y chocolate negro as Mejor del Análisis;
- current whole-milk comparison material with multiple supermarket products.

OCU also contains Auchan / Alcampo results, but the project deliberately ignores
them because Alcampo is outside the locally useful retailer scope.

OCU exact comparator cards can expose strong retail identity facts such as EAN,
format and manufacturer. These surfaces are useful for deterministic product
identity, but award labels shown inside generic "alternatives" widgets must not
be attributed to the page's primary product. The current report parser's local
evidence rule remains correct.

Future OCU expansion should evaluate comparator/category surfaces separately
instead of weakening report-local parsing.

### Current retailer-photo legal evidence

The photo default-off policy is now supported by direct legal pages, not only a
general copyright assumption.

- Lidl España's legal notice prohibits reproduction, distribution and public
  communication of site content for commercial purposes without authorization.
- Consum's shop legal notice prohibits reproduction, distribution, public
  communication, retransmission, copying and redistribution except personal
  and private use.
- Carrefour states that no licence is granted and specifically reserves
  alteration, exploitation, reproduction, distribution and public
  communication unless expressly authorized.
- DIA's current legal notice gives only strictly private use and prohibits
  copying, reproduction, public communication, transformation or distribution
  for public or commercial purposes without prior written authorization.
- Masymas / Juan Fornés' legal notice expressly excludes reproduction,
  distribution, transformation and public communication of protected site
  content.

Therefore the project must not interpret "we can fetch the image" as "we may
send the image to Telegram".

### Pre-implementation code re-review

The wider research was compared back against the current Python implementation
before any production deployment.

The shared operational model is still good, but the current code is not yet
compatible with ADR 0084 and must remain draft.

Required pre-production changes:

1. `ProductAwardCandidate.private_label` is mandatory. It must no longer be
   universal because a valid award product may be a third-party listed brand or
   a retailer-exclusive product.
2. The generic non-OCU renderer currently says every future product is
   `собственной марки`. That wording becomes factually wrong for ordinary
   listed brands and must be relationship-aware.
3. Stable retail identity needs its own record: retailer, relationship type,
   exact product ID and/or EAN, product URL, package/variant qualifiers and the
   configured retail context needed for a later exact refresh. Live price and
   photo URL must not become award event identity.
4. Rich verified source facts need a small typed/source-specific context so
   OCU, cheese, wine, jamón and consumer awards can render article-depth copy
   without generic free-form extraction.
5. Publication needs one optional exact-SKU retailer refresh before rendering.
   It must not search the catalogue by fuzzy product name at send time.
6. The common `_result_priority()` currently imposes one global ranking
   (`trophy > super gold > gold > silver > bronze > OCU`). This does not scale
   safely to unrelated award semantics such as Great Taste stars, category
   places, OCU value labels and wine competition distinctions. Canonicalisation
   of multiple results for the same source event belongs at the source adapter
   boundary; the shared core should not invent a universal award hierarchy.
7. Source discovery remains capped and bounded. Large global directories such
   as Great Taste or WCA should therefore be filtered using a source-native
   query/retailer-first lead rather than converted into a broad catalogue crawl.

Things that should **not** be added:

- a generic retailer search framework;
- daily scans of all eight supermarket catalogues;
- a database;
- an image cache;
- a browser;
- fuzzy matching;
- LLM product matching or prose generation;
- one queue or cron per retailer/award body.

Because no production product-award state has been established yet, evolving
the serialized candidate/state schema now is cheaper and safer than maintaining
a compatibility layer for an unused schema.

## Implementation status — 26 September 2026

The ADR 0084 foundation has now been implemented on draft PR #195 without
adding any speculative retailer crawler.

Implemented:

- `ProductAwardCandidate` no longer assumes every product is a private label;
- explicit `RetailEvidence` distinguishes `private_label`, `exclusive`
  and `listed` relationships and can retain exact retailer product ID, EAN,
  exact product URL and variant evidence;
- award event identity remains source-native and independent of retail price,
  stock and media;
- state schema is version 6; no compatibility layer was added because the
  feature has not yet established production state;
- the shared core no longer ranks unrelated award vocabularies;
- OCU owns its own `Mejor del Análisis` vs `Compra Maestra` precedence;
- OCU coverage includes DIA private-label names in addition to the earlier
  locally relevant allowlist, while Alcampo / Auchan is intentionally ignored;
- labels identical to retailer names such as Carrefour or DIA require separate
  product-brand evidence and are not accepted merely because the retailer name
  appears in parentheses;
- OCU editorial facts are separated into report-global method facts and
  product-local distinctions so one product's tasting/quality statement cannot
  leak to another result;
- the deterministic renderer distinguishes private label, exclusive and listed
  products;
- publication-time retail enrichment now accepts a list of exact package
  variants rather than one chosen price, so every verified package/price/unit
  price can be shown without transferring an award to another SKU;
- producer facts require an explicit production country; city/region remains
  optional additional context;
- headlines now lead with product + supermarket + award/result and keep numeric
  score in the article body;
- repeated award methodology renders in Telegram HTML
  `<blockquote expandable>` rather than occupying the visible daily post;
- OCU publication now requires overall/global score >=85/100 and sorts its own
  eligible candidates by that native score; high partial subscores cannot pass
  the gate;
- delivery queue, per-source baseline, at-most-once Telegram semantics and
  one-item-per-day policy remain unchanged.

The feed is intentionally **at most one** publication per day, not a quota.
If no source-specific exceptional candidate passes its gate, publication stays
silent. Future award adapters without a comparable overall 0-100 score must
define a reviewed equivalent top-tier result such as category winner, Best of
Class or Super Gold rather than treating any medal as sufficient.

Deliberately **not** implemented yet:

- no generic retailer catalogue search;
- no continuous or daily scans of the seven in-scope retailers;
- no Mercadona or Masymas parser before their exact browser-free contract is
  separately proven;
- no real publication-time retailer HTTP refresh yet — the renderer and data
  model now expose the safe boundary for it, but no source-specific retail
  adapter is registered;
- no retailer product-photo publication; the default remains text-only unless a
  source-specific reuse right is documented;
- no new award source is registered beyond OCU.

Validation on the final functional head before removing the temporary
branch-only workflow:

- Python compileall: passed;
- product-award modules: **46 tests passed**;
- complete repository suite: **1337 tests passed**;
- temporary validation workflow was removed from the final diff.
- live `product-awards-preview` on 26 September 2026 returned no eligible item after the >=85 OCU gate; this is expected because WCCC and retailer price-refresh adapters are not yet registered.

The next implementation unit should therefore be one **real retailer evidence
adapter backed by a proven live source contract**, not another generic
framework. Consum is the strongest clean candidate because its public catalogue
can expose a stable product code and often EAN; ALDI, Lidl and DIA are also
strong candidates. Mercadona and Masymas still need their dedicated
browser-free contract probes. Alcampo / Auchan remains intentionally excluded
for local-utility reasons.

