# SafeBeach daily beach-root sea context

- Date: 2026-10-06
- Scope: resident-facing daily beach root and later beach-change replies
- Status: research / product recommendation; no runtime behavior changed

## Question

Now that SafeBeach is published in a separate daily beach message instead of
being constrained by the short Morning Digest, should the root include more of
the current beach-service context (jellyfish, sea temperature, sea state, etc.),
and should later beach-change replies repeat or update that context?

The requirement is to add useful beach-specific information without duplicating
routine AEMET weather, creating noisy updates, or adding source requests.

## Existing source and product contract

Guardamar municipality links to the public SafeBeach page used by the local
beach service. Existing source research and production fixtures have verified
these public per-beach fields in the embedded `window.SB_MARKERS` data:

- `beachName`;
- `hasActividad`;
- `serviceEnded`;
- `textoBandera` / `colorBandera`;
- `waterTemp`;
- `viento`;
- `windDeg`;
- `oleaje`;
- `medusas`;
- `hora`.

The current adapter already parses all of the above fields. It retains current
flags and explicit jellyfish state for all verified Guardamar zones, while
`sea_temperature_c`, beach wind and `sea_state` are retained only from
Centre / Babilònia.

The six known zones remain:

1. Centre / Babilònia;
2. Roqueta;
3. Vivers;
4. Montcaio;
5. Camp;
6. Ortigues.

SafeBeach's own product documentation advertises a broader platform capability,
including occupancy, beach closure, waves / rip currents, wind, cleanliness and
jellyfish. Those product-level capabilities are **not** automatically accepted
as fields in Guardamar's public `SB_MARKERS` contract. A field must be
observed and validated on the municipality-linked Guardamar public page before
the bot can publish it.

Sources:

- https://info.safebeach.es/guardamar-del-segura/listado?lng=cas
- https://safebeach.es/como-funciona-safe-beach/
- `research/2026-07-26-safebeach-guardamar.md`
- `research/2026-07-27-aemet-safebeach-data-inventory.md`
- `research/2026-07-30-safebeach-client-practices.md`
- `adr/0018-nearby-beach-flags.md`
- `adr/0031-bounded-beach-change-monitoring.md`
- `adr/0032-complete-guardamar-beach-flags.md`
- `adr/0094-safebeach-october-query-window.md`

## Important semantics

### `oleaje` is not a measured wave height

The current Guardamar public contract exposes qualitative values normalized by
the adapter as:

- calm;
- slight;
- moderate;
- rough;
- very rough.

This can be rendered as a current sea-state description. It must **not** be
presented as a wave height in metres. No verified public Guardamar SafeBeach
field currently supplies numeric wave height.

### SafeBeach water temperature is different from the AEMET beach forecast

The Morning Digest already carries the AEMET beach forecast for sea
temperature / sea state where available. SafeBeach can expose a current
operational value entered through the beach service. These are different facts.

If SafeBeach temperature is shown in the beach root, the message should make
its current-beach context clear rather than silently replacing or duplicating
the AEMET forecast.

### Wind is currently low-value duplication

SafeBeach exposes beach wind direction and speed, but the Morning Digest
already has AEMET wind. Unless a later product need specifically asks for a
lifeguard-local wind observation, routine SafeBeach wind should not be added to
the beach root. Omitting it keeps the card shorter and avoids two competing
wind readings without explanation.

## Previous jellyfish decision and why the context changed

ADR 0018 allowed only an explicit positive jellyfish row and intentionally
suppressed routine negative reassurance. That decision was made for the compact
Morning Digest.

The separate daily beach root has a different job: it is the day's
self-contained operational snapshot. A compact negative jellyfish status can
therefore add real value, but only when it is based on explicit current
SafeBeach `No` values. Missing / unknown jellyfish data must never become
`медуз нет`.

## Recommended daily beach root

Keep the existing flag grouping as the primary safety block.

Add a compact **current beach-service context** block using facts already
available from the same SafeBeach response. No new request is needed.

Recommended information:

1. all current verified flags, grouped exactly as today;
2. jellyfish summary across the same current verified beach set;
3. Centre / Babilònia SafeBeach sea temperature when present;
4. Centre / Babilònia qualitative sea state when present;
5. existing explicit municipal bathing notice when present.

