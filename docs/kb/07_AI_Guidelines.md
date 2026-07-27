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

Only ADR 0011's Policía Local traffic fallback may call Gemini at runtime.
Gemini receives bounded public text from the freshly fetched official page and
must return the accepted JSON schema. Its evidence must be an exact source
quotation; dates and unchanged street names must pass application validation;
the restriction must be active today; and the Russian line is capped at 180
characters. The application omits the entire traffic section on any failure.

Do not send secrets, personal data, unrelated private content, or another
model's output. Do not use Gemini for AEMET, SafeBeach, Agenda, delivery,
scheduling, or the fixed known traffic rule.

ADR 0012 additionally permits Gemini Vision only when a new or changed
official monthly municipal-agenda poster must be converted into structured
event facts. The result must use a fixed schema and pass date, month, field
length, and duplicate validation before replacing the previous snapshot.
Russian translations must not be stored. Invalid OCR keeps the prior valid
snapshot and cannot erase it.
