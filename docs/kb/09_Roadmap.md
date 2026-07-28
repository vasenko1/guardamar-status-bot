# Roadmap

## Foundation — complete

- Establish repository structure.
- Create the AI-friendly knowledge base.
- Record runtime and product constraints.
- Prepare research and ADR workflows.

## MVP

- Select and validate authoritative data sources. AEMET weather and warnings
  plus SafeBeach beach status are approved; other categories remain open.
- Define the compact normalized records. Weather, warning, and beach-status
  records are implemented.
- Establish lightweight configuration and state. Environment configuration
  and an atomic `last_successful_date` state are implemented.
- Implement Morning Digest collection and formatting. The AEMET weather and
  warning slice, Platja Centre SafeBeach status, and AEMET beach-temperature
  fallback are implemented. The optional Agenda Guardamar same-day event slice
  and strict Policía Local festival traffic notice are implemented.
- Implement the approved canonical phone layout and inline wind comparison
  without changing source collection or message size. Complete.
- Add one-shot Telegram delivery. An external Termux scheduler invokes the
  short-lived process at 10:00; the application has no resident scheduler.
- Add one isolated private `/preview` listener for allowlisted operators,
  without publication state changes or source polling between commands.
- Add a fail-closed Gemini fallback for previously unknown official Policía
  Local traffic text, with strict evidence, date, street, and length checks.
- Done: implemented ADR 0012 with change-triggered Gemini Vision extraction
  of the monthly Ayuntamiento poster and one bounded local event snapshot.
- Add focused tests and recovery guidance.
- Review and add the next official Guardamar holiday calendar before each
  supported year begins; an unsupported year deliberately omits the market.
- Review the Campo de Guardamar operator schedule periodically and replace its
  local Sunday rule if an authoritative cancellation feed becomes available.
- Done: validated Python 3.12 operation, resource use, `termux-services`,
  Termux:Boot recovery, private preview, and the 10:00 `cronie` schedule on the
  target Android device.

## Next steps

- Improve source failure and stale-data handling.
- Expand traffic notices only when Policía Local or the municipality exposes
  another explicit, safely parseable official notice. Do not treat the current
  festival page as a general traffic feed.
- Tune relevance and message length from real usage.
- Add basic operational visibility without heavy services.
- Review sources and assumptions periodically.

## Later improvements

- Add sources only where they increase daily value.
- Improve localization or personalization only if demand is clear.
- Optimize measured bottlenecks rather than anticipated ones.

## Future feature placeholder

Keep one feature slot open. Define its user need, inputs, output, boundaries,
runtime cost, and decision record before adding it to the roadmap.