Do **not** add routine AEMET wind, air temperature, UV, precipitation or
forecast rows to this message.

A compact normal-day shape could be:

```text
🏖 Пляжи Гуардамара сегодня

🟢 На всех пляжах зелёные флаги
✅ Купание разрешено

🌊 Centre / Babilònia: вода 25° • море спокойное
🪼 Медузы: не отмечены
```

A mixed day could be:

```text
🏖 Пляжи Гуардамара сегодня

🔴 Красный флаг
Centre / Babilònia
⛔ Купание запрещено

🟡 Жёлтые флаги
Roqueta, Vivers
⚠️ Купаться с осторожностью

🌊 Centre / Babilònia: вода 25° • море умеренное
🪼 Медузы: Roqueta
```

The sea-context line is explicitly scoped to Centre / Babilònia because the
current normalized model does not retain temperature / sea state per beach.
Do not imply that one Centre value applies to all Guardamar beaches.

## Recommended jellyfish rendering rule

Let the displayed flag snapshot define the current beach set.

- If one or more of those beaches has explicit `medusas = Sí`, list only the
  positive beach names: `🪼 Медузы: Roqueta, Ortigues`.
- If **every beach in the displayed current set** has an explicit
  `medusas = No`, render `🪼 Медузы: не отмечены`.
- If there are no positives but one or more displayed beaches has unknown /
  missing jellyfish state, omit the jellyfish row. Do not convert partial
  negatives into a coast-wide all-clear.

This gives the requested routine daily reassurance without weakening the
project's fail-closed rule.

## Later change replies

Keep later beach-change replies narrow and event-like.

They should continue to show:

- exactly what changed (flag and/or explicit jellyfish transition);
- the latest confirmed flags as the current safety snapshot.

They should **not** repeat or trigger on:

- sea temperature changes;
- qualitative sea-state changes;
- SafeBeach wind changes.

Those fields are useful once in the daily root but are too volatile / low-value
to create Telegram alert traffic.

If the root is being edited as part of the existing 10:10-10:40 initial
SafeBeach lifecycle, passive sea context may refresh incidentally from the same
whole valid response. It must not cause an additional request, edit or
notification on its own. After the initial root lifecycle, temperature and sea
state stay non-alerting.

A later flag-only reply therefore remains compact:

```text
🏖 Изменения на пляжах:
• Centre / Babilònia: 🔴 → 🟡

Последние подтверждённые флаги:
  🟡 Centre / Babilònia
```

If jellyfish actually appear or disappear, that explicit transition remains a
material change and can be included in the same confirmed update.

## Why not add per-beach sea conditions now

The raw SafeBeach record carries sea/wind/temperature fields per item, but the
current normalized model intentionally retains those conditions only for
Centre / Babilònia. Expanding the model, state and rendering to all six beaches
would be justified only if live evidence shows materially different values that
residents benefit from seeing.

For the current requirement, that expansion is unnecessary:

- all six flags are already preserved;
- all six explicit jellyfish states are already preserved;
- Centre current water temperature and sea state are already preserved;
- the proposed daily enrichment requires no new request and very little new
  presentation logic.

This is the preferred minimal implementation path.

## Additional SafeBeach fields: evidence gap

SafeBeach's general product page advertises other operational concepts
(occupancy, beach closure, rip currents, cleanliness, etc.). Existing Guardamar
research has not yet established a stable public-field contract for them.

Before adding any of those facts, perform one read-only active-service probe of
the Guardamar `SB_MARKERS` item keys and representative values. Do not add a
second production source, API subscription, browser, raw-response archive or
generic dynamic-field renderer.

## Proposed implementation boundary

If this product direction is approved, the smallest implementation should be:

- reuse the existing `BeachStatus.sea_temperature_c`, `sea_state` and
  `jellyfish_states`;
- change only daily beach-root rendering and its focused tests;
- preserve the later operational state machine: changes remain only flag and
  jellyfish;
- add no new cron row, network request, dependency, persistent field or source.

A separate per-beach-conditions model is explicitly deferred until source
evidence demonstrates a need.
