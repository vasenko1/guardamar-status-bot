# Project Principles

These principles are decision rules, not aspirations. Product, architecture,
and code changes must follow them.

## 1. Keep the message short

The Morning Digest must be readable in seconds. Prefer a few high-value lines
over a complete report. Link to an official source when details matter more
than message length.

## 2. Use official sources only

Use the public authority or official organization responsible for the
information. Do not use social reposts, general news sites, community reports,
or commercial aggregators as factual inputs.

If no suitable official source exists, leave the information out of the MVP.

## 3. Silence is better than noise

Do not publish an item merely because data exists. Omit information that is:

- stale;
- unverified;
- duplicated;
- outside the relevant area or date;
- too vague to help;
- routine and without practical value.

If the digest has no trustworthy, useful content, do not send filler.

## 4. Every line must be useful

Each line should help the user:

- notice a risk or disruption;
- prepare for conditions;
- make a decision about the day; or
- discover a genuinely relevant event.

Remove decorative text, generic advice, and repeated context.

## 5. Facts must remain facts

Never invent, infer, or smooth over missing information. Do not treat absence
of a warning as proof of safety. Preserve meaningful qualifiers from the
source, including time, location, and uncertainty.

## 6. Safety and impact come first

Keep the canonical three-line conditions block stable, then order optional
sections by practical importance:

1. official warnings and urgent restrictions;
2. material disruptions or closures;
3. an official holiday applicable in Guardamar today;
4. relevant events;
5. routine context, only when useful.

The bot must not claim to replace official emergency communication.

## 7. AI is optional and fail-closed

The core digest policy remains deterministic. Gemini, with one bounded
OpenRouter fallback, is limited to the accepted Policía Local traffic
fallback, the exact-date Mayor-channel market exception, municipal-poster
OCR/title translation, and title-only translation of already structured
Agenda Guardamar events. Structured results, source evidence where applicable,
deterministic validation, and snapshot rules decide publication. Do not add
local models, embeddings, general generation, or AI dependencies to weather,
warnings, beach status, formatting, or delivery.

## 8. Design for partial failure

One broken or unreachable source must not invalidate good data from other
sources. Omit the affected section, avoid misleading defaults, and keep
recovery automatic and bounded.

## 9. The device constraint is a product constraint

Prefer the simplest solution that works reliably in Termux. New dependencies,
background work, polling, storage, and concurrency must justify their cost on a
weak Android device.

## Inclusion checklist

Before adding any digest item, confirm:

1. Is the source official?
2. Is the information current for the relevant place and time?
3. Can the claim be represented faithfully?
4. Will it help the user today?
5. Is it worth the space and network cost?

If any required answer is no or unknown, omit the item.
