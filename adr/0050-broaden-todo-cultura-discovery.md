# ADR 0050: Broaden Todo Cultura discovery for high-value local activities

Date: 2026-08-31

## Decision

Keep Todo Cultura's public WordPress REST API as an automated discovery source
for Guardamar events, and download up to six bounded detail candidates per
refresh. Candidate ranking gives explicit museum, child, youth, educational,
workshop and guided-visit signals priority. The existing cap of three extracted
programme sections and strict source/date/place/admission validation remains.

## Reason

The source publishes separate pages for important activities that may appear
late in the rolling programme, including children's museum events. A three-page
selection could leave such pages unprocessed until after their date.

## Consequences

Discovery coverage improves without increasing the number of LLM extraction
sections or allowing unverified facts into the digest. The bounded HTTP work is
larger but remains suitable for the phone and retains incremental cursor state.
