# Sports Slice C source-contract recon — 2026-10-05

## Status

Web/source recon complete. **Termux production probe pending.**

Do not implement Slice C source/runtime changes until the production probe below
confirms the same contracts from the actual Android environment.

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

## Gate

**PENDING TERMUX PROBE**

Implementation of FEPyC authority/details snapshots remains blocked until the
production output is reviewed.
