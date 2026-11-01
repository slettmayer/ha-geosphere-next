# GeoSphere Datasets

## Purpose
Catalogue the six GeoSphere Austria Dataset API datasets this integration samples,
their resolution and model-run cadence, and the parameters requested from each.

## Responsibilities
- Define each dataset's `(mode, resource_id)` identifier, grid resolution, and refresh cadence.
- List the parameters requested per dataset and what they map to.
- Explain which coordinator consumes each dataset.

## Non-Responsibilities
- How current conditions merge multiple datasets — see [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- How the forecast is processed — see [FORECAST.md](FORECAST.md).
- How the HTTP client and GeoJSON parsing work — see [../tech/ARCHITECTURE.md](../tech/ARCHITECTURE.md).

## Overview

All datasets are declared as `(mode, resource_id)` tuples in
`custom_components/geosphere_next/const.py` and fetched through the single
`GeoSphereApiClient.get_timeseries` point-timeseries call. The API returns
GeoJSON; no API key is required. The actual sampled grid-cell centre is returned
as `grid_latitude` / `grid_longitude`, which differs from the requested point.

### Forecast datasets

- **AROME** (the code's name for the deterministic forecast) —
  `("forecast", "nwp-v2-1h-1km")`. The deterministic control run of the C-LAEF
  AlpeAdria ensemble, 1 km grid, reruns every 3 h, 61 hourly stamps from the
  run's t0. The primary forecast source and the ultimate current-conditions
  fallback (its hour covering now). Parameters (`AROME_PARAMETERS`): `2t`
  (temperature, °C), `2r` (humidity, %), `10u` / `10v` (wind components),
  `10fg` (peak 10 m gust, m/s), `tcc` (cloud cover, **%**, 0–100), `tp` / `sf`
  (per-hour precipitation / snowfall, kg m⁻²), `snowlmt` (snow limit, m),
  `cape` (J/kg), `sy` (proprietary weather-symbol code).

  Each parameter is either instantaneous at its stamp or covers the interval
  *ending* at it, and which is decided by measurement, not by name: requested
  from the run's own t0, an interval parameter is `null` at index 0
  (measured 2026-11-01). `10fg`, `tp` and `sf` are interval-ending; `2t`, `2r`,
  `10u`/`10v`, `tcc`, `cape` and `snowlmt` are instantaneous. `sy` is `null`
  at t0 as well, but its cloud classes (codes 1–5) bin exactly on `tcc` at
  its own stamp (1: 0–10 %, 2: 11–30 %, 3: 32–60 %, 4: 61–90 %, 5: 90–100 %),
  so it is read at the stamp; its precipitation codes follow `tp` at the same
  stamp. The dataset also publishes `msl`, `pt` (a precipitation-type code
  distinct from the nowcast's), `rain`, `ssrd` and `sund`, which are not
  requested. See [FORECAST.md](FORECAST.md) for how each stamping is read.

  There is no convective inhibition, no 2 m min/max temperature and no
  run-accumulated series in this dataset. Thunder is therefore decided on CAPE
  alone — see [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md).

  The dataset declares CAPE's unit as `m2 s-2`, which is dimensionally
  identical to J/kg, so the `J/kg` label this integration uses is numerically
  correct.
- **C-LAEF ensemble** — `("forecast", "ensemble-v2-1h-1km")`. Probabilistic
  companion on the same 1 km grid, reruns every 3 h, 61 hourly stamps. Of its
  percentile parameters only the precipitation ones are requested
  (`ENSEMBLE_PARAMETERS`: `tp_p10`, `tp_p50`, `tp_p90`, kg m⁻²) — no member
  counts or true wet-fraction. Like `tp` they are per-hour amounts for the
  interval ending at their stamp (`null` at t0). Consumed only to derive the
  stepped precipitation probability.
- **INCA nowcast** — `("forecast", "nowcast-v1-15min-1km")`. 1 km, 15-min cadence,
  Austria-only grid. Parameters (`NOWCAST_PARAMETERS`): `t2m`, `td` (dew point),
  `rh2m`, `rr` (15-min precipitation), `pt` (precipitation-type code), `dd` (wind
  direction), `ff` (wind speed), `fx` (wind gust). Supplies precipitation
  type/rate and gusts, and is a fallback for INCA-analysis fields.
  Requested with a `start` of `NOWCAST_LOOKBACK` before the 15-min floor of
  `now`: unbounded, the response begins at the bucket covering `now` and so
  carries exactly one stamp at or before it. Even anchored it reaches no
  further than the serving run's own t0, which trails by ~25-35 min — the
  reason `precipitation_1h` is not reconstructed from it (see
  [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md)). An undocumented
  `forecast_offset` (0-5, per the dataset metadata's
  `available_forecast_reftimes`) reaches older runs and is not used;
  availability is the reason. Measured 2026-09-09/11 — ~48 h, all three of the
  author's locations, on the **pre-0.12.0 build** (the `start` anchor changes
  which buckets come back, not whether the request succeeds) — the nowcast
  yielded no value in 11 / 11 / 10 episodes, roughly one every four hours per
  location, each clearing within a poll or two. The dropouts **coincide**: all
  three locations failed within ~75 s of each other on three occasions, two of
  three on four more. Three coordinates and three separate requests, so that
  points at the endpoint rather than at any one point query. Four
  `forecast_offset` requests are therefore very unlikely to be independent
  draws against that rate — not tested directly, but they are four calls to
  the same endpoint inside the same window. See
  [#35](https://github.com/slettmayer/ha-geosphere-next/issues/35).
- **WRF-Chem** — `("forecast", "chem-v2-1h-3km")`. Chemical-weather forecast,
  3 km grid, one model run per day, ~73 h hourly. Parameters (`CHEM_PARAMETERS`):
  `no2surf`, `o3surf`, `pm10surf`, `pm25surf` (µg/m³). Optional.
- **WRF-Chem AQI** — `("forecast", "chem_aqi-v1-1d-3km")`. Daily European Air
  Quality Index, 3 km grid. Single parameter (`CHEM_AQI_PARAMETERS`: `aqi`, 1–6).
  Optional.

### Analysis dataset

- **INCA analysis** — `("historical", "inca-v1-1h-1km")`. 1 km, hourly,
  observation-anchored analysis, Austria-only grid. Note the `historical` mode.
  Parameters (`INCA_PARAMETERS`): `T2M`, `TD2M`, `RH2M`, `RR` (1 h precipitation),
  `P0` (surface pressure, Pa), `GL` (global radiation), `UU` / `VV` (wind
  components). The preferred source for current thermodynamic fields, wind, MSL
  pressure, and 1 h precipitation. Uppercase parameter names distinguish it from
  the nowcast's lowercase names.

### Domain coverage

The forecast/ensemble/WRF-Chem grids cover Austria and the surrounding
region — for the forecast and ensemble, latitude 43.0–51.5° and longitude
5.0–22.6° (`bbox_outer` in the dataset metadata); INCA analysis and nowcast are
Austria-only. A point outside a grid is answered with HTTP 400 and a `detail`
of "… is outside of dataset bounds!", which the client maps to
`GeoSphereOutOfDomainError`; nothing in the integration hard-codes the bounds. The config flow probes both AROME
and nowcast at setup to decide `has_nowcast` — see
[CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).

### Publication latency

A run's `reference_time` is the hour it is stamped for, not the moment it
becomes available — GeoSphere computes it well afterwards, and the lag is not
published. Measured at 47.07/15.44 on 2026-08-17 05:02Z:

| Dataset | Cadence | Newest `reference_time` | Implied lag |
|---|---|---|---|
| AROME | 3 h | `2026-08-17T00:00Z` | 03:00Z run not yet out → >2 h |
| C-LAEF ensemble | 12 h | `2026-08-16T12:00Z` | 00:00Z run not yet out → >5 h |
| INCA nowcast | 15 min | `2026-08-17T04:30Z` | ~30 min |
| WRF-Chem | 1 d | `2026-08-17T00:00Z` | — |

This is why fetches are gated on the cadence rather than scheduled against the
run hours — see [FORECAST.md](FORECAST.md#run-gating).

## Dependencies
- GeoSphere Austria Dataset API — `https://dataset.api.hub.geosphere.at/v1`.
- Request budget: 5 req/s, 240 req/h (no key). Default polling stays well under
  it: the forecast coordinator skips AROME and ensemble requests whose run
  cannot have been superseded, so it costs ~2 req/h at rest and up to ~4 req/h
  while hunting for a new run, plus the current coordinator's ~4–6 req/h and
  ~2 req/h with air quality enabled.

## Design Decisions
- Datasets are `(mode, resource_id)` tuples so `get_timeseries(*DATASET_X, ...)`
  stays uniform across all six.
- Only three ensemble percentiles are published, which forces the stepped
  precipitation-probability model — see [FORECAST.md](FORECAST.md).

## Known Risks
- The `sy` weather-symbol code table is undocumented and proprietary; the
  integration never relies on its exact semantics. The nowcast `pt` table is
  not in `/metadata` either, but GeoSphere confirmed it on request — see
  [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- Dataset resource IDs are versioned (`-v1-`, `-v2-`); a GeoSphere version bump
  would require updating `const.py`.

## Extension Guidelines
- To add a parameter, extend the matching `*_PARAMETERS` tuple in `const.py` and
  read it in the owning coordinator via `response.value_at(name, index)`.
- To add a dataset, declare a new `DATASET_*` tuple and fetch it in the relevant
  coordinator; keep the `(mode, resource_id)` shape.
