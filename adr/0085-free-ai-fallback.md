# ADR 0085: Free-only capability-scoped LLM fallback

## Status

Accepted on 2026-09-28. Implemented on 2026-09-28.

Supersedes ADR 0030. The capability list is extended by ADR 0087 with two
additional bounded resident-news text operations; the provider and failure
policy in this ADR remains unchanged.

## Context

The bot already uses Gemini for a small set of structured municipal and event
tasks. Production testing on 2026-09-28 showed that
`gemini-3.5-flash-lite` can return transient HTTP 503
`UNAVAILABLE` / high-demand responses. The existing secondary path in
`gemini.py` is OpenRouter with pinned `openai/gpt-4.1-mini`, which is a
paid model and therefore conflicts with the project's permanent free-only AI
policy.

The target runtime is a weak Android device under Termux. A solution must keep
network work, dependencies, state, retries, and provider-specific machinery
small. Existing deterministic validation, translation caches, snapshots, and
source-specific fail-closed behavior already preserve useful operation when AI
is unavailable.

Provider probes on the production device established a meaningful capability
boundary:

- Groq `openai/gpt-oss-120b` successfully handled the exact production
  contracts for event-title translation, teaser translation, traffic
  editorial composition, and exact-date market-status classification using
  strict structured outputs.
- The same model was not reliable enough for factual event extraction. On the
  real Turismo agenda it returned a mixture of valid and invalid candidates,
  including titles containing words not supported by the exact
  `evidence_es` quotation. On the standalone Todo Cultura regression case it
  extracted the facts but classified the event as `municipal_service`, which
  the deterministic normalizer correctly rejected.
- Groq Qwen vision could read the real monthly poster but a full production
  extraction exceeded the practical free-plan output/token budget before
  producing complete valid JSON. Reworking the poster into multiple crops or
  multi-call routing would add disproportionate complexity.

The existing source architecture makes a broad AI fallback unnecessary:
translation has a bounded persistent cache and Spanish fallback, traffic has a
deterministic `fallback_body()`, market cancellation is fail-closed, and
event extraction preserves prior verified snapshots or source state.

## Decision

### Providers

- Keep Gemini as the primary model for every approved AI task.
- Add exactly one active secondary provider: direct Groq using
  `openai/gpt-oss-120b`.
- Keep the production Groq project on the Free Plan. Do not add paid service
  tiers, automatic plan upgrades, or code that assumes paid capacity.
- Remove OpenRouter from the active runtime path. The existing
  `openai/gpt-4.1-mini` fallback is not compatible with the free-only policy.
- Do not add a third provider, dynamic free-model discovery, a provider
  registry, or automatic model routing.

### Capability boundary

Groq fallback is allowed only for these four public operations:

1. `translate_event_titles`
2. `translate_event_teasers`
3. `compose_traffic_notice`
4. `extract_market_status`

Every factual event-extraction operation remains Gemini-only, including:

- municipal/Turismo text extraction;
- Todo Cultura general extraction;
- Todo Cultura standalone extraction;
- Facebook/Cultura event extraction;
- AM Guardamar extraction;
- MUPI image extraction and blind verification;
- Ayuntamiento/fiesta poster extraction and blind verification;
- any future extraction operation unless a separate decision explicitly
  approves Groq for it.

The implementation should make Groq fallback opt-in, with the default remaining
Gemini-only. A small internal flag on the shared request helper is sufficient;
do not introduce a generic provider abstraction.

The Groq transport itself must also fail closed:

- text parts only;
- strict JSON Schema structured outputs;
- `reasoning_effort="low"`;
- no SDK dependency;
- one bounded request through the existing standard-library transport;
- a small output ceiling suitable for the approved bounded contracts, so a
  future accidental extraction call cannot send an 8000-token request.

### Fallback eligibility

Groq may be attempted only when an approved bounded operation has a genuine
primary-provider/protocol failure. Eligible cases include:

- network failure;
- timeout;
- provider redirect/content-type/response-shape failure;
- HTTP 408;
- HTTP 429;
- HTTP 401/403 with an operator-visible warning;
- HTTP 404/model-unavailable with an operator-visible warning;
- HTTP 5xx;
- invalid or empty provider JSON response.

