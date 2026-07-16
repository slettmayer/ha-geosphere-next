# Domain Overview

## Purpose
Index and entry point to the meteorological domain: the GeoSphere datasets, the
derived values, and the Home Assistant entities this integration produces.

## Responsibilities
- Domain classification, the concept catalog, the glossary, cross-cutting
  decisions, and the sub-file index.

## Non-Responsibilities
- Per-concept detail (datasets, merging, derivation, air quality) — lives in the
  sub-files. Implementation, build, and testing — see [../tech/README.md](../tech/README.md).

## Overview

### Domain classification
A Home Assistant custom integration that samples GeoSphere Austria's gridded
meteorological datasets at any coordinate within the supported dataset domains
(AROME across Austria and the surrounding Alpine region; current conditions
Austria-only) — not just weather stations — and turns them into HA weather and
sensor entities, with a physically-derived condition, a
stepped ensemble-backed precipitation probability, and optional air quality.
Industry: meteorology / open-government weather data consumed by home automation.

### Data/event surfaces and audiences
This integration has no HTTP API of its own; its "surfaces" are the HA entities
it publishes and the external dataset API it consumes.

- **Home automation user (HA entities published)** — one `weather` entity
  (current state + hourly forecast, `weather.get_forecasts`) and a set of
  `sensor` entities, all grouped under one HA `SERVICE` device
  (`entity.py: device_info`). Current-condition sensors are backed by the current
  coordinator; five optional air-quality sensors by the air-quality coordinator.
  Some sensors are disabled-by-default diagnostics (CAPE, raw `pt` code, raw `sy`
  symbol code). Entity platforms: `weather.py`, `sensor.py`.
- **Config/options surface (HA config flow)** — location onboarding and options
  (update intervals, air-quality toggle) via `config_flow.py`. See
  [../tech/ARCHITECTURE.md](../tech/ARCHITECTURE.md).
- **External data source (consumed)** — the GeoSphere Austria Dataset API
  (`https://dataset.api.hub.geosphere.at/v1`), a public no-key GeoJSON
  point-timeseries API. Six datasets are consumed; see [DATASETS.md](DATASETS.md).

### Sub-file index
| Doc | Covers |
|-----|--------|
| [DATASETS.md](DATASETS.md) | The six GeoSphere datasets: resolution, cadence, parameters |
| [FORECAST.md](FORECAST.md) | AROME hourly forecast, accumulation differencing, stepped precipitation probability |
| [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) | The INCA → nowcast → AROME merge and fallback chain |
| [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md) | HA condition strings derived from physical parameters |
| [AIR-QUALITY.md](AIR-QUALITY.md) | Optional WRF-Chem pollutants and the daily European AQI |

### Core concept catalog
| Concept | One-liner | Detail |
|---------|-----------|--------|
| **AROME forecast** | Deterministic 2.5 km NWP model; primary forecast + current fallback | [DATASETS.md](DATASETS.md) |
| **C-LAEF ensemble** | Probabilistic model; source of the precipitation percentiles | [FORECAST.md](FORECAST.md) |
| **INCA analysis** | 1 km observation-anchored hourly analysis; preferred current source | [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) |
| **INCA nowcast** | 1 km 15-min product; precipitation type/rate and gusts | [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) |
| **WRF-Chem** | 3 km chemical-weather forecast; pollutants + daily AQI | [AIR-QUALITY.md](AIR-QUALITY.md) |
| **CurrentConditions** | Merged current-state record consumed by the weather entity and sensors | [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) |
| **HourlyForecast / ForecastData** | Processed AROME(+ensemble) hourly output | [FORECAST.md](FORECAST.md) |
| **Condition string** | HA `ATTR_CONDITION_*` derived from physical parameters | [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md) |

### Terminology glossary
- **p10 / p50 / p90** — C-LAEF ensemble precipitation percentiles per hour
  (kg m⁻²); the only ensemble output published (no member counts).
- **Stepped precipitation probability** — derived value in {0, 30, 70, 95}%, the
  midpoint of the range implied by which percentile first exceeds 0.1 mm.
- **Snow limit (`snowlmt`)** — AROME-forecast altitude (m) of the rain/snow
  transition.
- **CAPE** — Convective Available Potential Energy (J/kg); thunder/lightning
  signal (threshold 1000 J/kg).
- **European Air Quality Index** — EEA 1–6 scale (1 very good … 6 very poor).
- **`rr_acc` / `snow_acc`** — run-accumulated AROME totals; hourly values via
  differencing.
- **`pt` (precipitation type)** — undocumented nowcast code; only 255 = none is
  trusted.
- **`sy` (weather symbol)** — GeoSphere's undocumented symbol code; exposed only
  as a diagnostic sensor.
- **Grid/point sampling** — the API returns the nearest grid-cell centre
  (`grid_latitude` / `grid_longitude`), distinct from the requested point.
- **`has_nowcast`** — capability flag set at config time; false outside Austria.

## Dependencies
- GeoSphere Austria Dataset API (sole external data source, CC BY 4.0).
- `astral` for solar elevation (day/night classification).

## Design Decisions
- Physical-parameter condition derivation over the proprietary `sy` code.
- "Primary must succeed, secondary degrades" — AROME/`chem` failures raise
  `UpdateFailed`; ensemble/AQI/nowcast failures degrade gracefully.
- Hourly-only forecast (no daily) — a deliberate HA-frontend-driven product
  decision.

## Known Risks
- Per-concept risks live in the owning sub-file — see [DATASETS.md](DATASETS.md)
  for the undocumented code tables (`sy`, `pt`) and versioned resource IDs.

## Extension Guidelines
- Add a new domain concept as a new file here and index it in
  [README.md](README.md) and the sub-file table above.
- Keep business language in these docs; name concrete routes/entities only in
  this "surfaces and audiences" section.
