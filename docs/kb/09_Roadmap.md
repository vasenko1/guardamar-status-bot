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
  supported year begins; an unsupported year deliberately omits both the
  holiday block and the holiday-dependent Wednesday market.
- Done: show an official holiday block immediately before today's events,
  using the same reviewed calendar without runtime requests or inferred
  transfers.
- Review the Campo de Guardamar operator schedule periodically and replace its
  local Sunday rule if an authoritative cancellation feed becomes available.
- Done: validated Python 3.12 operation, resource use, `termux-services`,
  Termux:Boot recovery and private preview on the target Android device.

## Next steps

- Observe the new evening next-day PVPC table on narrow phones and tune only
  verified display problems; do not add tariff comparison or billing advice.
- Done: persist one complete normalized ESIOS target day before public delivery
  and check confirmed publication before source access, eliminating redundant
  personal-token requests across scheduled attempts and previews.
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
- Parked idea: after the 10:10 beach update, optionally send one current beach
  camera still as a separate reply to the digest. Consider it only when the
  owner permits republication and exposes a stable direct JPEG/snapshot URL;
  do not add video capture or `ffmpeg` to the weak Android runtime. The photo
  must include beach, capture time and source in its short caption, must not be
  used to infer a flag automatically, and must be skipped silently when the
  camera is unavailable. It must never delay or fail the text digest.

## Approved second feature

The evening next-day PVPC table fills the former feature slot. Keep it isolated
from the Morning Digest and do not create another feature slot speculatively.

## Growth cycle — 2026-08 product review

`research/2026-08-12-product-review-and-growth.md` reviewed the delivered
functionality, the deterministic event phrase engine, and candidate content
sources. Each accepted item requires its own accepted ADR before
implementation and must keep Gemini inside its free tier:

- Friday-evening weekend events digest built only from the two existing local
  event catalogs (ADR 0035).
- UV-index row from already approved AEMET data plus a computed
  sunrise/sunset row with no new source (ADR 0036).
- One operator-triggered Telegram poll capability plus manual channel
  engagement steps: reactions, attached discussion group, pinned onboarding
  message (ADR 0037).
- On-call pharmacy row from the Colegio Oficial de Farmacéuticos de Alicante,
  only if its research note proves a bounded server-rendered page
  (ADR 0038).

Deferred from the same review: moving reviewed event corrections and
translations into a validated data file so monthly poster review becomes a
data-only change, and seasonal bathing-water quality before summer 2027.
Rejected: tides, DGT incident feeds, and any non-Guardamar content.
