# Decision Log

This is the concise index of important product and architecture decisions.
Detailed decisions belong in `adr/`.

| Date | Decision | Context and reason | Record |
| --- | --- | --- | --- |
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
| 2026-07-27 | Use AEMET Centro / La Roqueta water temperature only as a SafeBeach fallback | The official forecast keeps the sea row useful outside lifeguard hours, while the flag remains exclusively an active Platja Centre SafeBeach value. | `adr/0006-aemet-beach-temperature-fallback.md` |
| 2026-07-27 | Add at most two same-day events from Agenda Guardamar | Its official event pages expose deterministic title and start-time fields; optional failure stays silent and no media or AI processing is needed. | `adr/0007-agenda-guardamar-events.md` |
| 2026-07-27 | ~~Defer Policía Local traffic integration~~ | Superseded for one explicit official festival restriction; the site still is not treated as a general traffic feed. | `adr/0009-explicit-police-traffic-notice.md` |
| 2026-07-27 | Run one external-triggered Morning Digest process at 07:30 | Direct one-time collection, success-only state, and immediate exit remove resident scheduling, inbound polling, collectors, and cache concerns. | `adr/0008-one-shot-morning-execution.md` |
| 2026-07-27 | Add one explicit Policía Local festival traffic notice | The official HTML page states concrete access, closure, reason, and 15–29 July validity; strict matching can add value without polling, PDF parsing, or inference. | `adr/0009-explicit-police-traffic-notice.md` |
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

## Adding a decision

1. Create an ADR for a durable or consequential architecture choice.
2. Add a one-line summary here with its date, context, and ADR link.
3. Update any affected knowledge-base pages.
4. Do not rewrite old decisions; mark superseded decisions and link the
   replacement.
