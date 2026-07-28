# ADR 0018: Named nearby beach flags

- Status: Accepted
- Date: 2026-07-28

## Context

SafeBeach can publish different flags for adjacent Guardamar beaches. An
unnamed Centre flag can therefore be misread as the status of the whole
coast. Averaging safety flags would create a value that no lifeguard service
published, while listing all six SafeBeach positions would add noise.

## Decision

- Show individual active flags for the three beaches closest to the urban
  centre: Centre / Babilònia, La Roqueta, and Vivers.
- Render them in the fixed compact order `Centre`, `Roqueta`, `Vivers`.
- Never average flags or replace a missing beach with another beach's value.
- Omit an unavailable individual flag; omit the complete flag row when none
  are active.
- Keep sea temperature, sea state, and current beach wind tied to the Centre
  record. The existing AEMET temperature fallback remains unchanged.
- Put the optional Centre sea state beside the sea temperature.

## Consequences

- The digest remains short while making geographic differences explicit.
- Users can see that a nearby beach has a stricter flag without interpreting
  one indicator as city-wide.
- SafeBeach schema tests now cover three selected beach records and sea state.
- Source failure still cannot block the weather digest.

## Alternatives considered

- Average all flags: rejected because safety statuses are not numeric.
- Use the most restrictive city-wide flag: rejected because it hides the
  location and can incorrectly describe Centre.
- List all six SafeBeach positions: deferred because it overloads the daily
  digest; a separate command can be considered after MVP.
