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
3. precipitation ≥ 0.1 mm → `lightning-rainy` (thunder), else `pouring`
   (≥ 4 mm/h), else `rainy`
4. cloud unknown → `None`
5. thunder and cloud ≥ 60 % → `lightning`
6. gust ≥ 15 m/s → `windy-variant` (cloud ≥ 60 %) or `windy`
7. cloud ≤ 12.5 % → `clear-night` (night) or `sunny`
8. cloud ≤ 62.5 % → `partlycloudy`, else `cloudy`

**Thunder** (`is_thunder`) is CAPE ≥ 1000 J/kg, and nothing else: the forecast
dataset publishes no convective inhibition (see [DATASETS.md](DATASETS.md)), so
a capped airmass with high CAPE reads as thunder too. A missing CAPE is no
thunder. The same test applies to the forecast hours and to the current
condition.

`outlook.py` reuses `is_thunder` for the storm-outlook entities, where it
carries a second job: an hour counts as a thunderstorm hour when its derived
condition starts with `lightning` **or** `is_thunder` holds and the hour is
forecast to produce ≥ `PRECIP_MIN_MM` of precipitation. That second branch
exists because rules 1-2 above return `snowy` / `snowy-rainy` before thunder
is ever considered (thundersnow) and rule 4 returns None without cloud data.

Thresholds are named constants in `const.py` (`THUNDER_CAPE_JKG`,
`PRECIP_MIN_MM`, `POURING_MM_PER_H`, `WINDY_GUST_MS`,
`CLOUDY_TCC_PCT`, `CLEAR_TCC_PCT`, `WINDY_CLOUD_TCC_PCT`).

### `derive_current_condition` (now)

Keyword-only inputs including the nowcast precipitation-type code and rate. The
`pt` code decides the kind of precipitation; temperature (`SNOW_MAX_T2M_C` =
1.0 °C) splits rain from snow only when the code names no kind — absent, 255
beside an observed rate, or a code outside GeoSphere's table:

1. precipitating (pt ≠ 255, or rate ≥ 0.1 mm/h — where an INCA-sourced rate
   counts only while its analysis hour still touches the present, see
   [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md)) → `snowy` if T ≤ 1 °C
   and the kind is pt 5 or none, else `lightning-rainy` (thunder), else
   `snowy` (pt 5), else `snowy-rainy` (pt 7 rain and snow, or pt 3 freezing
   rain, which HA has no condition for), else `pouring` (≥ 4 mm/h) or
   `rainy`. pt 1 is rain at any temperature, and no kind is rain above 1 °C
   or with no temperature.
   So snow outranks thunder only at or below 1 °C; above it, or when no
   source has a temperature, a storm wins over every kind, since a graupel
   or rain-and-snow shower can still be a thunderstorm. Cold pt 7 and pt 3
   lose to thunder too: they are not snow.
   Thunder here is the same `is_thunder` test as above: the precipitation is
   *observed* (INCA / the nowcast are anchored to measurements) while CAPE is
   the forecast for the hour.
2. fog heuristic (when `FOG_HEURISTIC_ENABLED`): RH ≥ 98 %, wind < 2 m/s,
   cloud ≥ 87.5 % → `fog`.
3. otherwise delegate to `derive_condition` with zeroed precipitation.

The current precipitation rate comes from the nowcast `rr` (15-min bucket ×
`NOWCAST_BUCKETS_PER_HOUR` to mm/h) when available, else the INCA 1 h `RR`.

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
- Thunder rests on CAPE alone. High CAPE under a capping inversion — a real
  pattern, e.g. light frontal rain beneath a lid — reads as `lightning-rainy`
  (or `lightning` under ≥ 60 % cloud) although nothing triggers convection.
  The storm outlook still requires forecast precipitation for its CAPE branch,
  so dry high-CAPE afternoons do not raise it, but the derived condition can.
- The fog heuristic is a coarse RH/wind/cloud rule (current condition only) and
  can be disabled via `FOG_HEURISTIC_ENABLED`.
- Thresholds are tuned constants; changing one shifts classification across all
  hours and the current state simultaneously.

## Extension Guidelines
- Add or tune a threshold in `const.py`, adjust the branch in `condition.py`, and
  add a parametrized case in `tests/test_condition.py`.
- Keep the module free of `homeassistant` imports.
