# Hidraqua Guardamar ArcGIS experiment

## Question

Can the public Hidraqua / Veolia ArcGIS layer provide bounded, direct data for
water-supply interruptions in Guardamar del Segura, without browser automation?

## Sources checked

- Hidraqua official public pages: [map](https://hidraqua.veolia.es/mapa-de-obras-y-afectaciones)
  and [notices](https://hidraqua.veolia.es/avisos), accessed 2026-09-07.
- Public ArcGIS item
  [`a9d79aae8ed84ffa9f5ee9f2e0ca7839`](https://www.arcgis.com/sharing/rest/content/items/a9d79aae8ed84ffa9f5ee9f2e0ca7839?f=pjson),
  title `Cierres_webPublicas_v`, access `public`, owner `usr_publisherAO`.
- Its public FeatureServer layer
  [`0`](https://services3.arcgis.com/5VitVYyVLQYnzXCo/arcgis/rest/services/Cierres_webPublicas_v/FeatureServer/0?f=pjson),
  accessed 2026-09-07.

The service and layer descriptions are empty; the layer is a public read-only
view (`capabilities: Query`) and advertises `cacheMaxAge: 30`. No token was
sent, and the metadata and query requests succeeded.

## Schema and documented meaning

The following relevant fields are present. None has a coded-value domain, but
the field descriptions provide the only verified expansion of the codes.

| Field | Alias | ArcGIS type | Verified meaning |
| --- | --- | --- | --- |
| `CI_ID` | `Ident. Cierre` | integer | interruption identifier; metadata pattern `NNNN` |
| `CI_FH_INI_PREV` | `Previsión corte` | date | predicted interruption start; format hint `dd/mm/yyyy hh:mi` |
| `CI_FH_FIN_PREV` | `Previsión restablecimiento` | date | predicted restoration; same format hint |
| `CI_DIRECCION` | `Dirección Intervención` | string | metadata: address of the fault point |
| `CI_CALLES` | `Otras Calles` | string | other streets |
| `CI_ESTADO` | `Estado` | string | `4AP`: `Aprobado`; `5EC`: `En curso` |
| `CI_MOTIVO` | `Motivo` | string | `AVE`: `Avería`; `***`: `Actuación de mejora del servicio` |
| `COD_MUNI` | `Municipio` | string | municipality code |

Thus the proposed meanings of `4AP`, `5EC`, and `AVE` are confirmed by the
published layer metadata, rather than inferred from the abbreviations. The
metadata does **not** document a complete code list beyond those values.

`OBJECTID` is the FeatureServer object identifier and `GlobalID` exists, but
neither is the business identifier displayed as `Ident. Cierre`.

## Current Guardamar response

At the observation time, the direct query below returned one active row.

```text
where=COD_MUNI='03076' AND CI_ESTADO IN ('4AP','5EC')
outFields=CI_ID,CI_FH_INI_PREV,CI_FH_FIN_PREV,CI_DIRECCION,CI_CALLES,CI_ESTADO,CI_MOTIVO,COD_MUNI
returnGeometry=false
f=json
```

Raw result (public operational data, captured 2026-09-07):

```json
{
  "features": [
    {
      "attributes": {
        "CI_ID": 218932,
        "CI_FH_INI_PREV": 1788781729000,
        "CI_FH_FIN_PREV": 1788789600000,
        "CI_DIRECCION": "Calle Currica 51-51, 03140, Guardamar del Segura, Alicante, Comunidad Valenciana (Urbanització Bonavista)",
        "CI_CALLES": "LA NANSA, COSTABELLA",
        "CI_ESTADO": "5EC",
        "CI_MOTIVO": "AVE",
        "COD_MUNI": "03076"
      }
    }
  ]
}
```

An unrestricted `COD_MUNI='03076'` count was also `1`, and an aggregate by
status and motive was only `5EC` / `AVE`: `1`. Therefore, on this observation
the public view did not expose completed or historical Guardamar rows. This is
useful evidence that it is an operational current-state view, but it does not
prove how long a finished row remains visible or establish every possible
lifecycle state.

## Date check

ArcGIS returned integer epoch milliseconds. Interpreting them as UTC and then
converting with Python `zoneinfo.ZoneInfo("Europe/Madrid")` gave:

| Source value | UTC | Europe/Madrid |
| --- | --- | --- |
| `1788781729000` | 2026-09-07 11:48:49 UTC | 2026-09-07 13:48:49 CEST |
| `1788789600000` | 2026-09-07 14:00:00 UTC | 2026-09-07 16:00:00 CEST |

The probe uses `zoneinfo`, so normal CET/CEST transitions are handled by the
timezone database; it must not add a fixed offset.

## Isolated proof of concept

[`hidraqua_probe.py`](hidraqua_probe.py) uses the lightweight `requests`
package and is not imported by the bot. It uses one 20-second bounded request, rejects HTTP,
network, malformed-JSON, oversized-response, and ArcGIS JSON errors, prints
the normalized local dates, and never sends Telegram messages.

Install `requests` only in the environment used for this standalone experiment;
it is intentionally not added to the Telegram bot's production dependencies.

```sh
python research/hidraqua_probe.py
python research/hidraqua_probe.py --raw
python research/hidraqua_probe.py --all-guardamar
python research/hidraqua_probe.py --save-raw /safe/temporary/result.json
```

Raw data is saved only by the explicit `--save-raw` option; routine operation
does not create a raw-response archive.

## Monitoring recommendation

Use one externally scheduled, short-lived poll every 10 minutes initially
(five minutes is reasonable only after observing a practical need). Use the
active query above, a 20-second timeout, a 512 KiB response limit, and no
internal retry; the next scheduled run provides bounded recovery. Respect the
published 30-second cache hint and avoid bursts. No rate-limit header or
documented quota was observed in this small experiment, so production should
log HTTP 429 / `Retry-After` and back off or omit the run rather than retrying
indefinitely.

Maintain one small atomic local state keyed primarily by `CI_ID`. `CI_ID` is
the supplied business interruption identifier and is preferable to `OBJECTID`,
but this one-row observation cannot prove uniqueness/reuse across time; retain
the first-seen time and a fingerprint of status, motive, address, streets and
planned dates. Treat a changed fingerprint under the same `CI_ID` as `UPDATE`.

| Observed state | Action |
| --- | --- |
| First active `CI_ID` | `NEW` (the status/motive wording remains source-exact) |
| Active `CI_ID` with changed fingerprint | `UPDATE` |
| Missing from one successful active response | `DISAPPEARED`, internal only; do not say service is restored |
| Missing on a second successful poll, then query `COD_MUNI='03076' AND CI_ID=<id>` without status filtering | If a row exists, retain its actual status as an update; if it is absent, record only `CONFIRMED_CLOSED` after the second absence and without asserting a reason or restoration time |

If either active response or the confirmation query fails, preserve state and
publish nothing. A later frontend/API observation is still needed to learn
whether this view deletes completed rows immediately and whether another
closed-state code is ever exposed. Until then, the API is sufficient for a
conservative **new/changed active interruption** monitor without browser
automation, but not sufficient to make a strong automatic claim that water
service has been restored.

## Recommendation

The direct public FeatureServer is a viable production source for a narrowly
bounded active-event monitor: it identifies Guardamar, exposes a verified
planned/in-progress status and fault/improvement motive, addresses, streets,
and planned times. Keep it isolated until the product approves a recurring
alert feature. Before user-facing closure notices are enabled, collect several
real event transitions and document whether `CI_ID` persists and whether a
completed state is queryable.

## Semantic follow-up (2026-09-08)

The official frontend calls this a `Mapa de obras y afectaciones` in the water
network. Its date fields are `Previsión corte` / `Previsión restablecimiento`,
but `CI_DIRECCION` is explicitly the fault/intervention-point address and
`CI_CALLES` is only `Otras Calles`. This establishes a network intervention,
not a guaranteed outage at each address. The separate official notices page
uses explicit `Corte de suministro` language but does not document a one-to-one
mapping to FeatureServer rows. Automation must therefore use conservative
network-work wording.

The active layer currently has municipalities with 2, 3, and 4 simultaneous
IDs. Guardamar has one in both observations; this is not a one-event limit.
