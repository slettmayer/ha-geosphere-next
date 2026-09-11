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
and picks the AROME hour covering `now`, then merges them in `_merge` into a
`CurrentConditions` dataclass (`models.py`).

The nowcast request carries a `start` of `NOWCAST_LOOKBACK` before the 15-min
floor of `now`. Unbounded, the endpoint begins at the bucket covering `now`, so
the series holds exactly one stamp at or before it and `RATE_LOOKBACK` has
nothing to look back at. As with the AROME request the *anchor* is what matters:
the API rounds a mid-interval `start` up to the next stamp.

The AROME hour is selected per merge with `outlook.hour_at(hourly, now)`, which
matches the top-of-hour floor of `now` — not the `ForecastData.current` snapshot
taken when the forecast was fetched. The forecast coordinator can run up to
180 min apart while this one runs every 15 min, so reading that snapshot would
leave the AROME-only fields (cloud cover, CAPE, CIN) — and with them the derived
condition — hours stale. When the series does not cover `now` at all (a forecast
that has aged out entirely), the merge degrades to `ForecastData.current`.

### Per-field preference chain

`_merge` uses a small `chain(*values)` helper that returns the first non-`None`
value. The order encodes which source is trusted most for each field:

- **Temperature, humidity, wind speed, wind bearing**:
  INCA analysis → nowcast → AROME current hour.
- **Dew point**: INCA analysis → nowcast only (no AROME fallback).
- **Wind gust**: nowcast → AROME current hour.
- **MSL pressure**: INCA `P0` (Pa) only, converted to hPa.
- **Global radiation**: INCA `GL` only.
- **Cloud coverage, CAPE, CIN**: the AROME current hour only — the
  nowcast/INCA products do not carry them.
- **Snow limit, weather symbol**: `ForecastData.snow_limit` /
  `.weather_symbol`, which the forecast coordinator computes once per fetch
  from its first future hour. Unlike the fields above these are not re-picked
  per hour, so they age with the forecast interval.
