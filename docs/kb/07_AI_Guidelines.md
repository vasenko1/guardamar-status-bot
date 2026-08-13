# AI Guidelines

These rules apply to AI-assisted development and to any future AI-supported
content processing.

## AI may

- Compress faithful source material into shorter wording.
- Normalize equivalent labels and formats.
- Rank verified items by urgency, relevance, and usefulness.
- Omit duplicates, stale entries, and low-value details.
- Propose code, tests, documentation, and architecture changes within the
  approved scope.
- Identify uncertainty and request or preserve missing information.

## AI must never

- Invent facts, warnings, events, source values, or citations.
- Present inference as an official statement.
- Hide source disagreement or meaningful uncertainty.
- Turn stale data into a current claim.
- Add unapproved product scope or expand the electricity feature beyond its
  deterministic official-source contract.
- Introduce heavy dependencies or architecture that violates device limits.
- Expose secrets, personal data, or private configuration.

## Content rule

Compression and prioritization are allowed. Invention is not.

If reliable input is absent, omit the claim or state that the information is
unavailable. A shorter truthful digest is better than a complete-looking one.

## Approved runtime use

ADR 0011 permits the Policía Local traffic fallback to call Gemini at runtime.
Gemini receives bounded public text from the freshly fetched official page and
may return up to four independent mobility measures in the accepted JSON
schema. Every measure needs an exact source quotation, supported action,
active dates and unchanged street names; each Russian line is capped at 180
characters and the digest displays at most two. The application omits the
entire traffic section on any validation failure.

The reviewed Wednesday-market rule also permits one bounded Gemini call only
when fresh Mayor-channel posts explicitly mention the market. Deterministic
validation requires an exact quotation, cancellation wording, and the target
local date; otherwise the recurring market is omitted rather than guessed.

Do not send secrets, personal data, unrelated private content, or another
model's output. Do not use Gemini for AEMET, SafeBeach, delivery, scheduling,
or the fixed known traffic rule. Agenda Guardamar title translation is the
narrow exception described below; dates, times, places, selection, and
relevance remain deterministic.

ADRs 0012 and 0028 additionally permit Gemini structured extraction when the
official monthly municipal text changes and Gemini Vision only for a new MUPI
URL. MUPI facts require two blind structured readings: the second call must
not receive the first call's candidates. Deterministic agreement on key fields
is required, and official HTML text always wins conflicts. Every
result must use a fixed schema and pass date, month, field-length, provenance,
and duplicate validation before replacing the previous catalog.
For text agendas, each candidate additionally needs an exact contiguous source
quotation. Every meaningful word in a self-contained title and every returned
date, time and place must occur in that quotation. The model may compress explicit event
kind, act, tribute, benefit purpose, audience or cause into the title, but may
not create a free-form description. Poster candidates use null evidence and
remain governed by independent-reading agreement.
Validated title-only Russian translations are stored separately in a bounded
atomic cache keyed by exact source identity, source title, and policy version.
Only preparation commands may fill missing entries; the 07:30 publication and
private preview are read-only and use a normalized Spanish title when a
translation is absent. Invalid OCR keeps the prior valid
snapshot and cannot erase it. Without a prior snapshot, OCR failure remains an
optional municipal-agenda failure and cannot stop the rest of the digest.

The same bounded title-only translation contract applies to today's structured
Agenda Guardamar events. Gemini receives only the official titles and returns
the same number in the same order. It may not add dates, places, explanations,
or event facts. If a municipal batch has an invalid response shape, the bot
may recover at most twelve selected titles through individual schema-checked
calls; an individually invalid title alone is omitted. This recovery never
repeats OCR or source collection. A provider outage preserves already cached
translations and never removes the verified source event.

Gemini remains the primary model for every approved task. ADR 0030 permits one
secondary request through OpenRouter with pinned non-Google model
`openai/gpt-4.1-mini` after a Gemini failure. It receives only the same bounded
public input and the same strict JSON schema; every existing deterministic
validator remains authoritative. There is no third model and no provider
retry inside this layer.

Both clients send their keys only in API headers, accept bounded JSON only
from their exact HTTPS API hosts, and expose stable status codes instead of
provider response text. A missing secondary key preserves Gemini-only
behavior. A double failure omits the affected optional result or preserves an
already valid snapshot and reports both stages to the private diagnostics.
