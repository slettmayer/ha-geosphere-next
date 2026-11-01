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
  `cape` (J/kg), `sy` (GeoSphere's weather-symbol code, which the HA
  condition is mapped from — see [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md)).

  Each parameter is either instantaneous at its stamp or covers the interval
  *ending* at it, and which is decided by measurement, not by name: requested
  from the run's own t0, an interval parameter is `null` at index 0
  (measured 2026-11-01). `10fg`, `tp` and `sf` are interval-ending; `2t`, `2r`,
  `10u`/`10v`, `tcc`, `cape` and `snowlmt` are instantaneous. `sy` is `null`
  at t0 as well: its precipitation codes follow `tp` at the same stamp (the
  interval ending there) and its cloud classes bin `tcc` at that stamp, so it
  is read one stamp on, like `tp` — see
  [The `sy` code table on nwp-v2](#the-sy-code-table-on-nwp-v2). The dataset
  also publishes `msl`, `pt` (a precipitation-type code
  distinct from the nowcast's), `rain`, `ssrd` and `sund`, which are not
  requested. See [FORECAST.md](FORECAST.md) for how each stamping is read.

  There is no convective inhibition, no 2 m min/max temperature and no
  run-accumulated series in this dataset. Thunder comes from the `sy` code
  (and, for the outlook, from the ensemble) — see
  [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md) and
  [FORECAST.md](FORECAST.md#thunderstorm-outlook).

  The dataset declares CAPE's unit as `m2 s-2`, which is dimensionally
  identical to J/kg, so the `J/kg` label this integration uses is numerically
  correct.
- **C-LAEF ensemble** — `("forecast", "ensemble-v2-1h-1km")`. Probabilistic
  companion on the same 1 km grid, reruns every 3 h, 61 hourly stamps. It
  publishes p10/p50/p90 percentiles of most deterministic parameters — no
  member counts or true wet-fraction. Requested (`ENSEMBLE_PARAMETERS`):
  `tp_p10`, `tp_p50`, `tp_p90` (kg m⁻²), per-hour amounts for the interval
  ending at their stamp like `tp` (`null` at t0); and `cape_p90` (J/kg,
  declared `m2 s-2`), which has a value at t0 and is instantaneous like
  `cape` (measured 2026-11-01 on the 03:00Z run). The tp percentiles feed the
  stepped precipitation probability — an estimate this integration derives,
  not a probability GeoSphere publishes — and `tp_p90` with `cape_p90` the
  ensemble branch of the thunderstorm outlook.
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

### The `sy` code table on nwp-v2

GeoSphere published the `sy` table for `nwp-v1` in
[dataset-api-docs#30](https://github.com/Geosphere-Austria/dataset-api-docs/issues/30#issuecomment-2042539848)
(see [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md) for the table). For
`nwp-v2` the integration assumes the same table. The evidence, measured
2026-11-01 on the 06:00Z run through the grid endpoint
(`/grid/forecast/nwp-v2-1h-1km`, NetCDF, the full 945 × 1300 domain):

- **Coverage.** `sy` at all 60 stamps of the run (73.7 M values): cloud 1–5
  64.9 M, rain 8–10/17–19 6.97 M, sleet 11–13/20–22 1.24 M, snow
  14–16/23–25 0.55 M, thunder 26–32 5,560. Codes 6, 7, 25, 30 and 32 never
  occurred; neither did 6–7 in 8 night stamps of an older run.
- **Cloud classes** (6 stamps, 7.37 M points, each compared at its own stamp
  and the one before): codes 1–5 bin `tcc` at their own stamp exactly — 1:
  0–10 %, 2: 10–30 %, 3: 30–60 %, 4: 60–90 %, 5: 90–100 % — while `tcc` at the
  previous stamp spans 0–100 % for every code.
- **Precipitation classes** (893,586 coded points): every one has `tp` ≥ 0.1 mm
  at its own stamp; at the previous stamp only 38–100 % do, depending on the
  code. Cloud-coded points with `tp` ≥ 0.1 mm at their stamp: 0.04 %, all at
  the 0.1 mm boundary. Rain intensity bins `tp` exactly: 8/17 0.1–1 mm,
  9/18 1–5 mm, 10/19 ≥ 5 mm; the sleet and snow intensities overlap more
  loosely (e.g. code 12 spans 0.1–7.6 mm). So the
  precipitation classes describe the interval *ending* at their stamp, which
  is why a forecast row reads `sy` one stamp on (see
  [FORECAST.md](FORECAST.md#hourly-processing)).
- **Kind.** Rain codes: `sf` = 0, median `2t` 6.8–8.7 °C. Snow codes: `sf`/`tp`
  median 0.78–0.95, median `2t` −1.2 °C. Sleet codes: median `2t` 2.3–5.3 °C,
  `sf` > 0 at ~40 %.
- **Thunder.** All 26–32 points are wet (`tp` ≥ 0.1 mm) and lie over northern
  Italy, the Adriatic and the southern Alps; their CAPE has a median of
  159 J/kg, a 90th percentile of 241 and a maximum of 475. No point in the
  sample reached 1000 J/kg, so GeoSphere's thunder diagnosis is not a CAPE
  threshold. Code 31 (thunder with snow) sits at a median −1.3 °C with
  snowfall. Code 29 (thunder with sleet) is warmer than the sleet codes
  (median 8.1 °C, `sf` > 0 at 10 %), the one class that matches its label
  only loosely.
- **Fog.** Of 228,338 fog-like points (`2r` ≥ 98 %, 10 m wind < 2 m/s), 60 %
  carried code 5 and 25 % code 8; none carried 6 or 7.

### Domain coverage

The forecast/ensemble/WRF-Chem grids cover Austria and the surrounding
region — for the forecast and ensemble, latitude 43.0–51.5° and longitude
5.03–22.57° (`bbox_outer` in the dataset metadata); INCA analysis and nowcast are
Austria-only. A point outside a grid is answered with HTTP 400 and a `detail`
of "… is outside of dataset bounds!", which the client maps to
`GeoSphereOutOfDomainError`; nothing in the integration hard-codes the bounds. The config flow probes both AROME
and nowcast at setup to decide `has_nowcast` — see
[CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).

### Publication latency

A run's `reference_time` is the hour it is stamped for, not the moment it
becomes available — GeoSphere computes it well afterwards, and the lag is not
published. Measured from the datasets' `/metadata` (`last_forecast_reftime`),
polled every 5 min on 2026-11-01 from 08:49Z to 09:19Z:

| Dataset | Cadence | Newest `reference_time` | Implied lag |
|---|---|---|---|
| AROME (`nwp-v2-1h-1km`) | 3 h | `2026-11-01T03:00Z` throughout | 06:00Z run not yet out at 09:19Z → >3 h |
| C-LAEF ensemble (`ensemble-v2-1h-1km`) | 3 h | `2026-11-01T03:00Z` throughout | 06:00Z run not yet out at 09:19Z → >3 h |

The lag is longer than the cadence, so a run is already past its own cadence
by the time it can be fetched. For the nowcast (15 min cadence) the lag was
~30 min and WRF-Chem (daily) publishes its 00:00Z run the same morning
(measured 2026-08-17).

This is why fetches are gated on the cadence rather than scheduled against the
run hours — see [FORECAST.md](FORECAST.md#run-gating).

## Dependencies
- GeoSphere Austria Dataset API — `https://dataset.api.hub.geosphere.at/v1`.
- Request budget: 5 req/s, 240 req/h (no key). Default polling stays well under
  it. The forecast coordinator skips AROME and ensemble requests whose run
  cannot have been superseded, but because both publish later than their 3 h
  cadence (see [Publication latency](#publication-latency)) that gate rarely
  holds, so expect up to two requests per forecast tick (~4 req/h at the
  default 30 min), plus the current coordinator's ~4–6 req/h and ~2 req/h with
  air quality enabled.

## Design Decisions
- Datasets are `(mode, resource_id)` tuples so `get_timeseries(*DATASET_X, ...)`
  stays uniform across all six.
- Only three ensemble percentiles are published, which forces the stepped
  precipitation-probability estimate — see [FORECAST.md](FORECAST.md).

## Known Risks
- The `sy` table is published for `nwp-v1` only; the integration assumes
  `nwp-v2` uses the same one. Measured evidence supports it for every class
  observed (see [The `sy` code table on nwp-v2](#the-sy-code-table-on-nwp-v2)),
  but fog (6–7) and codes 25, 30 and 32 were never observed. If `nwp-v2` emits
  no fog codes, `fog` never appears. Neither table is in `/metadata`; the
  nowcast `pt` table GeoSphere confirmed on request — see
  [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- Dataset resource IDs are versioned (`-v1-`, `-v2-`); a GeoSphere version bump
  would require updating `const.py`.

## Extension Guidelines
- To add a parameter, extend the matching `*_PARAMETERS` tuple in `const.py` and
  read it in the owning coordinator via `response.value_at(name, index)`.
- To add a dataset, declare a new `DATASET_*` tuple and fetch it in the relevant
  coordinator; keep the `(mode, resource_id)` shape.
