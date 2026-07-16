# Condition Derivation

## Purpose
Document how the Home Assistant weather condition is derived from physical
parameters (rather than GeoSphere's proprietary symbol code), and the shared
meteorological helper math.

## Responsibilities
- Explain `derive_condition` (forecast hours) and `derive_current_condition` (now).
- Document the thresholds that classify each condition string.
- Cover the helper functions: wind vectors, apparent temperature, dew point, night.

## Non-Responsibilities
- Which parameters feed derivation and from where — see [FORECAST.md](FORECAST.md)
  and [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- Dataset parameter definitions — see [DATASETS.md](DATASETS.md).

## Overview

`custom_components/geosphere_next/condition.py` is a pure, `homeassistant`-free
module (fully unit-tested in `tests/test_condition.py`). GeoSphere's `sy`
weather-symbol code table is undocumented, so — like Open-Meteo for this model —
the HA condition is derived from physical parameters. Condition strings equal
Home Assistant's `ATTR_CONDITION_*` values but are written as literals to keep
the module import-free.

### `derive_condition` (per forecast hour)

Inputs: hourly precipitation, snow, cloud cover (`tcc` %), CAPE, gust speed,
`night`. Precedence:

1. snow ≥ 0.1 mm and rain ≥ 0.1 mm → `snowy-rainy`
2. snow ≥ 0.1 mm → `snowy`
3. precipitation ≥ 0.1 mm → `lightning-rainy` (CAPE ≥ 1000 J/kg), else `pouring`
   (≥ 4 mm/h), else `rainy`
4. cloud unknown → `None`
5. thunder (CAPE ≥ 1000) and cloud ≥ 60 % → `lightning`
6. gust ≥ 15 m/s → `windy-variant` (cloud ≥ 60 %) or `windy`
7. cloud ≤ 12.5 % → `clear-night` (night) or `sunny`
8. cloud ≤ 62.5 % → `partlycloudy`, else `cloudy`

Thresholds are named constants in `const.py` (`THUNDER_CAPE_JKG`,
`PRECIP_MIN_MM`, `POURING_MM_PER_H`, `WINDY_GUST_MS`, `CLOUDY_TCC_PCT`,
`CLEAR_TCC_PCT`, `WINDY_CLOUD_TCC_PCT`).

### `derive_current_condition` (now)

Keyword-only inputs including the nowcast precipitation-type code and rate. The
`pt` code table is undocumented (255 = none), so any other code only signals
*that* it precipitates; rain vs snow is decided by temperature
(`SNOW_MAX_T2M_C` = 1.0 °C):

1. precipitating (pt ≠ 255, or rate ≥ 0.1 mm/h) → `snowy` (T ≤ 1 °C), else
   `lightning-rainy` (thunder), `pouring` (≥ 4 mm/h), or `rainy`.
2. fog heuristic (when `FOG_HEURISTIC_ENABLED`): RH ≥ 98 %, wind < 2 m/s,
   cloud ≥ 87.5 % → `fog`.
3. otherwise delegate to `derive_condition` with zeroed precipitation.

The current precipitation rate comes from the nowcast `rr` (15-min bucket × 4 to
mm/h) when available, else the INCA 1 h `RR`.

### Helper math

- `wind_from_components(u, v)` → (speed via `hypot`, meteorological bearing °).
- `apparent_temperature(t, rh, wind)` — Australian BoM formula.
- `dew_point_from_t_rh(t, rh)` — Magnus formula (AROME has no dew-point param).
- `is_night(lat, lon, when)` — `astral` solar elevation < 0.

## Dependencies
- `astral` — solar elevation for the day/night check.
- `const.py` — every threshold.

## Design Decisions
- Physical-parameter derivation over the proprietary `sy` code (which is exposed
  only as a disabled diagnostic sensor).
- Duplicating HA `ATTR_CONDITION_*` literals rather than importing them keeps the
  module pure and independently testable.

## Known Risks
- The fog heuristic is a coarse RH/wind/cloud rule (current condition only) and
  can be disabled via `FOG_HEURISTIC_ENABLED`.
- Thresholds are tuned constants; changing one shifts classification across all
  hours and the current state simultaneously.

## Extension Guidelines
- Add or tune a threshold in `const.py`, adjust the branch in `condition.py`, and
  add a parametrized case in `tests/test_condition.py`.
- Keep the module free of `homeassistant` imports.
