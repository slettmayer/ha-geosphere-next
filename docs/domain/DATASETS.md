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

- **AROME** — `("forecast", "nwp-v1-1h-2500m")`. Deterministic NWP model, 2.5 km
  grid, model reruns every 3 h, ~60 h hourly horizon. The primary forecast source
  and the ultimate current-conditions fallback (its "step 0" hour). Parameters
  (`AROME_PARAMETERS`): `t2m`, `mnt2m`, `mxt2m` (temp / min / max), `rh2m`
  (humidity), `u10m` / `v10m` (wind components), `ugust` / `vgust` (gust
  components), `tcc` (cloud cover, 0–1), `rr_acc` / `snow_acc` (run-accumulated
  precipitation / snow), `snowlmt` (snow limit, m), `grad` (global radiation),
  `cape` (J/kg), `sy` (proprietary weather-symbol code).
- **C-LAEF ensemble** — `("forecast", "ensemble-v1-1h-2500m")`. Probabilistic
  companion, 2.5 km-class grid, model reruns every 12 h, ~61 h length. Publishes
  only three precipitation percentiles per hour (`ENSEMBLE_PARAMETERS`:
  `rr_p10`, `rr_p50`, `rr_p90`, kg m⁻²) — no member counts or true wet-fraction.
  Consumed only to derive the stepped precipitation probability.
- **INCA nowcast** — `("forecast", "nowcast-v1-15min-1km")`. 1 km, 15-min cadence,
  Austria-only grid. Parameters (`NOWCAST_PARAMETERS`): `t2m`, `td` (dew point),
  `rh2m`, `rr` (15-min precipitation), `pt` (precipitation-type code), `dd` (wind
  direction), `ff` (wind speed), `fx` (wind gust). Supplies precipitation
  type/rate and gusts, and is a fallback for INCA-analysis fields.
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

The AROME/ensemble/WRF-Chem grids cover Austria and the surrounding region;
INCA analysis and nowcast are Austria-only. The config flow probes both AROME
and nowcast at setup to decide `has_nowcast` — see
[CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).

## Dependencies
- GeoSphere Austria Dataset API — `https://dataset.api.hub.geosphere.at/v1`.
- Request budget: 5 req/s, 240 req/h (no key). Default polling uses ~9 req/h,
  ~11 with air quality enabled.

## Design Decisions
- Datasets are `(mode, resource_id)` tuples so `get_timeseries(*DATASET_X, ...)`
  stays uniform across all six.
- Only three ensemble percentiles are published, which forces the stepped
  precipitation-probability model — see [FORECAST.md](FORECAST.md).

## Known Risks
- The `sy` weather-symbol and nowcast `pt` code tables are undocumented and
  proprietary; the integration never relies on their exact semantics.
- Dataset resource IDs are versioned (`-v1-`, `-v2-`); a GeoSphere version bump
  would require updating `const.py`.

## Extension Guidelines
- To add a parameter, extend the matching `*_PARAMETERS` tuple in `const.py` and
  read it in the owning coordinator via `response.value_at(name, index)`.
- To add a dataset, declare a new `DATASET_*` tuple and fetch it in the relevant
  coordinator; keep the `(mode, resource_id)` shape.
