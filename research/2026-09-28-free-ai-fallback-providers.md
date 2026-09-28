# Free AI fallback provider evaluation

## Question

Which free secondary LLM can safely improve resilience when Gemini is
temporarily unavailable without making the Termux bot heavier or weakening its
event-evidence rules?

## Scope and sources checked

Access date: 2026-09-28.

Provider documentation reviewed during the investigation:

- Google Gemini API error behavior for the configured
  `gemini-3.5-flash-lite` endpoint.
- Groq model, Structured Outputs, API and Free Plan rate-limit documentation.
- OpenRouter model/pricing/free-model documentation.
- Current repository implementation in `src/telegrambot/gemini.py`,
  `src/telegrambot/openrouter.py`, event translation recovery, municipal
  agenda extraction, traffic, market, and AM Guardamar.

Production probes were read-only. They used the production device and current
public Guardamar source data without Telegram delivery or state changes. No API
key was committed or written to project state.

## Findings

### Gemini primary failure mode

A bounded production probe against `gemini-3.5-flash-lite` returned HTTP 503
on four attempts with the provider status `UNAVAILABLE` and a high-demand
message. This was a provider-capacity failure, not an input/schema validation
error.

### Existing OpenRouter fallback

The repository currently pins `openai/gpt-4.1-mini`, which is paid. The
production OpenRouter key reported a free-tier account with zero spendable
limit for paid requests, and the existing fallback request returned HTTP 403
`Key limit exceeded`.

This makes the current fallback unsuitable for the project's permanent
free-only policy.

### Groq Qwen technical compatibility

`qwen/qwen3.8-27b` successfully handled small strict-JSON test cases for
translation, traffic schema, and agenda-text schema. One real Guardamar poster
request also returned structured content.

A later exact production poster extraction failed because the model generated a
large response that reached the 8000-token output budget before producing a
complete schema-valid JSON object. The production workflow requires a second
blind reading as well. Making this reliable would require poster splitting or
multiple extra calls, so Qwen vision was rejected as a runtime fallback.

### Groq GPT-OSS 120B bounded text

The exact production entry points were probed with
`openai/gpt-oss-120b`, strict JSON Schema, temperature zero, and
`reasoning_effort="low"`.

The model passed the bounded contracts for:

- event-title translation;
- event-teaser translation;
- traffic editorial composition;
- positive exact-date market cancellation;
- negative market case where the cancellation belonged to another date.

The traffic probe preserved `Avenida del Mediterráneo` exactly.

One title translation retained uppercase Russian words despite the prompt's
sentence-case preference. This is a fallback-quality degradation, not a factual
failure, and does not justify extra capitalization logic.

### GPT-OSS factual extraction

The model was not accepted for factual event extraction.

On the real current Turismo agenda, a strict structured response returned 18
candidates. Some passed every deterministic validator, but multiple candidates
failed because the generated `title_es` contained words not present in the
single exact `evidence_es` quotation. Examples included a theatre title and
the generic word `Cine` added outside the evidence span. This proves that the
model can be partly correct while still producing an incomplete/unsafe catalog.

On the standalone Todo Cultura regression case, all quoted facts, date and time
were supported, but the model classified the World Cleanup Day activity as
`municipal_service`. The production normalizer correctly rejected the
one-day service row.

These failures are semantic/provenance failures, not API/schema failures.
Changing providers through OpenRouter would not solve them, and weakening the
validators would reduce safety.

### Runtime load and quota perspective

The successful GPT-OSS bounded-text requests were small. Translation, teaser,
traffic and market calls are also naturally limited by the existing translation
cache and by event/traffic/market triggers.

The project therefore does not need a quota database, circuit breaker,
provider-health file, retry daemon, or internal scheduler. A Groq 429 or outage
can safely degrade to the existing deterministic/cache behavior and recover on
a later normal one-shot.

## Recommendation

Adopt the architecture recorded in ADR 0085:

- Gemini remains primary.
- Direct Groq `openai/gpt-oss-120b` is the only active secondary model.
- Groq fallback is opt-in for exactly four bounded operations:
  `translate_event_titles`, `translate_event_teasers`,
  `compose_traffic_notice`, and `extract_market_status`.
- All factual event extraction and image work remains Gemini-only.
- Replace the active paid OpenRouter runtime fallback rather than chaining a
  third provider.
- Emit stable `PROVIDERS-UNAVAILABLE` after an eligible Gemini failure when
  Groq cannot produce a usable response, and stop individual translation
  recovery in that state.
- Do not add retries, a circuit breaker, quota state, provider registry,
  dynamic model selection, local models, or image-splitting workflows.

Confidence: high for the current production scope because the chosen and
rejected paths were exercised against the actual production functions and real
Guardamar source material.

## Open questions

- Free-plan limits and provider model availability can change. Re-check official
  Groq documentation before a future model replacement.
- If production logs later show frequent simultaneous Gemini/Groq outages, the
  need for a third provider or a short process-local cooldown can be
  reconsidered from observed data rather than added preemptively.
