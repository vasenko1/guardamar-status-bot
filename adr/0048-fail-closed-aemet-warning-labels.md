# ADR 0048: Fail closed on unknown AEMET warning labels

Date: 2026-08-31

## Decision

Normalize known AEMET hazard-name variants deterministically. If the CAP
`event` field contains only a source/status label such as `Aviso AEMET`, or a
hazard not in the allowlist, omit that warning from public and operational
messages. Do not display a generic label that could be mistaken for a hazard.

## Reason

AEMET CAP records can contain source-only or newly named event values. The old
fallback rendered every unknown value as “предупреждение AEMET”, which hid the
actual data-quality problem and gave readers no useful meaning.

## Consequences

Known hazards and conservative aliases continue to render normally. An
unrecognized record is logged for diagnosis and withheld until its hazard can
be mapped from an explicit official value. This keeps the digest truthful and
prevents silent misclassification.