- **1 h precipitation**: INCA `RR` only. `None` when INCA has none — the
  nowcast cannot stand in, see [Design Decisions](#design-decisions).
- **Precipitation type**: nowcast `pt`, passed through raw as a diagnostic
  sensor. GeoSphere publishes no code table for it, so only 255 (= none) is
  known and the code is never decoded into rain/snow/hail.
- **`is_precipitating`** (the `precipitating` binary sensor): `pt` ≠ 255 **or**
  precipitation rate ≥ `PRECIP_MIN_MM`, via `condition.is_precipitating` —
  the integration's single definition, shared with the condition derivation.
  Either source suffices, and both come from the 15-min nowcast — the only
  source that observes precipitation *now*. `None` when neither spoke, which
  happens outside the Austrian grid (`CONF_HAS_NOWCAST` skips the nowcast and
  INCA alike) and on a failed nowcast fetch; a "dry" there would be invented.
  The coordinator therefore keeps the unobserved rate as `None` rather than
  defaulting it to 0.0.

  INCA's hourly `RR` is deliberately **not** a fallback for this field. It is
  an accumulation over the hour it is stamped for, `inca_latest` returns the
  newest non-`None` value at any age, and the cached slice is served for up
  to `INCA_MAX_AGE_SECONDS` (indefinitely while refreshes fail) — so reading
  it as an instantaneous rate reports rain that has already stopped. Only
  `precipitation_1h` (the measurement it actually is) and the condition
  derivation (which must decide either way) use it.
- **Precipitation rate** (mm/h, feeds the condition): the matched nowcast `rr`
  bucket × `NOWCAST_BUCKETS_PER_HOUR`, else INCA's hourly `RR` where there is
  no nowcast at all — but only while that `RR` is younger than
  `INCA_RR_MAX_AGE_SECONDS` (2 h). `inca_latest` returns the newest value at
  any age and the cached slice is served on indefinitely while refreshes
  fail, so an ungated read derived `rainy` under a clear sky from rain that
  had stopped hours earlier, and held there. The bound marks a slice that has
  **stopped updating**, not ordinary lag — INCA's freshest `RR` is routinely
  up to ~90 min old (same publish cycle that makes `observed_at` trail by
  ~90 min), and a tighter bound would reject the best data the source has for
  part of every cycle, flapping the condition hourly through steady rain.
  Past the bound the derivation falls through to cloud cover. The condition
  must still name something, which is why it keeps the fallback at all —
  `is_precipitating` drops `RR` outright. Note `observation_time` does **not**
  date the accumulation: it anchors to whichever source supplied the
  temperature, which can be a newer row of the same slice. When `pt` says it
  *is* precipitating, the peak across the
  last `RATE_LOOKBACK`
  (30 min) of buckets is used instead of the matched one alone — a single
  bucket can round to 0.0 in the gap between cells, and a rate of 0 mm/h would
  then starve both the `pouring` branch and the downpour override in
  [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md).

  INCA's hourly `RR` is deliberately *not* the wider source here, though it is
  the obvious candidate. It is a total over the whole past hour, so using it
  as an instantaneous rate reports rain that has already stopped: 6 mm falling
  in the first 20 minutes and ending, with drizzle keeping `pt` non-zero,
  would read as 6 mm/h and derive a thunderstorm from a capped, drizzling sky.
  The 30-minute window is short enough that what it reports is still falling.

INCA analysis is preferred over the 15-min nowcast for thermodynamic fields and
wind because the nowcast extrapolates from an analysis ~2 h behind and lags
diurnal ramps by up to ~2 °C (see the README FAQ). The trade-off is that INCA
publishes with delay, so `observed_at` can trail real time by **~90 min**.

That figure is the publish cadence, not the cache policy. INCA appears roughly
30 min after the hour it describes, and the previous slice is served until the
next one exists — so shortly before an analysis lands, the reading on display
is the one from the hour before last. Observed on 2026-08-11: the 07:00Z
analysis was still being served at 08:32Z, 92 minutes old. Lowering
`INCA_MAX_AGE_SECONDS` cannot help; the data simply is not published yet.

This matters most on fast diurnal ramps, where it reads as a disagreement
between "current" and the forecast rather than as staleness. On that same
morning the current temperature showed 19.4 °C (the 09:00 local analysis) while
the forecast row for 11:00 showed 26.1 °C — two hours apart, both correct.
The `observation_time` sensor exists so that age is visible rather than
inferred.

### Observation time

`observed_at` reports the stamp of whichever source supplied the
**temperature** — the field the reading is judged by. Every rung follows that
one field, so no other field's freshness can vouch for it:

1. the INCA analysis carrying `T2M`;
2. the 15-min nowcast bucket that was matched, when INCA has no temperature.
   Its own stamp, not `now` — no source ever states `now`, and this sensor
   exists to show the gap;
3. the AROME row's own stamp, when nothing else contributed, clamped to `now`
   because an observation time can never be in the future. Outside the nowcast
   grid (`has_nowcast = False`) every field comes from `hour_at(...)`, stamped
   at the top of its hour and so up to an hour old — exactly the staleness
   this sensor exists to show.

The INCA analysis behind the *precipitation* is deliberately **not** a rung.
An analysis carrying `RR` but no `T2M` would otherwise date a temperature that
came from somewhere else entirely — overstating staleness just as anchoring to
`now` understates it.

It is surfaced by the `observation_time` sensor (diagnostic, but **enabled by
default**, unlike the other diagnostics): every other entity presents the
analysis as "now", so without it a stale reading is indistinguishable from a
wrong one.

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
current conditions degrade to the AROME current hour. If no source is
available at all, `_async_update_data` raises `UpdateFailed`.

## Dependencies
- `GeoSphereForecastCoordinator` — injected into the current coordinator's
  constructor to supply AROME fallback values (`hourly`, `current`, `snow_limit`,
  `weather_symbol`).
- INCA analysis and nowcast datasets — see [DATASETS.md](DATASETS.md).

## Design Decisions
- The current coordinator holds a direct reference to the forecast coordinator
  rather than sharing a store — a deliberate simplification for two/three
  coordinators.
- Preferring INCA analysis over the nowcast for thermodynamics/wind was a
  measured decision (v0.6.0).
- **The nowcast does not back `precipitation_1h`** (v0.12.0). Summing its `rr`
  buckets looks like a free hourly total, but the endpoint serves one model run
  clamped to that run's own t0, published ~25-35 min after the analysis it is
  stamped for. Measured 2026-09-11: an unbounded request returns a single
  bucket at/before now, and an anchored one reaches only the current run's
  start — 2 buckets at 11:42Z, 3 at 05:33Z. The sum therefore covered 15-45 min
  and was reported as a full hour, under-reporting by up to 4× on exactly the
  degraded path it exists for. A true hour needs the t0 bucket of four
  consecutive runs (`forecast_offset=0..3`), four requests per location per
  update against an endpoint whose failures are both frequent and *correlated
  across locations* — so an outage would very likely take out every offset at
  once, leaving the reconstruction unavailable during precisely the gaps it
  exists to fill while costing 4x the requests the rest of the time. The field
  reports `unknown` instead. Measurements and their provenance in
  [DATASETS.md](DATASETS.md#forecast-datasets).

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
