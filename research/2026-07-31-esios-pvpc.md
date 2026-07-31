# ESIOS next-day PVPC publication

Checked: 2026-07-31

## Official findings

- Red Eléctrica says next-day hourly PVPC prices are updated every day around
  20:15: <https://www.ree.es/es/sala-de-prensa/notas-de-prensa/2014/03/red-electrica-empieza-publicar-los-nuevos-precios-horarios-de-la-electricidad>
- Its consumer guide states 20:20 for publication of the following day's
  hourly prices: <https://www.ree.es/sites/default/files/11_PUBLICACIONES/Documentos/03_Consumidor_Activo_DIGITAL.pdf>
- The current ESIOS API documents personal-token authentication and indicator
  date filtering: <https://api.esios.ree.es/doc/index.html>
- The current PVPC page describes the 2.0TD active-energy term and its official
  green/yellow/orange thresholds: <https://www.esios.ree.es/es/pvpc/>

These statements describe an approximate publication target, not a guaranteed
API availability SLA. The application therefore starts at 20:30 and makes
independent recovery attempts at 20:35, 20:45, 21:00 and 21:20.
