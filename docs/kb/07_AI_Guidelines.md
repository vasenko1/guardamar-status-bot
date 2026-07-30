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
- Add unapproved product scope or the undefined future feature.
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
model's output. Do not use Gemini for AEMET, SafeBeach, Agenda, delivery,
scheduling, or the fixed known traffic rule.

ADR 0012 additionally permits Gemini Vision only when a new or changed
official monthly municipal-agenda poster must be converted into structured
event facts. The result must use a fixed schema and pass date, month, field
length, and duplicate validation before replacing the previous snapshot.
Russian translations must not be stored. Invalid OCR keeps the prior valid
snapshot and cannot erase it. Without a prior snapshot, OCR failure remains an
optional municipal-agenda failure and cannot stop the rest of the digest.

The Gemini client sends the key only in the API header, accepts bounded JSON
only from the exact official HTTPS API host, and exposes stable status codes
instead of provider response text. It performs no internal retry; a failed AI
call omits the affected optional result or preserves an already valid snapshot.
