# Hourly Forecast

## Purpose
Document how the forecast coordinator turns the AROME point forecast (and C-LAEF
ensemble) into the hourly forecast, including accumulation differencing and the
stepped precipitation probability.

## Responsibilities
- Explain AROME hourly processing: time window, wind decomposition, dew point.
- Explain differencing of run-accumulated precipitation/snow series.
- Explain the stepped precipitation probability derived from ensemble percentiles.

## Non-Responsibilities
- The condition string per hour — see [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md).
- Current-conditions merging — see [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- Dataset definitions — see [DATASETS.md](DATASETS.md).

## Overview

`GeoSphereForecastCoordinator` (`custom_components/geosphere_next/coordinator.py`)
runs at the forecast interval (default 30 min; the AROME model itself only reruns
every 3 h). Each cycle fetches AROME (required) and the C-LAEF ensemble
(optional), then `_process` builds a list of `HourlyForecast` entries plus a
`current` step-0 snapshot, `snow_limit`, and the raw `weather_symbol`. The
current-conditions coordinator picks its AROME hour out of `hourly` by the
clock and only falls back to `current` when the series no longer covers now —
see [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).

### Hourly processing

- **Time window**: hours from the top of the current hour onward are kept, so
  the forecast starts at the current hour (matching OpenWeatherMap /
  Open-Meteo). The **final** stamp is always dropped -- see the stamping rule
  below, which needs a successor.
- **Two stampings, one row**: a row stamped `T` describes the hour *beginning*
  at `T`, but AROME mixes instantaneous and interval parameters:

  | Stamping | Parameters | Read at |
  |----------|------------|---------|
  | Instantaneous at the stamp | `t2m`, `rh2m`, `u10m`/`v10m`, `tcc`, `cape`, `cin`, `snowlmt`, `grad`, `sy` | `i` |
  | The interval **ending** at the stamp | `ugust`/`vgust`, `mnt2m`/`mxt2m`, and the `rr_acc`/`snow_acc` deltas | `i + 1` |

  The dataset metadata is explicit -- `ugust` is "U component of maximum wind
  gust **in the last forecast intervall**", `mxt2m` likewise, and `rr_acc` is
  "accumulated ... since start of the forecast" so `acc[i] - acc[i-1]` spans
  `(ts[i-1], ts[i]]`. Reading the interval fields at `i` reports the hour that
  already ended: rain that has stopped, and the previous hour's gust peak.
- **Wind**: `wind_from_components(u10m, v10m)` and `(ugust, vgust)` convert u/v
  components to (speed m/s, meteorological bearing °) — see
  [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md).
- **Dew point**: `dew_point_from_t_rh(t2m, rh2m)` (Magnus formula) — AROME has no
  dew-point parameter.
- **Cloud**: `_percent()` normalizes AROME `tcc` (0–1) to a percentage.

### Accumulation differencing

AROME `rr_acc` and `snow_acc` are run-accumulated totals. `_diff(series, index)`
computes the hourly amount as `acc[i] - acc[i-1]`, rounded to 2 decimals and
clamped to ≥ 0 so a negative delta (accumulation reset on a new model run) yields
0. Index 0 returns `None` (no predecessor).

Because that delta covers the interval *ending* at `index`, the row for the hour
beginning at `ts[i]` calls `_diff(series, i + 1)` — see the stamping table
above. This rule is verified in `tests/test_coordinator.py`
(`test_forecast_interval_fields_describe_the_hour_they_start`).

### Stepped precipitation probability

The C-LAEF ensemble publishes only `rr_p10` / `rr_p50` / `rr_p90` percentiles
per hour — no member counts, so no true wet-fraction. `_precipitation_probability`
maps the wettest percentile above `PRECIP_MIN_MM` (0.1 mm) to the midpoint of the
range it implies:

- `p10` wet ⇒ **95 %** (≥ 90 % of members wet)
- `p50` wet ⇒ **70 %** (50–90 %)
- `p90` wet ⇒ **30 %** (10–50 %)
- none wet ⇒ **0 %**
- `p90` missing ⇒ `None` (no probability)

The percentiles are **interval** values, like AROME's accumulations and gusts:
GeoSphere documents them as "the last forecast period", so a percentile stamped
`T` covers the period *ending* at `T`. `_process` therefore keys `pop_by_ts` by
the **preceding stamp**, putting each probability on the row that reports the
matching amount. Both grids are hourly, so the keys line up by exact timestamp;
unmatched hours get no probability. Reading the percentiles at their own stamp
— the pre-0.9.2 behaviour — pairs every row's amount with the *previous* hour's
probability. `tests/test_coordinator.py`
(`test_precipitation_probability_matches_the_row_it_is_reported_with`) pins it.

The period start is read from the series rather than by subtracting a fixed
step. Ensembles commonly coarsen along their horizon, and if C-LAEF ever does,
a hardcoded 1 h step would miss every AROME row past the break and blank the
probability across the whole forecast — silently, with nothing logged. The
predecessor is correct at any cadence, and index 0 (the run start, whose "last
period" precedes the run) simply has no row to land on.
`test_precipitation_probability_survives_a_coarsening_ensemble` pins that.

The stepped values (0/30/70/95) are coarser
than the smooth percentages other providers show but are each ensemble-backed
rather than interpolated (see the README FAQ). Thresholds and the percentages
live in `const.py` (`POP_P10_WET_PCT` etc.).

### Partial-failure isolation

AROME failure raises `UpdateFailed` (rate-limit errors propagate `retry_after`).
Ensemble failure is caught, logged at warning level, and only omits the
precipitation probability — it never takes the forecast down.

### No daily forecast

The weather entity exposes `FORECAST_HOURLY` only. AROME's ~60 h horizon yields
at most 2–3 aggregable local days, and the HA frontend only renders forecast
arrays with more than 2 entries, so a daily tab would intermittently spin
forever. See the README FAQ and [../tech/ARCHITECTURE.md](../tech/ARCHITECTURE.md).

## Dependencies
- AROME and C-LAEF ensemble datasets — see [DATASETS.md](DATASETS.md).
- `condition.py` helpers (`wind_from_components`, `dew_point_from_t_rh`,
  `derive_condition`, `is_night`).

## Design Decisions
- Stepped, ensemble-backed probability over smooth interpolation is a deliberate
  accuracy-over-appearance trade-off (v0.8.0).
- The in-progress hour is kept (comparing to the top of the hour) so the forecast
  begins at the current hour. The request is anchored to the top of the hour and
  backed off by `HOURLY_LOOKBACK_HOURS`. The anchor is the load-bearing half: an
  unbounded request begins well after the current hour, and the API rounds a
  *mid-hour* `start` up to the next whole stamp — so anchoring to `now` at 15:30
  returns 16:00 and drops the hour under way, while `start = 15:00` is honoured
  exactly. The lookback is margin on top of that. `_process` drops whatever
  precedes the cutoff.
- Interval parameters are read one step on rather than re-stamped, so the row
  keeps HA's convention that `datetime` is the *start* of the forecast period.
  The cost is the final stamp, which has no successor and cannot be emitted.

## Known Risks
- Negative accumulation deltas at model-run boundaries clamp to 0; a genuine
  spike straddling a run boundary is therefore under-reported for that hour.
- Any new AROME parameter has to be classified as instantaneous or
  interval-ending before it is wired in; the metadata endpoint's `desc` field
  states which ("in the last forecast intervall"). Getting it wrong shifts that
  field by an hour, silently.

## Extension Guidelines
- To expose a new forecast field, add it to `HourlyForecast`, populate it in
  `_process`, and map it in `weather.py`'s `_async_forecast_hourly`.
