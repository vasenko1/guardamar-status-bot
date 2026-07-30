# Decision Log

This is the concise index of important product and architecture decisions.
Detailed decisions belong in `adr/`.

| Date | Decision | Context and reason | Record |
| --- | --- | --- | --- |
| 2026-07-30 | Harden the remaining municipal and Gemini transports | Exact-host redirects, MIME/size validation, stable diagnostics, and corrupt-snapshot recovery improve reliability without new polling, retries, sources, or dependencies. | `adr/0026-harden-municipal-source-boundaries.md` |
| 2026-07-30 | Share one strict Telegram client and bound Agenda detail reads | Exact-host redirects, type/size validation, and structured failures harden all Telegram operations; three concurrent Agenda reads avoid a long sequential optional-source delay without adding requests or dependencies. | `adr/0025-bounded-telegram-and-agenda-clients.md` |
| 2026-07-30 | Fill up to three SafeBeach flag slots from named Guardamar beaches | Centre / Babilònia, Roqueta, and Vivers remain preferred, while Montcaio, Camp, and Ortigues prevent one unavailable preferred record from unnecessarily shrinking the useful beach status. Flags are never averaged or renamed. | `adr/0024-safebeach-public-client.md` |
| 2026-07-30 | Harden the public SafeBeach adapter without history or caching | One bounded same-day HTML request, strict host/type/schema checks, and fail-closed conflict handling improve safety while external five-minute invocations remain the only retry mechanism. | `adr/0024-safebeach-public-client.md` |
| 2026-07-29 | Replace fixed AEMET delays with bounded protocol-aware recovery | Retry only transient failures, honor usable `Retry-After`, repeat the complete two-step request, keep the key off product URLs, and convert UTC forecast periods to Madrid time. | `adr/0023-aemet-client-reliability.md` |
| 2026-07-29 | Add stable source diagnostics to private previews only | The operator needs a transferable code and concrete failure stage for every consulted source; group messages remain free of technical noise and secrets. | `adr/0010-private-preview-listener.md` |
| 2026-07-29 | Publish available SafeBeach flags without waiting for all three selected beaches | One missing record must not hide current official flags for other beaches; absent beaches are omitted, Centre is labeled as the combined Centre / Babilònia zone, and generic flag meanings are omitted. | `adr/0018-nearby-beach-flags.md` |
| 2026-07-29 | Publish at 07:30 and conditionally replace after bounded SafeBeach checks | City information arrives early; one later full replacement adds verified beach data without leaving two messages or keeping a process asleep. | `adr/0021-two-stage-daily-replacement.md` |
| 2026-07-29 | ~~Use one AEMET retry policy everywhere: two retries at two-minute intervals~~ | Superseded by protocol-aware recovery in ADR 0023. | `adr/0021-two-stage-daily-replacement.md` |
| 2026-07-26 | Target Termux on a weak Android device | The bot must run cheaply on limited hardware and unstable mobile internet. | Project brief |
| 2026-07-26 | ~~Use one lightweight Python process with Telegram long polling~~ | Superseded: the process is now one-shot and outbound-only. | `adr/0008-one-shot-morning-execution.md` |
| 2026-07-26 | Keep persistent state local and small | Server databases are unnecessary for the planned scope. | Project brief |
| 2026-07-26 | Make Morning Digest the first feature | It addresses the initial validated user need. | Project brief |
| 2026-07-26 | Reserve, but do not define, one future feature | Preserve limited extensibility without speculative design. | Project brief |
| 2026-07-26 | Prefer official sources and omit unreliable content | Trust and signal are more important than apparent completeness. | Project principles |
| 2026-07-26 | Use AEMET OpenData for the first Guardamar weather slice | AEMET is the responsible official authority and provides structured forecast, observation, and CAP warning products. | `research/2026-07-26-aemet-mvp-source.md` |
| 2026-07-26 | Use Rojales station `7261X` for current conditions | AEMET lists no station in Guardamar and identifies Rojales as the nearest station at 5.3 km; the digest must label it. | `docs/kb/06_Data_Sources.md` |
| 2026-07-26 | Keep the first slice one-shot and dependency-free | Fetching, normalization, and formatting can be validated before adding Telegram delivery or scheduling, with minimal Termux cost. | `docs/kb/05_Features.md` |
| 2026-07-26 | Deliver to one configured Telegram destination with standard-library HTTP | The MVP needs direct Bot API delivery without a webhook or Telegram framework. | `adr/0001-daily-telegram-delivery.md` |
| 2026-07-26 | ~~Claim each local date before collection~~ | Superseded by success-only state. | `adr/0008-one-shot-morning-execution.md` |
| 2026-07-26 | ~~Use an internal scheduler with pre-noon catch-up~~ | Superseded by one external 07:30 invocation. | `adr/0008-one-shot-morning-execution.md` |
| 2026-07-26 | Add Guardamar SafeBeach as an optional source | The municipality links to this official public status; source failure must not block AEMET delivery. The original all-beach selection rule is superseded by ADR 0006. | `adr/0002-optional-safebeach-status.md` |
| 2026-07-26 | Omit the Rojales location label from the digest | Keep the user-facing message focused on Guardamar while retaining the observation origin in project documentation. | `docs/kb/06_Data_Sources.md` |
| 2026-07-26 | Render the Morning Digest fully in Russian | Keep the single daily message consistent and immediately readable; unknown AEMET event names use a neutral Russian fallback. | `docs/kb/05_Features.md` |
| 2026-07-26 | Add one compact later-day wind comparison to the digest contract | A single deterministic line adds planning value using the existing AEMET forecast, without new sources, architecture, or a larger weather section. | `adr/0003-compact-wind-forecast.md` |
| 2026-07-26 | Accept one fixed phone-first Morning Digest layout | A learned visual order, three compact mandatory rows, inline wind forecast, and optional empty-section omission make the message scannable in under five seconds. | `adr/0004-phone-first-digest-layout.md` |
| 2026-07-27 | ~~Accept private allowlisted operator commands through long polling~~ | Superseded: inbound polling was removed with the resident process. | `adr/0008-one-shot-morning-execution.md` |
| 2026-07-27 | ~~Use AEMET Centro / La Roqueta water temperature only as a SafeBeach fallback~~ | Superseded: AEMET is now the primary representative sea forecast. | `adr/0019-aemet-sea-forecast.md` |
| 2026-07-27 | Add at most two same-day events from Agenda Guardamar | Its official event pages expose deterministic title and start-time fields; optional failure stays silent and no media or AI processing is needed. | `adr/0007-agenda-guardamar-events.md` |
| 2026-07-27 | ~~Defer Policía Local traffic integration~~ | Superseded for one explicit official festival restriction; the site still is not treated as a general traffic feed. | `adr/0009-explicit-police-traffic-notice.md` |
| 2026-07-27 | ~~Run one external-triggered Morning Digest process at 07:30~~ | The one-shot model remains; only the publication time is superseded by ADR 0016. | `adr/0008-one-shot-morning-execution.md` |
| 2026-07-27 | ~~Add one explicit Policía Local festival traffic notice~~ | Superseded after the linked PDF proved more precise than the HTML summary. | `adr/0022-structured-mobility-measures.md` |
| 2026-07-27 | Restore only private allowlisted `/preview` through a separate listener | Immediate Telegram previews require inbound updates; isolating one standard-library long poll preserves the one-shot publication path and avoids webhooks or a bot framework. | `adr/0010-private-preview-listener.md` |
| 2026-07-27 | Permit Gemini only as a fail-closed Policía Local translation fallback | Unknown official traffic formats need automated Russian compression; exact evidence, date, street, activity, schema, and length validation prevents the model from deciding publication alone. | `adr/0011-gemini-traffic-fallback.md` |
| 2026-07-27 | Keep a bounded monthly municipal-agenda snapshot | The official poster contains events missing from HTML; change-triggered Gemini Vision extraction plus a local structured snapshot preserves coverage during source outages without daily OCR or stored translations. | `adr/0012-monthly-municipal-agenda-snapshot.md` |
| 2026-07-27 | Prefer active Platja Centre wind for the current value | SafeBeach provides beach-local speed and direction; render both current wind and the inline AEMET forecast in m/s without another request or source. | `adr/0003-compact-wind-forecast.md` |
| 2026-07-27 | Add the official Wednesday market as a recurring event | Ayuntamiento and Turismo Guardamar explicitly identify the weekly Wednesday market at parking La Redonda; a local calendar rule is simpler and more reliable than fetching it every morning. | `docs/kb/06_Data_Sources.md` |
| 2026-07-27 | Use `@AlcaldeGuardamar` only for market exceptions | A bounded Wednesday-only public-page check can suppress an explicitly cancelled or moved market without turning the channel into a general news source. | `adr/0013-mayor-channel-market-exceptions.md` |
| 2026-07-27 | Make the compact weather icon dynamic from AEMET | A fixed icon can contradict the official daily sky forecast; a small deterministic mapping adds useful context without more text, AI, or sources. | `adr/0013-dynamic-weather-icon.md` |
| 2026-07-27 | Apply market holiday moves from a reviewed annual calendar | The ordinance moves a holiday Wednesday market to Tuesday; a tiny official calendar is deterministic, while unsupported years omit the market instead of guessing. | `adr/0014-reviewed-holiday-calendar.md` |
| 2026-07-27 | Add Campo de Guardamar as a recurring Sunday event | The accepted operator schedule provides `07:00–16:00` and Camino del Raso, 15; no cancellation or holiday behavior is inferred. | `docs/kb/06_Data_Sources.md` |
| 2026-07-27 | Deploy only CI-tested commits through a daily Termux pull | A promoted `deploy` branch avoids exposing the phone or running a heavy self-hosted runner; the phone keeps secrets and state local and validates each update before use. | `adr/0015-tested-termux-deployment.md` |
| 2026-07-28 | ~~Publish at 10:02 to prefer an active beach flag~~ | Superseded by the two-stage 07:30 plus conditional replacement flow. | `adr/0021-two-stage-daily-replacement.md` |
| 2026-07-28 | Preserve event time, type, and place in the digest | Events remain useful without a published time, but any official time range, activity type or medium, and location must survive extraction and appear compactly without inference. | `adr/0017-event-display-facts.md` |
| 2026-07-28 | Name three nearby beaches and keep their flags separate | A single unnamed Centre flag can be mistaken for a city-wide status; explicit Centre, Roqueta, and Vivers indicators stay compact and avoid unsafe averaging. | `adr/0018-nearby-beach-flags.md` |
| 2026-07-28 | Correct verified July poster facts without repeat OCR | The official text agenda identifies `Entropía`, Conchi Montes, `08:00–14:00`, and Biblioteca Pública Municipal; an exact poster-specific correction repairs the stored OCR record safely. | `adr/0012-monthly-municipal-agenda-snapshot.md` |
| 2026-07-28 | Use one AEMET temperature and compact sea-state forecast | Centro / La Roqueta supplies one official representative temperature and two wave periods; equal states retain `волны`, while changes render compactly as `слабые → умеренные`, without averaging nearby beaches. | `adr/0019-aemet-sea-forecast.md` |
| 2026-07-28 | Show only high-probability rain | The existing AEMET municipal forecast adds planning value without another request; show the highest eligible remaining period only at 75% or above. | `adr/0020-high-probability-rain.md` |
| 2026-07-28 | Bound SafeBeach to a conservative summer window | Municipal service dates can vary inside a broader official window; use SafeBeach only from 20 June through 14 September to prevent stale winter flags while retaining its live activity checks. | `adr/0018-nearby-beach-flags.md` |
| 2026-07-29 | Normalize traffic documents into independent mobility measures | Multiple periods, closures, exceptions and routes cannot be represented safely by one document-wide summary; the reviewed festival PDF is checksum-pinned and unknown HTML remains fail-closed. | `adr/0022-structured-mobility-measures.md` |

## Adding a decision

1. Create an ADR for a durable or consequential architecture choice.
2. Add a one-line summary here with its date, context, and ADR link.
3. Update any affected knowledge-base pages.
4. Do not rewrite old decisions; mark superseded decisions and link the
   replacement.
