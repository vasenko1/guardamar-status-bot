# Sports Slice C production verification — 2026-10-05

## Production revision

Deployed and verified:

`9816a58558e739337ec043624421a8aabaa51a4c`

Branch: `main`

## Verification evidence

The production gate completed successfully on the Termux device:

- exact reviewed `main` deployed;
- no affected fishing/source process was running before deploy;
- deployment itself did not mutate the pre-existing Pesca base state;
- Python 3.12.12 and Termux `pdftotext` 26.02.0 available;
- compileall: PASS;
- focused Slice C production suite: **80 tests, OK**;
- full repository suite: **1639 tests, OK**;
- one real `python -m telegrambot.pesca_cv` source preparation completed:
  - base Pesca facts: 2;
  - FEPyC authority records: 1;
  - FPCV detail records: 1;
- base FPCV normalized national range remains 23-29 November, while accepted
  FEPyC authority corrects the projected national occurrence to 26-29 November;
- the reviewed 17 October provincial event joins accepted rich details:
  - provincial Alicante championship / Comunidad Valenciana 2027 qualifier;
  - two 3-hour heats;
  - 16:00 concentration;
  - 18:00-21:00 first heat;
  - 22:30-01:30 second heat;
  - club-mediated registration deadline 13 October at 12:00;
- all three fishing state files are mode 0600;
- the old `state/pesca_cv_events.json` event schema remains exact and
  rollback-compatible;
- separate normalized production state now exists in:
  - `state/fepyc_fishing_authority.json`;
  - `state/pesca_cv_details.json`;
- cron rows remained unchanged;
- `guardamar-preview` restarted and remained running;
- no Telegram publication was triggered.

Post-refresh evidence:

- `state/pesca_cv_events.json` SHA-256:
  `40a0dbd5ab70ed90d050511c86a548070b3b6d9ec0f88e9c4d012a7ba8c40f57`;
- FEPyC authority SHA-256:
  `5fa2d364570a3de1d186b810fe1d9a21dbf57473a4a5e295acdfe80a5176934e`;
- FPCV details SHA-256:
  `2afe1a15bbc38ca94899acceae64bc8fcf7967e30c8def643f7390335f3ce83d`.

## Gate result

**PASS**

Slice C is complete in production.

Slice D may proceed. Slice E remains blocked until Slice D passes its own
implementation/test/review/production gates.
