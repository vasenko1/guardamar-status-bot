# Todo Cultura incremental API check — 2026-08-07

This note records time-sensitive behavior of the public WordPress REST API at
`/wp-json/wp/v2/mec-events`; it is not a permanent source guarantee.

## Observations

- A bounded metadata query for `Guardamar` supports `modified_gmt`, ascending
  order and `modified_after`; 100 records fit under the accepted 150 KiB limit.
- Up to three chosen posts can be fetched by one `include=` request under the
  existing 300 KiB response limit.
- Exact per-day search is incomplete. Date headings may be inline with their
  first event, so the parser must split both standalone and inline headings.
- Several posts can reproduce overlapping Ayuntamiento programme dates.

## Implementation experiment

Using 7 August 2026 as the local date:

- initial bounded run covered 7, 8, 10, 11, 12 and 13 August;
- an immediate run with persisted state returned no new sections and made no
  duplicate date work;
- advancing the local date to 8 August added only 14 August;
- the persisted covered-date list then contained only unexpired dates.

The experiment supports ADR 0033's rolling cursor design. It does not make Todo
Cultura authoritative: official municipal HTML and Agenda Guardamar still win,
and a source or model failure preserves the prior catalog and cursor.
