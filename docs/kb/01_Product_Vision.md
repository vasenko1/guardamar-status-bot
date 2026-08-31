# Product Vision

## Problem

Daily city information is scattered across weather services, marine reports,
beach notices, warning channels, municipal publications, and event calendars.
Checking each source takes time, while broad feeds create noise.

## Vision

Provide a quiet, trustworthy morning briefing that answers:

- What are the important conditions today?
- Is there a warning, restriction, or disruption I should know about?
- Is there a relevant event today?

The answer should fit in one short Telegram message.

## User promise

The bot will:

- use only official, authoritative sources;
- include only current and relevant information;
- separate verified facts from unavailable data;
- omit weak or low-value items;
- keep each line useful;
- avoid pretending that missing information is normal or safe.

The bot is a convenience layer over official information, not an emergency
service. Users should follow the responsible authority for urgent instructions.

Rare standalone notices are acceptable when an official source reports a
material event in Guardamar's immediate area. They must be geographically
narrow, deduplicated, compact, and quiet when nothing qualifies.

## Product experience

A good digest is calm and predictable:

- one current group message: an early 07:30 briefing, replaced later only
  when verified beach or Mayor-channel information adds value;
- important items appear before routine conditions;
- wording is factual and compact;
- missing optional sections do not create clutter;
- source failure does not produce fabricated replacements;
- no message is preferable to a misleading or empty message.

## MVP direction

The MVP proves that a small deterministic system can collect, filter, and
format useful official information reliably on the target device.

Weather, warnings, beach status, formatting, and delivery do not depend on AI.
Gemini and its single bounded non-Google fallback are restricted to municipal
tasks: fail-closed traffic translation, exact-date market cancellation
extraction, changed-poster OCR, and title-only translation of already
structured official events.
Deterministic validation or a valid snapshot must protect every result;
otherwise only that optional contribution is omitted.

## Long-term direction

Keep the product deliberately narrow:

1. Make the Morning Digest dependable.
2. Improve source quality and relevance using observed needs.
3. Validate the approved evening next-day PVPC table without expanding it into
   general energy advice or tariff comparison.

More messages, more sources, and more infrastructure are not signs of success
unless they make the daily experience materially better.
