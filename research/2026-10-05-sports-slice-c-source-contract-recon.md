# Sports Slice C source-contract recon — 2026-10-05

## Status

**PASS — web/source recon and Termux production contract probe complete.**

The actual Android/Termux environment confirmed the same contracts without
mutating source state, cron, Telegram or the working tree.

## FEPyC national occurrence authority

Fresh public review confirms the first-party event page:

`https://www.fepyc.es/26MC26`

It exposes:

- stable visible ID: `26MC26`;
- title: XVI Campeonato de España Mar-costa Dúos;
- discipline: Lanzado Mar Costa;
- category: Dúos;
- competition type: Nacional;
- place: Guardamar del Segura (Alicante);
- dates: 26-29 November 2026;
- responsible federation: Federación de Pesca Comunidad Valenciana.

This remains the narrow fact-level authority for the national championship
occurrence dates. It should be normalized as a small fishing-authority snapshot
and consumed before generic Event merge, not emitted as a parallel generic
Event that must be fuzzy-resolved later.

## FPCV competition table conflict

Fresh public review of:

`https://federacionpescacv.com/competiciones-de-nuestros-clubes/`

still shows the operational FEPyC/NACIONAL Mar Costa Dúos rows beginning on
23 November in Guardamar.

Therefore the known 23-29 vs 26-29 conflict is still live and must be corrected
before fishing is enabled in sports planning/current-day output.

## FPCV convocatoria index

Fresh public review of:

`https://federacionpescacv.com/convocatorias-clasificaciones-2026/`

still contains a deterministic row for:

- 17/10/2026;
- Provincial Alicante;
- Mar-Costa Captura y suelta;
- Playas la Roqueta y Centro – Guardamar (Alicante);
- exact official convocatoria link.

The same index also still uses explicit `CANCELADO` rows, confirming that
cancellation is a source-owned first-party fact rather than an inferred status.

## Exact FPCV PDF

The 17 October row currently links to:

`https://federacionpescacv.com/wp-content/uploads/2026/09/bases-prov-mar-costa-captura-y-suelta-2026.pdf`

The document is a six-page text-layer PDF.

Reviewed source-backed facts include:

- Campeonato Provincial de Alicante;
- Mar-Costa masculino;
- qualifying for Comunidad Valenciana 2027;
- 17 October 2026;
- Playas La Roqueta y Centro, Guardamar;
- registrations performed by clubs until 13 October at 12:00;
- two competition heats of three hours;
- programme:
  - 16:00 concentration;
  - 18:00-21:00 first heat;
  - 22:30-01:30 second heat;
- schedule may vary slightly with beach occupancy.

These facts are sufficient to enrich the normal Event presentation before the
Event Access projection is enabled later.

## Runtime design consequence

The repository already has an approved bounded text-PDF extraction pattern in
`src/telegrambot/emergency_risks.py`:

- validate PDF magic/size;
- invoke Termux `pdftotext` with `subprocess.run`;
- explicit parse timeout;
- bounded stdout;
- no OCR/browser;
- raw bytes/text process-local.

Slice C should reuse this pattern rather than introduce another PDF framework.

However the current Runtime Constraints authorize Poppler only for already
named workflows. Slice C therefore still requires an explicit ADR/KB amendment
before production FPCV PDF extraction is enabled.

## Production probe requirements

The actual Termux device must verify, read-only:

### FEPyC

- HTTP 200;
- final HTTPS host remains `www.fepyc.es`/`fepyc.es`;
- HTML content type;
- measured bytes/time;
- stable visible markers for ID, date range, category/type and Guardamar.

### FPCV convocatoria index

- HTTP 200;
- final HTTPS host remains `federacionpescacv.com`;
- HTML content type;
- measured bytes/time;
- exact 17 October Guardamar row;
- one deterministic official PDF href;
- cancellation marker remains visible.

### FPCV PDF

- HTTP 200;
- final HTTPS host remains `federacionpescacv.com`;
- `application/pdf`;
- measured bytes/time;
- PDF magic;
- local `pdftotext` available;
- bounded text extraction succeeds quickly;
- exact expected competition/deadline/programme markers are present.

No source/state file, cron or Telegram operation may be mutated by this probe.

## Termux production probe result

Production revision:
`0c01686545ee90236a2ab33a433b6f24a17d789f`.

Observed on 2026-10-05:

- existing normalized FPCV national conflict still present: 23-29 November;
- `pdftotext` available at
  `/data/data/com.termux/files/usr/bin/pdftotext`, version 26.02.0;
- FEPyC `26MC26`: HTTP 200, `text/html`, 33,826 bytes, 0.326 s,
  all expected semantic markers present;
- FPCV convocatoria index: HTTP 200, `text/html`, 161,072 bytes,
  2.465 s, exact 17 October Guardamar row and one exact PDF link present;
- exact FPCV PDF: HTTP 200, `application/pdf`, 609,280 bytes, 1.474 s;
- `pdftotext -layout`: exit 0, 8,442 text bytes, 0.088 s,
  all reviewed competition/deadline/programme markers present;
- pre/post `state/pesca_cv_events.json` SHA-256 unchanged:
  `08a882681c4c3f2848c0ba53c43577aa56319f8766f7b2cf164a162fffc4e346`;
- working tree unchanged;
- no Telegram call, cron mutation or production state write.

## Gate

**PASS**

The source contract is approved for the narrow ADR 0101 runtime amendment.
Python implementation may begin only after the documentation-only ADR/KB change
passes its own consistency review.
