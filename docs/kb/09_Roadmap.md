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
  and a small atomic daily message-replacement state are implemented.
- Implement Morning Digest collection and formatting. The AEMET weather and
  warning slice, Platja Centre SafeBeach status, and AEMET beach-temperature
  fallback are implemented. The optional Agenda Guardamar same-day event slice
  and structured Policía Local mobility measures are implemented. Event
  completeness now includes Russian Agenda titles, same-page venue recovery,
  all verified same-day items, a seven-day poster transition, and narrowly
  parsed Fiestas de Barrio from the Mayor channel.
- Implement the approved canonical phone layout and inline wind comparison
  without changing source collection or message size. Complete.
- Add two-stage Telegram delivery. Termux invokes the full briefing at 07:30
  and bounded SafeBeach checks at 10:10–10:40; every process exits and the
  group retains one current message.
- Add one isolated private `/preview` listener for allowlisted operators,
  without publication state changes or source polling between commands.
- Add a fail-closed Gemini fallback for previously unknown official Policía
  Local traffic text, with strict evidence, date, street, and length checks.
- Done: refined ADR 0012 with ADR 0028: official HTML text is primary,
  changed MUPI needs two agreeing reads, and two staggered pre-morning event
  catalogs remove routine event-site work from the 07:30 run.
- Add focused tests and recovery guidance.
- Review and add the next official Guardamar holiday calendar before each
  supported year begins; an unsupported year deliberately omits the market.
- Review the Campo de Guardamar operator schedule periodically and replace its
  local Sunday rule if an authoritative cancellation feed becomes available.
- Done: validated Python 3.12 operation, resource use, `termux-services`,
  Termux:Boot recovery and private preview on the target Android device.

## Next steps

- Observe the new evening next-day PVPC table on narrow phones and tune only
  verified display problems; do not add tariff comparison or billing advice.
- Improve source failure and stale-data handling.
- Review changed Policía Local PDFs before accepting a new checksum; unknown
  HTML notices remain eligible for the fail-closed structured fallback. Do not
  treat the source as a live traffic feed.
- Tune relevance and message length from real usage.
- Add basic operational visibility without heavy services.
- Review sources and assumptions periodically.

## Later improvements

- Add sources only where they increase daily value.
- Improve localization or personalization only if demand is clear.
- Optimize measured bottlenecks rather than anticipated ones.

## Approved second feature

The evening next-day PVPC table fills the former feature slot. Keep it isolated
from the Morning Digest and do not create another feature slot speculatively.
