# Product Awards Rich Message media recovery — 2026-09-29

> **Correction — 2026-10-03:** this document records the original incident and decision, but its root-cause conclusion was incomplete. Production later proved that the runtime sent Consum's stale base `productData.imageURL` (HTTP 404), not the working `media[0].url` ending in `_001.jpg` that was manually verified here. Telegram therefore rejected a genuinely missing asset, and the local recovery retried the same missing URL. See `research/2026-10-03-product-awards-publication-gap.md` and ADR 0092. The multipart recovery remains useful only after a reachable exact first-party image has been selected.

## Incident

The first controlled Product Awards recovery run after the deleted NALTROS post
selected the next reviewed category while the state still contained:

- `last_delivery_day = 2026-09-28`;
- `category_cursor = 1`;
- no uncertain delivery.

Telegram rejected the Celta +Proteína publication with deterministic HTTP 400:

`Bad Request: RICH_MESSAGE_PHOTO_NO_MEDIA_FOUND`

The failed send did not consume the slot: `last_delivery_day`, published
history and category cursor remained unchanged, and `uncertain_event` was
cleared.

## Evidence

The candidate was:

- event: `dairy_drinks:pda-2026:celta-proteina`;
- retailer: Consum;
- exact EAN: `8414044004122`;
- public Consum product page:
  `https://tienda.consum.es/es/p/batido-proteina-sabor-cafe/7475171`.

Consum currently exposes a public first product image on:

`https://cdn-consum.aktiosdigitalservices.com/tol/consum/media/product/img/300x300/7475171_001.jpg?t=20260424170004`

The image is a normal public 300x300 JPEG and is retrievable outside Telegram.
The failure is therefore Telegram's upstream fetch path for that Rich Message
media, not a missing product, failed EAN match, or malformed Product Awards
state.

Telegram Bot API 10.2+ supports `InputRichMessage.media` and explicit
`InputMediaPhoto` attachments referenced from Rich HTML using
`tg://photo?id=<id>`. `InputMediaPhoto.media` may use
`attach://<file_attach_name>` with multipart/form-data.

## Decision

Keep the normal zero-copy URL path first because it is cheapest and already
works for ALDI.

Only after an explicit deterministic Rich Message remote-media rejection:

1. clear the failed delivery reservation;
2. download the exact already-reviewed retailer image once with the existing
   bounded transport;
3. accept only JPEG, PNG or WebP, at most 700 KiB, from an explicit retailer
   media-host allowlist;
4. keep the bytes only in a private temporary file;
5. reserve the same event again;
6. resend the same rich article once with `InputRichMessage.media` and a
   multipart `attach://` photo;
7. delete the temporary file before exit.

This was the original 29 September decision. ADR 0092 supersedes the
candidate-omission outcome: after a deterministic media-path failure, a
verified product may be sent as the same Rich Message without an image. An
ambiguous send still leaves the reservation uncertain and forbids every
automatic fallback.

No browser, image processor, persistent media cache, new daemon, scheduler or
dependency is added.
