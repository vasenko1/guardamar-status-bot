# ADR 0064: Immutable morning anchor and semantic operational updates

Status: accepted (2026-09-14)

The 07:30 Morning Digest is an immutable daily snapshot and remains the
reply anchor. Later CAMS, Meteosalud and AEMET changes are compact,
deterministic replies only when user-facing meaning changes. Late CAMS compares
the current and remaining local hours while retaining historical samples for
its rolling windows. Valid Meteosalud levels, including zero, replace only the
prior verified level; stale or unavailable data preserves it.

CAMS keeps the mutable source cache separate from the raw cycle that produced
the accepted public semantic baseline. A remotely fetched production cycle is
first saved as an exact cycle-addressed candidate using an atomic process-safe
temporary file. After the public outcome is known, that exact candidate may be
promoted to the accepted snapshot. Reconstruction of an older accepted cycle
reads only the accepted snapshot and never rewrites a candidate. Publication
state stores only compact semantic facts and has no source-cache side effects.
Operator previews use a disposable CAMS cache copied from the mutable last-good
file, so preview activity cannot overwrite production cache or candidates.
The late environment read, compare, Telegram send and semantic-state update
share the existing publication-state lock. If raw snapshot promotion fails
after a Telegram update has already succeeded, the semantic state still
advances so the same public alert is not deliberately repeated.

SafeBeach has a separate seasonal root message that is edited as verified
coverage grows while retaining any Mayor bathing restriction. The root is
built from the union of previously confirmed beach facts and newly confirmed
changes, so a beach missing from a later partial source response cannot erase
its last confirmed status. The first confirmed beach status populates the root
itself and does not generate a duplicate reply. Later confirmed changes reply
to that root. If the root disappears between refresh and reply, the complete
confirmed root is recreated before the reply is retried; a standalone change
message is never stored as the root. Public flag blocks are phone-first: the flag colour/type is on its own line,
beach names follow on rows of at most three names, and the bathing meaning is a
separate final line. Mixed states are ordered red, yellow, then green; when all
tracked beaches share one colour the names are omitted in favour of an all-beaches
summary. An explicit bathing prohibition suppresses contradictory permission
wording. Newer explicit Mayor bathing transitions are checked only on existing
initial/operational windows and refresh this same root; source failure preserves
the last verified notice. The ADR intentionally does not hard-code any one
beach-specific phrase.

A small atomic JSON state stores anchors and compact baselines; there is no
database, daemon, new cron, runtime AI generation, or project-wide scheduler
lock. Legacy state containing replacement identifiers remains readable during
the same-day cutover. New days use the immutable-anchor lifecycle. Source
failure, stale data, or missing data never becomes a false risk-cleared
notification.
