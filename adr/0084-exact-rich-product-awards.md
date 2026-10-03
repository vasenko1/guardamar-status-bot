# ADR 0084: Exact rich Product Awards runtime

Date: 2026-09-28

## Status

Accepted. This refines the first Product Awards implementation in ADR 0083. ADR 0092 further refines Consum media selection, ALDI product-error handling, per-invocation retries and consecutive-retailer rotation.

## Context

> **2026-10-03 correction:** the 29 September `RICH_MESSAGE_PHOTO_NO_MEDIA_FOUND` incident was not proved to be a Telegram/CDN fetch defect. Forensic production probes later showed that the runtime selected Consum's stale `productData.imageURL`, which returned HTTP 404, while the same official payload exposed working numbered `media[].url` assets. ADR 0092 supersedes the Consum media-selection assumption below; the bounded multipart upload path remains valid only after a real first-party image URL has been selected.

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

If Telegram deterministically rejects a retailer image because its servers
cannot fetch the remote HTTP(S) media, clear the first delivery reservation and
attempt one bounded local recovery for pinned first-party retailer media. The
phone may download at most 700 KiB of JPEG, PNG or WebP from an allowlisted
retailer CDN, keep it only in a private temporary file, and resend the same Rich
Message once using Telegram's explicit InputRichMessage media attachment with
`attach://`. The temporary file is deleted before exit.

If that bounded local media read fails, this ADR originally omitted the
candidate. ADR 0092 supersedes that outcome: image delivery is enrichment, not
product eligibility. After an explicit deterministic media-path failure, the
same already-verified article may be delivered as a Rich Message without media.
Ambiguous delivery still blocks every automatic fallback send.

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

The publication path stays dependency-free and cheap on Termux. Exact identity
or current-price failure still omits a candidate. ADR 0092 makes product media
optional so a photo failure degrades presentation rather than discarding a
verified article. Adding another award product requires a reviewed source fact
and an exact current retailer locator, but not a new runtime subsystem.
