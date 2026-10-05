# Sports Slice B production verification — 2026-10-05

## Production revision

Deployed and verified:

`0c01686545ee90236a2ab33a433b6f24a17d789f`

Branch: `main`

## Verification evidence

Production verification completed successfully:

- exact clean reviewed `main`;
- no affected Morning/Weekend/Tomorrow/FACV/Pesca process running;
- pre/post source and publication state hashes unchanged:
  - FACV:
    `adcd08a056df7162b94161e3063b328011146f1eca5e4e1a700582009bba48a3`;
  - Pesca CV:
    `08a882681c4c3f2848c0ba53c43577aa56319f8766f7b2cf164a162fffc4e346`;
  - Tomorrow:
    `1df941422df4539debdd475c93aa45c1296dd31ae0f7a837f5f847435d518cae`;
  - Weekend:
    `8a1654a3d16cff3b65601bb35b4e843489008d9eceb27a7b4c0401ce39d027fa`;
- Event model smoke:
  - sport remains the final optional field;
  - sport + unknown merge preserves sport;
  - conflicting known sports remain separate;
  - presentation helper is deterministic;
- FACV production snapshot had no retained rows, so the FACV projection smoke
  was correctly skipped rather than inventing a fixture;
- Pesca CV production projection returned one event with
  `sport="fishing"`;
- focused Slice B production suite: **64 tests, OK**;
- cron unchanged;
- `guardamar-preview` restarted and remained running;
- no Telegram publication occurred;
- no persistent state schema changed;
- resident-facing Morning/Tomorrow/Weekend routing remains unchanged.

## Gate result

**PASS**

Slice B is complete in production.

Slice C may proceed. Slice D remains blocked until Slice C passes its own
source-contract, implementation, test, review and production verification gates.
