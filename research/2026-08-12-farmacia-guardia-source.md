# Farmacia de guardia source for Guardamar del Segura

## Question

Can the on-call pharmacy rota for Guardamar be collected from the legally
authoritative source with one bounded request and no browser automation?

## Sources checked

- Colegio Oficial de Farmacéuticos de Alicante,
  `https://cofalicante.com/farmacias-de-guardia/`, accessed 2026-08-12.
  The provincial college legally responsible for the on-call rota.
- Its linked annual publication
  `https://www.cofalicante.com/ficheros/farmaciasguardia/guardias2026.xlsx`,
  downloaded and inspected 2026-08-12.

## Findings

- The search page itself is JavaScript-populated (a WordPress plugin,
  `libs_wordpress_cofa_on_call_pharmacies`, fills a `Cargando…`
  placeholder). Scraping it would require script execution or an
  undocumented AJAX endpoint — both outside the project constraints.
- The page, however, links one explicit official download: `Descargar
  guardias 2026`, a ~2.0 MB XLSX with the complete provincial rota for the
  year. This is a documented public publication, comparable in standing to
  the reviewed Policía Local PDF.
- The workbook is a single sheet of ~26,300 rows with the header
  `FECHA · ZONA · NOMBRE ZONA · TURNO · Nº FARMACIA · NOMBRE FARMACIA ·
  DIRECCIÓN · MUNICIPIO · HORARIO`. All strings are inline (`inlineStr`),
  so the standard-library `zipfile` + `ElementTree` parse it without any
  dependency. `FECHA` is an Excel serial day number
  (`date(1899, 12, 30) + serial`).
- Filtering `MUNICIPIO == "Guardamar del Segura"` yields 343 rows for
  2026. Observed shift patterns: `De 9:00 a 9:00` (24-hour duty),
  `De 21:00 a 9:00` (night), and `RF*` reinforcement rows
  `De 9:00 a 22:00` (daytime). Names and street addresses are complete,
  e.g. `PLANELLES MAS, ASUNCION · AV. CERVANTES, Nº29`.

## Recommendation

Feasible with high confidence. Collect through a pre-morning sync command,
never at 07:30: one bounded fetch of the annual XLSX (exact host, 4 MB
cap), normalization of only Guardamar rows in a bounded forward window
into a small atomic local catalog, and a read-only morning row from that
catalog. The raw workbook is never stored. The yearly filename changes
(`guardias2027.xlsx`); the sync derives it from the current local year and
fails closed in an unpublished January until the new file appears.
Open question: whether the college updates the annual file mid-year for
rota swaps — the weekly refresh absorbs that automatically.
