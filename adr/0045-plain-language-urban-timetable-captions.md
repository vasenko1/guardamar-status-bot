# ADR 0045: Plain-language urban timetable captions

## Status

Accepted and implemented

## Context

The two municipal timetable messages already attach readable full-page images.
Their captions repeated a PDF link and compressed route names, calendar rules,
and source symbols into wording that required the reader to interpret the
official diagram before understanding whether the bus served their area.

## Decision

- Keep the timetable image as the complete schedule and remove the redundant
  full-quality PDF link from the public caption.
- For a reviewed official PDF, describe the useful served areas in plain
  Russian while preserving official place names needed to recognize stops.
- State the active calendar regime as a sentence, not as the vague label
  `Сейчас`.
- Explain stars and the market-stop exception as practical passenger outcomes.
- Keep unknown future PDF revisions fail-closed: show their official route line
  and tell readers that current days and times are on the image, without
  carrying forward reviewed seasonal claims or exceptions.
- Preserve the return link and standard public footer.

This decision supersedes ADR 0042 only where it required a direct PDF link in
the caption. Source discovery, validation, conditional downloading, rendering,
message recovery, and update frequency remain unchanged.

## Consequences

The caption answers where the line goes, when the displayed regime applies,
and what exceptional trips mean without duplicating the attached schedule.
Removing the public PDF link shortens the phone layout but does not weaken
source validation: the bot still downloads and verifies the same official PDF.

