# Condition Derivation

## Purpose
Document how the Home Assistant weather condition is taken from GeoSphere's own
weather-symbol code (`sy`), how observations override it for the current
condition, and the shared meteorological helper math.

## Responsibilities
- Document the `sy` code table and its mapping to HA condition strings.
- Explain `derive_condition_from_symbol` (forecast hours) and `derive_current_condition` (now).
- Cover the helper functions: wind vectors, apparent temperature, dew point, night.

## Non-Responsibilities
- Which forecast stamp a row reads the symbol from — see [FORECAST.md](FORECAST.md).
- Which observation feeds the current condition — see
  [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- The thunderstorm outlook entities — see [FORECAST.md](FORECAST.md#thunderstorm-outlook).
- Dataset parameter definitions — see [DATASETS.md](DATASETS.md).

## Overview

`custom_components/geosphere_next/condition.py` is a pure, `homeassistant`-free
module (fully unit-tested in `tests/test_condition.py`). Condition strings equal
Home Assistant's `ATTR_CONDITION_*` values but are written as literals to keep
the module import-free.

### The `sy` code table

GeoSphere published the weather-symbol table, in German, in
[dataset-api-docs#30](https://github.com/Geosphere-Austria/dataset-api-docs/issues/30#issuecomment-2042539848).
It was confirmed there for `nwp-v1`; that `nwp-v2` follows it is measured, not
published — see [DATASETS.md](DATASETS.md#the-sy-code-table-on-nwp-v2). The code
groups live in `const.py` (`SY_CLEAR` … `SY_THUNDER`):

| `sy` | GeoSphere | HA condition |
|---|---|---|
| 1, 2 | Wolkenlos, Heiter | `sunny`, or `clear-night` at night |
| 3 | Wolkig | `partlycloudy` |
| 4, 5 | Stark bewölkt, Bedeckt | `cloudy` |
| 6, 7 | Bodennebel, Hochnebel | `fog` |
| 8, 9 | Leichter / Mäßiger Regen | `rainy` |
| 10 | Starker Regen | `pouring` |
| 11–13 | Schneeregen | `snowy-rainy` |
| 14–16 | Leichter / Mäßiger / Starker Schneefall | `snowy` |
| 17, 18 | Regenschauer | `rainy` |
| 19 | Starker Regenschauer | `pouring` |
| 20–22 | Schneeregenschauer | `snowy-rainy` |
| 23–25 | Schneeschauer, Starker Schneeschauer | `snowy` |
| 26, 27 | Gewitter | `lightning-rainy` |
| 28 | Starkes Gewitter | `lightning-rainy` |
| 29, 30 | (Starkes) Gewitter mit Schneeregen | `lightning-rainy` |
| 31, 32 | (Starkes) Gewitter mit Schneefall | `lightning-rainy` |

A missing code, or one outside the table, maps to `None` (unknown) — never a
guess. The table has no night variants, so `is_night` decides between `sunny`
and `clear-night`. HA's `windy`, `windy-variant`, `lightning` (dry thunder),
`hail` and `exceptional` have no code and never occur.

### `derive_condition_from_symbol` (per forecast hour)

Inputs: the hour's `sy` code and `night`. Returns the table's condition. Every
thunderstorm code, the sleet and snow ones (29–32) included, maps to
`lightning-rainy`: HA has no thundersnow condition, and the thunderstorm is the
hazard people act on. `is_thunder_symbol` is the shared 26–32 test, also used by
the current condition and the outlook.

### `derive_current_condition` (now)

The symbol comes from a model run that is routinely 3–6 h old (see
[DATASETS.md](DATASETS.md#publication-latency)), so observations decide whether
and what is falling now. Keyword-only inputs: the nowcast precipitation-type code
and rate, temperature, the `sy` code of the forecast hour covering now, and
`night`. `is_precipitating` reads the code and rate as observed wet, observed
dry, or nothing observed (`None`):

1. **Observed wet** (pt ≠ 255, or rate ≥ 0.1 mm/h — where an INCA-sourced rate
   counts only while its analysis hour still touches the present, see
   [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md)). The `pt` code decides the
   kind; temperature (`SNOW_MAX_T2M_C` = 1.0 °C) splits rain from snow only
   when the code names no kind — absent, 255 beside an observed rate, or a
   code outside GeoSphere's table:
   `snowy` if T ≤ 1 °C and the kind is pt 5 or none, else `lightning-rainy`
   when the hour's symbol is 26–32, else `snowy` (pt 5), else `snowy-rainy`
   (pt 7 rain and snow, or pt 3 freezing rain, which HA has no condition for),
   else `pouring` (≥ 4 mm/h) or `rainy`. pt 1 is rain at any temperature, and
   no kind is rain above 1 °C or with no temperature. The symbol's own kind
   (rain, sleet, snow) is never used here.
2. **Observed dry**: the symbol's mapping, except that a precipitation or
   thunder code (8–32) reads `cloudy` — the model expects precipitation that
   is not falling, under what is then an overcast sky. Fog comes only from
   codes 6–7.
3. **Nothing observed** (outside the nowcast grid, or the nowcast down and
   INCA's `RR` stale): the symbol is the only evidence and its mapping applies
   unchanged, rain and thunder included.

**Snow outranks a thunder symbol when cold.** At or below 1 °C observed snow
(pt 5, or no kind) shows `snowy` even when the hour's symbol is a thunderstorm.
HA's `lightning-rainy` depicts rain, thundersnow is rare and still snow, and the
run behind the symbol may have expected a warmer airmass than the one now
snowing. Above 1 °C, or when no source has a temperature, the thunder symbol
wins over every kind, since a graupel or rain-and-snow shower can still be a
storm. Cold pt 7 and pt 3 lose to thunder too: they are not snow. The forecast
rows have no observation to weigh, so a 31/32 hour there reads
`lightning-rainy`.

The current precipitation rate comes from the nowcast `rr` (15-min bucket ×
`NOWCAST_BUCKETS_PER_HOUR` to mm/h) when available, else a current INCA 1 h
`RR`, else `None`.

### Helper math

- `wind_from_components(u, v)` → (speed via `hypot`, meteorological bearing °).
- `apparent_temperature(t, rh, wind)` — Australian BoM formula.
- `dew_point_from_t_rh(t, rh)` — Magnus formula (the forecast has no dew-point param).
- `is_night(lat, lon, when)` — `astral` solar elevation < 0.

## Dependencies
- `astral` — solar elevation for the day/night check.
- `const.py` — the `sy` code groups and the observed-precipitation thresholds.

## Design Decisions
- GeoSphere's own classification over our thresholds: the condition matches
  what GeoSphere's products show, and no cloud, gust, fog or CAPE threshold
  needs tuning here. Raw values (cloud, precipitation, gusts, CAPE) are
  unchanged on the forecast rows and sensors.
- Observations outrank the symbol for what is falling now, because the symbol's
  run is hours old. Thunder is the one thing observations cannot see, so it
  comes from the symbol, and only while precipitation is observed.
- Duplicating HA `ATTR_CONDITION_*` literals rather than importing them keeps the
  module pure and independently testable.

## Known Risks
- The `nwp-v2` table is assumed equal to the `nwp-v1` one GeoSphere confirmed.
  The measured evidence is in [DATASETS.md](DATASETS.md#the-sy-code-table-on-nwp-v2):
  cloud, precipitation-intensity, rain/sleet/snow and thunder classes all track
  the parameters they should, but codes 6–7 (fog), 25, 30 and 32 were never
  observed. If `nwp-v2` does not emit fog codes, **no hour and no current
  condition will ever read `fog`**.
- GeoSphere's thunder codes fire at modest CAPE (median ~160 J/kg in the
  sample, never above ~480 J/kg), far below the outlook's 1000 J/kg ensemble
  threshold, so `lightning-rainy` is driven by GeoSphere's own diagnosis, not
  by CAPE.
- Codes 1–5 bin `tcc` at the end of the row's hour, while the row's
  `cloud_coverage` is `tcc` at its start (see [FORECAST.md](FORECAST.md)), so the
  condition and the cloud percentage beside it can disagree by a class.

## Extension Guidelines
- To change a mapping, move the code between the `SY_*` groups in `const.py`
  and update `SYMBOL_TABLE` in `tests/test_condition.py`.
- Keep the module free of `homeassistant` imports.
