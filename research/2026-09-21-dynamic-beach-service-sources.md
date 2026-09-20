# Dynamic beach-service sources

Reviewed 2026-09-21.

## Decision

Do not model one universal "official beach season" for Guardamar.

Each resident-facing fact keeps its own source and lifecycle:

- Zona Azul: reviewed ORA seasonal rule and transition notices.
- SafeBeach: current operational flag/activity source; no public "season starts"
  announcement.
- Bathing-water programme: annual dates and newest weekly report discovered
  from the Ayuntamiento index.
- Lifeguard service: research only until a small stable PLACSP contract is
  verified; do not infer start dates from SafeBeach or Zona Azul.
- Beach cleaning and seasonal concessions: separate municipal services with
  their own periods; no combined seasonal notification.

## Bathing-water source

Primary index:

`https://www.guardamardelsegura.es/programa-de-control-de-las-zonas-de-bano/`

The municipal page publishes an explicit current-year control period and dated
weekly PDF links. For 2026 it states 1 June through 15 September.

The first implementation intentionally stores only:

- programme year;
- start and end dates;
- newest linked weekly-report range;
- newest official report URL;
- observation timestamp.

It does not parse PDF laboratory tables and cannot make a public water-quality
claim yet.

The national NÁYADE citizen service is the preferred candidate for actual
sample/result values because it is the official national bathing-water
information system and exposes current controlled zones. A stable Guardamar
query/result contract still needs to be verified before production use.

## Lifeguard source research

PLACSP publishes machine-processable open contracting datasets and states that
the non-minor-contract datasets are updated daily. Current documentation
describes XML/ATOM open-data files; OpenPLACSP documentation identifies
syndication 643 as the feed for tenders published in contractor profiles hosted
on PLACSP.

This makes PLACSP promising, but the bot should not ingest the national feed
until we have verified a cheap deterministic filter for the Guardamar
contracting authority and the exact fields needed for:

- service start/end dates;
- beaches/coverage;
- daily service hours;
- contract replacement or extension.

No lifeguard adapter is implemented in this change.

## Sources

- `https://www.guardamardelsegura.es/programa-de-control-de-las-zonas-de-bano/`
- `https://nayadeciudadano.sanidad.gob.es/Splayas/ciudadano/indexCiudadanoAction.do`
- `https://contrataciondelestado.es/wps/portal/DatosAbiertos`
- `https://contrataciondelestado.es/datosabiertos/DGPE_PLACSP_OpenPLACSP_v.2.2.pdf`
