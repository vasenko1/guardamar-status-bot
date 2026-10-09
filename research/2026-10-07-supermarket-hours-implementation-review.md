# Supermarket closure implementation review — 2026-10-07

## Scope

Implementation review for ADR 0105, limited to the exact Guardamar Mercadona,
masymas and DIA closure-notification slice.

## Review passes and defects closed

1. **Source-contract pass**
   - kept exact host/path/query allowlists and bounded transport;
   - required same-day Mercadona `fechaCreacion`;
   - kept retailer failures independent;
   - confirmed shortened-open never becomes a closure event.

2. **Lifecycle pass**
   - verified early / tomorrow / today identities are per store + target date;
   - Monday Tuesday closures collapse early+tomorrow into one message;
   - Sunday Monday closures produce tomorrow only;
   - missed early phases are not fabricated;
   - one message per local day remains the hard cap.

3. **Delivery/crash-safety pass**
   - fixed deterministic Telegram failure so both observation baseline and
     reservation roll back to the entire pre-send state;
   - split accounted `sent` keys from definitely delivered `confirmed`
     keys;
   - ambiguous delivery therefore blocks duplicate resend but cannot trigger a
     later false correction;
   - state pruning preserves uncertain keys and enforces
     `confirmed ⊆ sent`.

4. **Long-running-state pass**
   - bounded per-store future closures and delivery histories;
   - removed independent pruning behaviour that could break
     `confirmed ⊆ sent`;
   - retained at most one bounded ambiguous batch.

5. **Termux pass**
   - one 08:15 Europe/Madrid one-shot between SUMA and Sports Today;
   - cron installer owns only its marked block;
   - installer temporary files moved under `$HOME/.cache/crontab`, never
     `/tmp`;
   - runner keeps one bounded rotating log and no daemon.

6. **Resident-copy pass**
   - fixed correction grammar;
   - store ordering is stable and editorial rather than key-alphabetic;
   - same-date stores are grouped;
   - urgent correction groups sort before later-week closures;
   - holiday wording says only that Guardamar has an official day off; it does
     not claim the holiday caused the retailer decision;
   - mixed holiday behaviour explicitly says which reviewed stores remain open.

7. **Seasonal-Sunday pass**
   - found that accepting DIA's current Sunday weekly field as a generic
     baseline could turn one Sunday difference into a false seasonal-change
     claim;
   - v1 now hard-bounds resident closure notifications to the reviewed
     Monday-Saturday baseline;
   - seasonal Sunday transition automation is deferred until a stable
     first-party boundary/range contract is proved.

8. **Branch-integrity pass**
   - detected early/WIP duplicate `supermarket_sources.py`, old
     `supermarket-hours` launchers/tests, and unrelated traffic/electricity
     changes in the working feature branch;
   - final delivery is rebuilt as one commit from exact production base
     `b907b069fe6bba499b31ca129a818ebe2263bacb`;
   - none of those WIP or unrelated files are included in the final tree.

## Test boundary

Focused standard-library regression tests cover the three real 7/9/12 October
source contracts, routine Sunday suppression, strict URL policies, bounded
403/406 fallback, grouped copy, holiday/non-holiday wording, correction rules,
partial source failure, deterministic rollback, ambiguous reservation and
same-day at-most-once delivery.

The repository has no general GitHub CI workflow. Exact full-suite execution and
live read-only endpoint validation therefore remain a production-Termux
pre-deploy gate; no Telegram send is required for that validation.

## Remaining deliberate limitations

- Sunday seasonal transitions are silent until stronger first-party evidence is
  available.
- A retailer contract change may silence that one store until reviewed.
- A true ambiguous Telegram send cannot be resolved automatically; semantic
  keys remain reserved to prefer no duplicate over speculative retry.

No further correctness or architecture defect is known after the review passes
above.


9. **Live Termux gate pass (2026-10-08)**
   - syntax and focused supermarket tests passed;
   - the full repository suite passed 1812/1812 tests;
   - live Mercadona and DIA contracts passed;
   - live masymas failed closed with `IDENTITY`, revealing that runtime posted the visible locality label instead of the official HTML option value;
   - fixed runtime POST from `IdLocalidad=GUARDAMAR DEL SEGURA` to the official value `IdLocalidad=GUARDAMAR`;
   - added a regression test that asserts the exact encoded POST body.


10. **Second live masymas review (2026-10-08)**
    - the follow-up gate still failed closed with `masymas:IDENTITY`;
    - re-reading the proven exact production probe showed the successful request was
      `IdLocalidad=GUARDAMAR DEL SEGURA`; the intermediate `GUARDAMAR`
      hypothesis was disproven and reverted;
    - the real remaining gap was the legacy masymas HTML: nested tables place
      independent `<tr>` rows inside parent rows;
    - the runtime row parser previously used one depth-wide buffer and could
      collapse/lose the exact store row;
    - fixed parsing to maintain a stack of independent row buffers so nested
      store rows are emitted separately;
    - added a regression fixture with the nested legacy table shape and restored
      the exact proven POST body.
