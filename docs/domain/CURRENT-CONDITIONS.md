# Current Conditions

## Purpose
Document how the current-conditions coordinator merges the nowcast, INCA analysis,
and AROME forecast into one `CurrentConditions` record, and the per-field fallback
chain it applies.

## Responsibilities
- Define the source-preference chain for each current-conditions field.
- Explain the INCA analysis caching and freshness policy.
- Explain the `has_nowcast` capability flag and out-of-Austria degradation.

## Non-Responsibilities
- The condition string derivation — see [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md).
- Forecast processing — see [FORECAST.md](FORECAST.md).
- Dataset definitions — see [DATASETS.md](DATASETS.md).

## Overview

`GeoSphereCurrentCoordinator` (`custom_components/geosphere_next/coordinator.py`)
runs at the current-conditions interval (default 15 min). Each cycle it fetches
the nowcast (if `has_nowcast`), obtains the cached-or-refreshed INCA analysis,
and reads the forecast coordinator's "step 0" AROME snapshot, then merges them in
`_merge` into a `CurrentConditions` dataclass (`models.py`).

### Per-field preference chain

`_merge` uses a small `chain(*values)` helper that returns the first non-`None`
value. The order encodes which source is trusted most for each field:

- **Temperature, humidity, wind speed, wind bearing**:
  INCA analysis → nowcast → AROME step 0.
- **Dew point**: INCA analysis → nowcast only (no AROME fallback).
- **Wind gust**: nowcast → AROME step 0.
- **MSL pressure**: INCA `P0` (Pa) only, converted to hPa.
- **Global radiation**: INCA `GL` only.
- **Cloud coverage, CAPE, snow limit, weather symbol**: AROME (via the forecast
  coordinator) only — the nowcast/INCA products do not carry them.
- **1 h precipitation**: INCA `RR`; if absent, sum the last four 15-min nowcast
  `rr` buckets at/before now.
- **Precipitation type / `is_precipitating`**: nowcast `pt` (255 = none).

INCA analysis is preferred over the 15-min nowcast for thermodynamic fields and
wind because the nowcast extrapolates from an analysis ~2 h behind and lags
diurnal ramps by up to ~2 °C (see the README FAQ). The trade-off is that INCA
publishes with delay, so `observed_at` can trail real time by up to ~75 min.

### INCA caching and freshness

`_async_get_inca` caches the INCA response on the coordinator instance
(`self._inca`) and refetches only when the newest analysis timestamp — not the
fetch time — is older than `INCA_MAX_AGE_SECONDS` (55 min). This decouples the
poll interval from INCA's hourly publish cadence: once the latest hour ages out,
each cycle retries until the next analysis appears. INCA is queried with a
`start`/`end` window of the last `INCA_LOOKBACK_HOURS` (3 h).

### Capability flag and coverage

`has_nowcast` is decided once during the config flow (see
[../tech/ARCHITECTURE.md](../tech/ARCHITECTURE.md)) and stored in `entry.data`.
INCA and the nowcast share the Austria-only grid, so when `has_nowcast` is
`False` (inside the AROME domain but outside Austria) both are skipped and
current conditions degrade to the AROME step-0 snapshot. If no source is
available at all, `_async_update_data` raises `UpdateFailed`.

## Dependencies
- `GeoSphereForecastCoordinator` — injected into the current coordinator's
  constructor to supply AROME fallback values (`current`, `snow_limit`,
  `weather_symbol`).
- INCA analysis and nowcast datasets — see [DATASETS.md](DATASETS.md).

## Design Decisions
- The current coordinator holds a direct reference to the forecast coordinator
  rather than sharing a store — a deliberate simplification for two/three
  coordinators.
- Preferring INCA analysis over the nowcast for thermodynamics/wind was a
  measured decision (v0.6.0).

## Known Risks
- The nowcast `pt` code table is undocumented; only "255 = none" is trusted, and
  rain-vs-snow is decided by temperature — see [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md).
- `observed_at` reflecting INCA delay may confuse users comparing to live
  stations (documented in the README FAQ).

## Extension Guidelines
- To add a current field, add it to `CurrentConditions`, extend `_merge` with the
  appropriate `chain(...)` order, and add a sensor description in `sensor.py`.
- Keep the source order explicit and commented — the chain order is the domain
  knowledge here.
