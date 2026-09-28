# ADR 0084: Exact rich Product Awards runtime

Date: 2026-09-28

## Status

Accepted. This refines the first Product Awards implementation in ADR 0083.

## Context

Production probes showed that the original reviewed catalogue had two problems:
some retailers were no longer in scope or were not safely refreshable from
Termux, and the public text-only card did not identify products well on mobile.

The phone must remain a small one-shot Termux runtime. Product Awards are rare,
so the runtime should not add a browser, local image processor, LLM dependency,
queue, daemon, or new scheduler.

## Decision

Keep the existing three-day cooldown, exclusive lock, state schema and
ambiguous-delivery reservation.

Replace the reviewed publication pool with only exact, production-verified
retailer identities. Consum and Masymas use saved product IDs plus an exact EAN
check before accepting current price and media. ALDI uses its saved exact
product object identity. A source or retailer contract drift fails closed for
that candidate.

Use first-party retailer media already returned by the exact product detail.
For the verified Masymas CDN, prefer the working 300x300 variant over 135x135.
Do not add image-processing dependencies.

Publish through Telegram Rich Messages:
- first-party product image;
- a separate paragraph block for the headline;
- short deterministic source-specific prose;
- current retailer price;
- expandable methodology block;
- standard group footer.

Do not include award or retailer links in the public article.

Keep editorial generation deterministic. Do not require Gemini, OpenRouter or
another LLM for Product Awards publication. The runtime may use only facts
already validated by the award and retailer adapters.

The initial reviewed pool is:
- NALTROS Brut / OCU / ALDI;
- Celta +Proteína / Producto del Año / Consum;
- Takis Blue Heat / Producto del Año / Consum;
- ELPOZO ExtraTiernos / Producto del Año / Consum;
- Nescafé Latte Baileys / Producto del Año / Consum;
- Ambar Especial / World Beer Awards / Consum;
- Mahou Sin Filtrar / World Beer Awards / Masymas.

## Consequences

The publication path stays dependency-free and cheap on Termux. Exact identity,
price and photo failures omit a candidate rather than producing a weak or
misleading post. Adding another award product requires a reviewed source fact
and an exact current retailer locator, but not a new runtime subsystem.
