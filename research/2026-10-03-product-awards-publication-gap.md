# Product Awards publication-gap forensic — 2026-10-03

## Scope

This investigation explains why the Product Awards workflow did not publish on
2 October or 3 October 2026 after the three-local-day cooldown expired.

No production state or application code was changed during the investigation.

## Production control path

The production evidence rules out scheduler/offline/state causes:

- Product Awards cron is installed for 14:20 Europe/Madrid;
- `crond` was running;
- the job ran at 14:20 on both 2 and 3 October;
- Telegram and retailer HTTP paths were reachable;
- `last_delivery_day=2026-09-29`;
- `uncertain_event=null`;
- the workflow was due and still had unpublished candidates.

All registered award-authority checks also passed during the read-only control
probe.

## Root cause A: NALTROS is a product-specific ALDI error state

The runtime exact URL is:

`https://www.aldi.es/p/cava-brut-190300.html`

The historical reviewed alias is:

`https://www.aldi.es/producto/cava-brut-190300.html`

Both return HTTP 200 with the same current Next.js build and the same product
query, but both contain:

- `pageProps.hasError=true`;
- `page=None`;
- `apiData=None`;
- a very small error-shell HTML response;
- no current NALTROS product payload.

Changing User-Agent does not change the result.

Two independent ALDI controls on the same build behave differently:

- `queso-curado-181600`;
- `queso-de-oveja-ahumado-v-de-navarra-601233500`.

Both return full product pages, `hasError` is absent/false, `apiData` is a
JSON string and the exact product ID is present.

Therefore the NALTROS failure is not:

- phone connectivity;
- User-Agent blocking;
- global ALDI frontend drift;
- a global Next.js contract change;
- the `/p` versus `/producto` route;
- the saved NALTROS object ID/marker parser.

The precise runtime fact is narrower: ALDI's current product-detail backend does
not resolve product 190300 into a current product payload. This may mean
delisting or a product-specific ALDI backend fault. The evidence does not prove
which, so runtime must fail closed without asserting either publicly.

## Root cause B: Consum exposes a stale base-image field

Five independent current Consum candidates were probed from the production
phone:

1. Celta +Proteína;
2. Takis Blue Heat;
3. ELPOZO ExtraTiernos;
4. Nescafé Latte Baileys;
5. Ambar Especial.

For every candidate:

- exact EAN matches the reviewed EAN;
- product name is valid;
- current price is present;
- `productData.imageURL` points to a base filename such as
  `7475171.jpg`;
- that base URL returns HTTP 404;
- the same payload's `media[].url` contains one or more numbered assets such
  as `7475171_001.jpg`;
- those numbered URLs return valid `image/jpeg` responses.

Representative Celta payload:

- stale base: `7475171.jpg` -> HTTP 404;
- `media[0]`: `7475171_001.jpg` -> valid JPEG;
- `media[1]`: `7475171_002.jpg` -> valid JPEG.

The same pattern reproduced across all five products, proving a systematic
Consum image-contract issue rather than one broken asset.

## Why the current recovery cannot work

The current retailer helper prefers `productData.imageURL` whenever that field
contains a syntactically valid HTTPS URL. It examines `media[]` only when the
base field is missing.

The selected publication therefore contains the stale base URL.

Telegram then returns:

`RICH_MESSAGE_PHOTO_NO_MEDIA_FOUND`

This is expected because the selected URL itself returns 404.

ADR 0084's recovery then downloads `publication.offer.image_url`, which is the
same stale base URL, so the phone receives:

`MEDIA-HTTP-404`

The fallback therefore retries the wrong asset and cannot recover.

## Correction to the 29 September diagnosis

The 29 September research observed that
`7475171_001.jpg` was publicly reachable and concluded that Telegram's remote
fetch path was the primary failure.

That conclusion was incorrect because production was not actually sending that
URL. It was sending `7475171.jpg`, a different asset that returns 404.

Telegram was not the root cause of the observed Celta rejection. The root cause
was retailer-image selection inside Product Awards. The multipart fallback
remains useful for a genuinely reachable media URL that Telegram cannot fetch,
but it does not repair selection of a nonexistent URL.

## Secondary inefficiency

After each Consum media failure, delivery selection restarts. NALTROS is then
verified again and fails again, so one invocation may repeat the same ALDI
request several times.

This does not cause the missing post. The final ADR 0092 does not add a
candidate-attempt cache solely for this symptom: making media non-fatal removes
the normal delivery branch that caused the selector to restart after each
Consum image failure.

## Retailer-diversity clarification

The 3 October follow-up requirement is **preference, not prohibition**.

Publication is primary: if at least one normal candidate is valid on a due run,
retailer diversity must not be the reason for silence. The selector should
first prefer a retailer different from the last confirmed post, while
preserving authority rank semantics, then fall back to the ordinary selector
and allow the same retailer when no different-retailer candidate is
publishable.

The current pool is still unacceptably concentrated in Consum from an editorial
perspective. That concentration should be repaired by rebuilding the reviewed
registry across Mercadona, Lidl, DIA, Carrefour, ALDI, Consum and Masymas
rather than by suppressing valid Consum posts.

## Remediation boundary

The approved design is ADR 0092.

It requires no new infrastructure:

- correct Consum media-field precedence;
- explicit and precise ALDI product-error/contract-drift distinction;
- retailer preference derived from existing published-event history;
- one bounded selection scan with an in-memory same-retailer fallback;
- existing bounded Telegram upload recovery retained;
- no-image Rich Message delivery after deterministic media-path failure.

No code was changed as part of this research/documentation checkpoint.
