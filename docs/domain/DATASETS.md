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
  and the ultimate current-conditions fallback (its hour covering now). Parameters
  (`AROME_PARAMETERS`): `t2m`, `mnt2m`, `mxt2m` (temp / min / max), `rh2m`
  (humidity), `u10m` / `v10m` (wind components), `ugust` / `vgust` (gust
  components), `tcc` (cloud cover, 0–1), `rr_acc` / `snow_acc` (run-accumulated
  precipitation / snow), `snowlmt` (snow limit, m), `grad` (global radiation),
  `cape` (J/kg), `cin` (convective inhibition, J/kg), `sy` (proprietary
  weather-symbol code).

  AROME publishes `cin` in J/kg as a negative quantity; the observed range in
  the recorded fixture is −49.5 to 0.0, where 0.0 means uncapped and more
  negative means a stronger lid. It gates the thunder decision in
  [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md) — see that doc for the
  threshold.

  That threshold (`CAP_CIN_JKG = 50.0`, i.e. thunder needs `cin > -50`) sits
  just outside every value in the fixture: the strongest recorded lid is
  −49.5. On this sample the gate therefore suppresses nothing, and it is
  exercised only by synthetic test values. 50 J/kg is a defensible boundary
  for weak inhibition and a single 57-hour July recording is not evidence the
  threshold is wrong, but real-world discrimination is unconfirmed. A fixture
  recorded during a genuinely capped situation (a capped spring/summer
  airmass, `cin` well below −50) would be worth capturing.

  AROME declares CAPE's unit as `m2 s-2`, which is dimensionally identical to
  J/kg, so the `J/kg` label this integration uses is numerically correct.
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
- The `sy` weather-symbol and nowcast `pt` code tables are undocumented and
  proprietary; the integration never relies on their exact semantics.
- Dataset resource IDs are versioned (`-v1-`, `-v2-`); a GeoSphere version bump
  would require updating `const.py`.

## Extension Guidelines
- To add a parameter, extend the matching `*_PARAMETERS` tuple in `const.py` and
  read it in the owning coordinator via `response.value_at(name, index)`.
- To add a dataset, declare a new `DATASET_*` tuple and fetch it in the relevant
  coordinator; keep the `(mode, resource_id)` shape.
