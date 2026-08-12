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
- **1 h precipitation**: INCA `RR`; if absent, sum the last four 15-min nowcast
  `rr` buckets at/before now.
- **Precipitation type / `is_precipitating`**: nowcast `pt` (255 = none).
- **Precipitation rate** (mm/h, feeds the condition): the matched nowcast `rr`
  bucket × `NOWCAST_BUCKETS_PER_HOUR`, else INCA's hourly `RR` where there is
  no nowcast at all. When `pt` says it *is* precipitating, the peak across the
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
