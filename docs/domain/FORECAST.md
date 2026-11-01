# Hourly Forecast

## Purpose
Document how the forecast coordinator turns the deterministic point forecast
(called AROME in the code) and the C-LAEF ensemble into the hourly forecast,
including the stamping of interval parameters, the stepped precipitation
probability, and the thunderstorm outlook scanned from it.

## Responsibilities
- Explain AROME hourly processing: time window, wind decomposition, dew point.
- Explain how interval-ending parameters (precipitation, snow, gust) are read.
- Explain the stepped precipitation probability derived from ensemble percentiles.
- Explain the storm-outlook entities (`outlook.py`).

## Non-Responsibilities
- The `sy` → condition mapping — see [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md).
- Current-conditions merging — see [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- Dataset definitions — see [DATASETS.md](DATASETS.md).

## Overview

`GeoSphereForecastCoordinator` (`custom_components/geosphere_next/coordinator.py`)
runs at the forecast interval (default 30 min). Each cycle resolves AROME
(required) and the C-LAEF ensemble (optional) — from cache when neither can
have been rerun yet, see [Run gating](#run-gating) — then `_process` builds a
list of `HourlyForecast` entries (each carrying its `weather_symbol`) plus a
`current` step-0 snapshot and `snow_limit`. The current-conditions coordinator picks its AROME
hour out of `hourly` by the clock and only falls back to `current` when the
series no longer covers now — see [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).

### Run gating

The models rerun less often than the coordinator ticks: both AROME and C-LAEF
every 3 h. `_run_is_current` compares a cached response's
`reference_time` against the matching cadence (`AROME_RUN_INTERVAL`,
`ENSEMBLE_RUN_INTERVAL` in `const.py`) and serves the cache while a re-fetch
could only return the same bytes. Same shape as the INCA cache in
[CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md): keyed on the age of the *data*,
not of the HTTP call.

The gate is deliberately keyed on the bare cadence rather than on an estimate of
when GeoSphere actually publishes, which is hours later (see
[DATASETS.md](DATASETS.md)). Once `reference_time + cadence` passes, every cycle
retries until a newer run appears. That under-caches — the retries during the
publication lag are wasted — but it never serves a run that has been superseded,
and it picks a new run up within one forecast interval of publication. A
latency estimate would invert both properties.

`_process` re-runs on every cycle regardless, cached or not: the cutoff, the
derived conditions and the day/night flags are all functions of `now`, so the
published forecast still begins at the hour under way on every tick. A cached
response also carries a `start` bound older than the current tick would have
requested; the extra leading rows precede the cutoff and are dropped there.

The run stamp is surfaced as the `model_run` sensor (diagnostic, enabled by
default) so a stale forecast is distinguishable from a wrong one.

### Hourly processing

- **Time window**: hours from the top of the current hour onward are kept, so
  the forecast starts at the current hour (matching OpenWeatherMap /
  Open-Meteo). The **final** stamp is always dropped -- see the stamping rule
  below, which needs a successor.
- **Two stampings, one row**: a row stamped `T` describes the hour *beginning*
  at `T`, but the dataset mixes instantaneous and interval parameters:

  | Stamping | Parameters | Read at |
  |----------|------------|---------|
  | Instantaneous at the stamp | `2t`, `2r`, `10u`/`10v`, `tcc`, `cape`, `snowlmt` | `i` |
  | The interval **ending** at the stamp | `10fg`, `tp`, `sf`, `sy` | `i + 1` |

  The metadata says so in words — `10fg` is the "maximum 10 metre wind gust
  **in the last forecast interval**", `tp` the "total amount of liquid and
  solid precipitation **in the last forecast interval**" — and the data
  confirms it: requested from the run's t0, all three are `null` at index 0.
  `tp` and `sf` are per-hour amounts, not run-accumulated, so they are read
  directly. Reading the interval fields at `i` reports the hour that already
  ended: rain that has stopped, and the previous hour's gust peak.
- **Condition**: `derive_condition_from_symbol(sy, is_night(ts + 30 min))` —
  night is judged at the middle of the row's hour (`FORECAST_ROW_MIDPOINT`),
  so a clear hour that is mostly dark reads `clear-night` — see
  [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md). `sy` is read at `i + 1`
  because its precipitation classes follow `tp` at their own stamp, measured
  over the whole grid (see
  [DATASETS.md](DATASETS.md#the-sy-code-table-on-nwp-v2)): only there does the
  row's condition agree with the row's own precipitation amount. Read at `i`,
  a row would show rain for the hour after it stopped and none for the hour it
  started. The cost is the cloud classes, which bin `tcc` at that later stamp
  — the sky at the *end* of the row's hour, while the row's `cloud_coverage`
  is the sky at its start. The code is kept on the row as `weather_symbol`,
  and the current coordinator reads it from the row covering now.
- **Wind**: `wind_from_components(10u, 10v)` converts u/v components to (speed
  m/s, meteorological bearing °) — see
  [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md). The gust `10fg` is
  already a scalar speed.
- **Dew point**: `dew_point_from_t_rh(2t, 2r)` (Magnus formula) — the dataset
  has no dew-point parameter.
- **Cloud**: `tcc` is published in percent and passed through unchanged.

This rule is verified in `tests/test_coordinator.py`
(`test_forecast_interval_fields_describe_the_hour_they_start`,
`test_forecast_symbol_describes_the_hour_it_starts`).

### Stepped precipitation probability

GeoSphere publishes no precipitation probability. The value on each row is an
**estimate this integration derives** from the C-LAEF ensemble, which
publishes only `tp_p10` / `tp_p50` / `tp_p90` percentiles per hour — no member
counts, so no true wet-fraction. `_precipitation_probability`
maps the wettest percentile above `PRECIP_MIN_MM` (0.1 mm) to the midpoint of the
range it implies:

- `p10` wet ⇒ **95 %** (≥ 90 % of members wet)
- `p50` wet ⇒ **70 %** (50–90 %)
- `p90` wet ⇒ **30 %** (10–50 %)
- none wet ⇒ **0 %**
- `p90` missing ⇒ `None` (no probability)

The percentiles are **interval** values, like `tp` and the gust: GeoSphere
documents them as "in the last forecast interval", so a percentile stamped
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

### Thunderstorm outlook

`outlook.py` scans the processed rows; the entities re-evaluate on every hour
boundary as well as on coordinator updates. Two signals:

- **Symbol**: the row's `sy` is a thunderstorm code (26–32), GeoSphere's own
  verdict for the deterministic run.
- **Ensemble**: the row's `ensemble_cape_p90` ≥ `THUNDER_CAPE_JKG` (1000 J/kg)
  **and** its `ensemble_precipitation_p90` ≥ `PRECIP_MIN_MM` (0.1 mm). So at
  least a tenth of the C-LAEF members reach that CAPE, and at least a tenth
  that much precipitation — not necessarily the same members. `cape_p90` is
  instantaneous and read at the row's own stamp, like `cape`; `tp_p90` covers
  the row's hour, keyed to the preceding stamp like the probability.

The entities:

- `thunderstorm_expected_next_hour` (key `thunderstorm_expected_1h`): on when
  any row in the window (the in-progress hour plus the next) fires either
  signal. The `source` attribute names which: `symbol`, `ensemble` or
  `symbol_and_ensemble`, judged across the window; `None` when off. A row is
  decidable with a symbol or a complete ensemble pair; a window with no
  decidable row reports `unknown`, never a confident `off`. Built for storm
  blinds, where a false alarm costs a closed blind and a miss costs the blind,
  so either signal suffices.
- `next_thunderstorm`: the start of the first row from the in-progress hour on
  that fires either signal — the same per-row test, so whenever the binary
  sensor is on, this names a row inside its window. Attributes: that row's
  `cape` and its own `source` (judged for that row alone).
- `cape_max_12h`: peak deterministic CAPE over 12 h, a plain diagnostic that
  no longer decides anything.

Measured 2026-11-01, GeoSphere's thunder codes fire at a median CAPE of
~160 J/kg and never reached 1000 J/kg anywhere in the domain, so in practice
the symbol is the season-round signal and the ensemble adds high-CAPE summer
situations the deterministic run does not convect on.

### Partial-failure isolation

AROME failure raises `UpdateFailed` (rate-limit errors propagate `retry_after`).
Ensemble failure is caught, logged at warning level, and only omits the
precipitation probability and the ensemble storm signal — it never takes the
forecast down; the outlook then rests on the symbol alone. Once a run has
been cached, a failed ensemble *re*-fetch degrades to that run rather than to
nothing: the percentiles are matched to AROME by timestamp, so a superseded run
still has a value for every hour it covers, and hours it has run past simply
report no probability.

That fallback is bounded by `ENSEMBLE_MAX_FALLBACK_AGE` (12 h: the publication
lag, which alone exceeds the 3 h cadence, plus two cadences). A
superseded run is an older, worse forecast for the same hour rather than the
same answer, and nothing on display says which run a probability came from —
the `model_run` sensor reports AROME's stamp, not C-LAEF's. Past the bound the
cache is dropped and the probability disappears, which is visible rather than
quietly wrong.

An AROME response is committed to the cache only after `_process` accepts it.
A run that parses but yields no usable hours would otherwise be pinned by the
gate for a whole cadence, re-raising the same `UpdateFailed` every tick.

### No daily forecast

The weather entity exposes `FORECAST_HOURLY` only. AROME's ~60 h horizon yields
at most 2–3 aggregable local days, and the HA frontend only renders forecast
arrays with more than 2 entries, so a daily tab would intermittently spin
forever. See the README FAQ and [../tech/ARCHITECTURE.md](../tech/ARCHITECTURE.md).

## Dependencies
- AROME and C-LAEF ensemble datasets — see [DATASETS.md](DATASETS.md).
- `condition.py` helpers (`wind_from_components`, `dew_point_from_t_rh`,
  `derive_condition_from_symbol`, `is_thunder_symbol`, `is_night`).

## Design Decisions
- Stepped, ensemble-backed probability over smooth interpolation is a deliberate
  accuracy-over-appearance trade-off (v0.8.0).
- The in-progress hour is kept (comparing to the top of the hour) so the forecast
  begins at the current hour. The request is anchored to the top of the hour and
  backed off by `HOURLY_LOOKBACK_HOURS`. The anchor is the load-bearing half:
  where an unbounded request begins is undocumented, and the API rounds a
  *mid-hour* `start` up to the next whole stamp — so anchoring to `now` at 15:30
  returns 16:00 and drops the hour under way, while `start = 15:00` is honoured
  exactly (re-measured on `nwp-v2-1h-1km` 2026-11-01; a `start` before the
  run's t0 comes back at t0). The lookback is margin on top of that. `_process` drops whatever
  precedes the cutoff.
- Interval parameters are read one step on rather than re-stamped, so the row
  keeps HA's convention that `datetime` is the *start* of the forecast period.
  The cost is the final stamp, which has no successor and cannot be emitted.
- Fetches are gated on the model rerun cadence rather than scheduled against
  the model run times. GeoSphere publishes hours behind the hour a run is
  stamped for and the lag varies, so a cron on 00/03/06… would fetch before the
  data exists; the gate needs no estimate of the lag and self-corrects if
  GeoSphere shifts it. Gating the *request* rather than the update interval
  also keeps `CONF_FORECAST_INTERVAL` meaningful — it still controls how often
  the clock-dependent parts of `_process` re-run.

## Known Risks
- A row's condition (from `sy` at the end of its hour) and its
  `cloud_coverage` (from `tcc` at the start) can disagree by a cloud class.
- The ensemble storm signal pairs two independent 90th percentiles, so it can
  fire when no single member has both the CAPE and the precipitation — a
  deliberate lean towards false alarms.
- A transient AROME failure still raises `UpdateFailed` and takes the entities
  unavailable even when a usable run is held in the cache. Serving it would
  match the ensemble's degradation, but it would also change the documented
  primary-dataset contract, so the failure stays loud for now.
- The ensemble's own run stamp is not surfaced anywhere, so a probability
  derived from a superseded run inside the fallback bound is indistinguishable
  from a current one.
- Any new AROME parameter has to be classified as instantaneous or
  interval-ending before it is wired in. The metadata's wording is a hint, not
  proof — `pt` is described as "in the last forecast interval" yet has a value
  at t0, and `ssrd` carries no such wording yet is `null` there — so classify
  by requesting from the run's t0 and checking index 0
  (`scripts/explore_api.py` does this). Getting it wrong shifts that field by
  an hour, silently.

## Extension Guidelines
- To expose a new forecast field, add it to `HourlyForecast`, populate it in
  `_process`, and map it in `weather.py`'s `_async_forecast_hourly`.
