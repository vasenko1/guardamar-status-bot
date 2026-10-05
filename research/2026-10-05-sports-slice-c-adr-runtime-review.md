# Sports Slice C ADR/runtime review — 2026-10-05

## Scope

Documentation-only gate after the live Termux source-contract probe and before
any Slice C Python implementation.

Reviewed branch:
`feat/sports-foundation-slice-c`

Base main:
`0c01686545ee90236a2ab33a433b6f24a17d789f`

## Verified

Before runtime code changes, the branch changes only:

- ADR 0101;
- Runtime Constraints;
- Data Sources;
- Decision Log;
- Slice B production verification;
- Slice C source-contract research;
- sports implementation-plan checkpoint.

No Python module, shell wrapper, cron row, source-state file or Telegram path is
changed by this stage.

## Contract bounds

ADR 0101 and KB04 are no broader than the successful production probe:

- exact first-party FPCV linked PDF only;
- HTTPS and approved host;
- `application/pdf`;
- `%PDF-` magic;
- <= 1 MiB PDF bytes;
- one `pdftotext -layout` extraction;
- <= 10 s extraction timeout;
- <= 64 KiB non-empty UTF-8 extracted text;
- no OCR/browser/JavaScript/new Python dependency;
- raw PDF/text are process-local only.

## State/authority review

- existing strict `state/pesca_cv_events.json` remains unchanged;
- new FEPyC authority and FPCV details are separate rollback-safe normalized
  files;
- details failure may not invalidate a successful base fishing refresh;
- FEPyC is consumed inside fishing projection before generic Event merge;
- no parallel generic FEPyC Event is approved;
- FEPyC authority may override only reviewed national occurrence dates;
- the known unsafe FPCV national range fails closed when no accepted FEPyC
  authority can prove it.

## Runtime review

The implementation must remain in the existing short-lived 05:10 fishing
preparation lifecycle.

No new cron, daemon, Event Access fetch path, runtime AI, browser or queue is
authorized.

The implementation must choose explicit small maxima for authority pages and
relevant convocatoria documents before rollout.

## Gate result

**PASS**

Slice C Python implementation may begin.

The next gate is implementation -> focused/full tests -> manual review. Any
defect restarts that cycle before production deployment or Slice D.
