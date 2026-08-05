# ADR 0030: One secondary structured LLM

## Context

The bounded municipal AI tasks use Gemini for translation, extraction, and a
second poster reading. Provider rate limits and temporary outages can leave a
prepared event catalog incomplete even though the public source input is
valid. The target device cannot justify a local model, a general AI framework,
or a chain of several remote models.

## Decision

- Keep Gemini as the primary provider.
- Configure exactly one secondary provider through `OPENROUTER_API_KEY` and
  pin `openai/gpt-4.1-mini`, a non-Google model that supports image input and
  strict structured JSON.
- Make at most one secondary request after a Gemini protocol, configuration,
  transport, HTTP, or response-shape failure. Do not retry either provider
  inside this layer and do not add a third model.
- Send the same bounded public input and the same JSON schema to the secondary
  model. Its result passes every existing deterministic source, evidence,
  date, length, and catalog validator; provider success alone never permits
  publication.
- Support the already accepted text, image, and PDF inputs. Restrict both
  transports to their exact HTTPS hosts, bounded timeouts, and bounded JSON
  responses. Never log or persist either token or raw provider response.
- If the secondary key is absent, preserve the previous Gemini-only behavior.
  If both providers fail, expose one operator-safe diagnostic containing both
  failure stages and preserve any prior valid snapshot or translation.

## Consequences

One rare extra request improves resilience without adding a package, daemon,
schedule, cache, or new product behavior. OpenRouter is an additional external
dependency and incurs usage charges only after Gemini fails. A shared network
failure can still affect both providers, and deterministic fallbacks remain
necessary.
