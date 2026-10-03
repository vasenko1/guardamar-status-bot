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

This does not cause the missing post, but it is unnecessary network traffic.
ADR 0092 therefore limits repeated candidate verification within one process
without adding persistent negative cache state.

## Retailer-diversity requirement

Product Awards now also has a strict public sequencing requirement: two
confirmed posts must not feature the same supermarket consecutively.

This must preserve authority rank semantics. A candidate blocked only because
its retailer matches the last confirmed retailer defers that category for the
current invocation; the runtime must not silently demote to a lower-ranked
product from another supermarket merely to satisfy variety.

The current pool is strongly concentrated in Consum. With NALTROS currently
unresolvable and Mahou/Masymas already published, a successful Consum post may
therefore be followed by intentional silence until a different retailer has a
reviewed eligible candidate.

## Remediation boundary

The approved design is ADR 0092.

It requires no new infrastructure:

- correct Consum media-field precedence;
- explicit ALDI product-error recognition;
- one small last-retailer state value;
- strict retailer anti-repeat selection;
- one invocation-local attempted-candidate set;
- existing bounded Telegram upload recovery retained.

No code was changed as part of this research/documentation checkpoint.