Do not use Groq to mask local/request/input failures such as:

- missing or locally invalid Gemini configuration;
- `SOURCE-SIZE`;
- unsupported input/MIME;
- local URL-policy failures;
- HTTP 400, 413, 415, or 422;
- application-level semantic validation failure after a structurally valid
  model response.

A valid Gemini result is never sent to Groq for comparison or voting. The
secondary model is a transport/provider fallback, not a second opinion.

### Double-provider failure

When an approved operation reaches an eligible Gemini failure and Groq is
missing, unavailable, rate-limited, misconfigured, or otherwise fails, expose
one stable `PROVIDERS-UNAVAILABLE` diagnostic.

This code means that no permitted provider can currently produce a usable
response for this request. It is intentionally broader than "both services are
down".

Existing bounded individual translation recovery remains available for an
ordinary batch/application failure. It must stop immediately on
`PROVIDERS-UNAVAILABLE`, so a provider outage cannot expand into twelve
additional Gemini/Groq attempts.

Do not add provider retries, sleeps, `Retry-After` handling, a persistent
retry queue, a circuit breaker, provider-health state, or a quota manager.
Existing later cron invocations and source snapshots are the recovery path.

### Existing deterministic behavior remains authoritative

- Event/title/teaser results still pass existing length/order/cache rules.
- Traffic facts remain TomTom-derived; if AI composition fails, use the
  existing deterministic `fallback_body()`.
- Market cancellation still requires the existing exact-source evidence and
  target-date validator; if status analysis is unavailable, keep the existing
  fail-closed market behavior.
- Factual event extraction never falls back to GPT-OSS. Gemini failure must
  preserve prior verified facts or existing source-state behavior rather than
  accept a partial or weaker extraction.
- Evidence, date, place, source, and poster-agreement validators must not be
  weakened for any provider.

### Documentation and configuration migration

When the implementation is made:

- replace `OPENROUTER_API_KEY` with optional `GROQ_API_KEY` in the example
  configuration and runtime documentation;
- remove the active OpenRouter import/path and its paid model;
- remove dead OpenRouter tests/client code if no runtime caller remains;
- keep old ADRs as history and mark ADR 0030 superseded;
- make provider-neutral application-validation messages where they can now
  describe a result returned by either Gemini or Groq.

Do not automatically edit the operator's production `.env`; an old
`OPENROUTER_API_KEY` may remain harmlessly until removed manually.

## Consequences

The bot gains one independent free fallback for the four small text operations
where the tested model behaved acceptably, while all fact extraction remains
under the existing stricter Gemini-plus-validator/snapshot design.

The solution adds one small standard-library HTTP client but no dependency,
daemon, scheduler, queue, database, persistent AI state, provider registry, or
additional cron job.

A simultaneous Gemini/Groq outage degrades safely instead of causing retry
storms. Existing caches, snapshots, deterministic wording, and later scheduled
one-shots provide recovery.

OpenRouter remains a researched future option but is intentionally not an
active third layer because its free limits and same-model redundancy do not
justify the extra runtime path.

## Rejected alternatives

### Gemini -> Groq -> OpenRouter

Rejected as unnecessary provider-chain complexity. It adds another key,
transport, error taxonomy, quota surface, test matrix, and lifecycle while
largely reusing the same GPT-OSS model.

### Groq for all text input

Rejected because text input is not equivalent to low-risk text generation.
Turismo, Todo Cultura, Facebook/Cultura, and AM Guardamar text paths extract
new factual event records and require stronger provenance behavior than
GPT-OSS demonstrated.

### Groq/Qwen image fallback

Rejected after a real production-poster probe exceeded the practical free
output/token budget. Cropping or multi-call poster pipelines would be
overengineering for a path already protected by a verified snapshot.

### Looser evidence validators

Rejected. The validators correctly caught unsupported title words and wrong
semantic classification during GPT-OSS probes. Reliability takes precedence
over apparent extraction completeness.

### Circuit breaker, retries, quota state, or AI queue

Rejected until production evidence shows they are necessary. The present
one-shot cron architecture, caches, and last-good snapshots already provide
bounded recovery.
