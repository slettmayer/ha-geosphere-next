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
sensor entities, with a condition taken from GeoSphere's own weather symbol,
a stepped precipitation-probability estimate derived from the ensemble, a
thunderstorm outlook, and optional air quality.
Industry: meteorology / open-government weather data consumed by home automation.

### Data/event surfaces and audiences
This integration has no HTTP API of its own; its "surfaces" are the HA entities
it publishes and the external dataset API it consumes.

- **Home automation user (HA entities published)** — one `weather` entity
  (current state + hourly forecast, `weather.get_forecasts`) and a set of
  `sensor` entities, all grouped under one HA `SERVICE` device
  (`entity.py: device_info`). Current-condition sensors are backed by the current
  coordinator; five optional air-quality sensors by the air-quality coordinator.
  Some sensors are disabled-by-default diagnostics (CAPE, raw `pt` code,
  raw `sy` symbol code). The `precipitating` binary sensor reports whether
  precipitation is falling now, and the `precipitation_kind` sensor what is
  falling, both backed by the current coordinator. Five forecast-outlook entities — `wind_gust_max_1h`,
  `wind_gust_max_12h`, `cape_max_12h` (diagnostic, disabled by default),
  `next_thunderstorm`, and the `thunderstorm_expected_1h` binary sensor — are
  backed by the forecast coordinator: their data refreshes on its interval,
  while their `now`-anchored window is additionally re-evaluated at every full
  hour (`entity.py: HourBoundaryRefreshMixin`). Entity platforms:
  `weather.py`, `sensor.py`, `binary_sensor.py`.
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
| [FORECAST.md](FORECAST.md) | AROME hourly forecast, interval-parameter stamping, stepped precipitation probability, thunderstorm outlook |
| [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) | The INCA → nowcast → AROME merge and fallback chain |
| [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md) | HA condition strings mapped from GeoSphere's `sy` code, observations overriding it now |
| [AIR-QUALITY.md](AIR-QUALITY.md) | Optional WRF-Chem pollutants and the daily European AQI |

### Core concept catalog
| Concept | One-liner | Detail |
|---------|-----------|--------|
| **AROME forecast** | The code's name for the deterministic 1 km forecast (`nwp-v2-1h-1km`, the C-LAEF AlpeAdria control run); primary forecast + current fallback | [DATASETS.md](DATASETS.md) |
| **C-LAEF ensemble** | Probabilistic model; source of the precipitation percentiles and the ensemble storm signal | [FORECAST.md](FORECAST.md) |
| **INCA analysis** | 1 km observation-anchored hourly analysis; preferred current source | [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) |
| **INCA nowcast** | 1 km 15-min product; precipitation type/rate and gusts | [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) |
| **WRF-Chem** | 3 km chemical-weather forecast; pollutants + daily AQI | [AIR-QUALITY.md](AIR-QUALITY.md) |
| **CurrentConditions** | Merged current-state record consumed by the weather entity and sensors | [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md) |
| **HourlyForecast / ForecastData** | Processed AROME(+ensemble) hourly output | [FORECAST.md](FORECAST.md) |
| **Condition string** | HA `ATTR_CONDITION_*` mapped from GeoSphere's `sy` code | [CONDITION-DERIVATION.md](CONDITION-DERIVATION.md) |

### Terminology glossary
- **p10 / p50 / p90** — C-LAEF ensemble percentiles per hour. Used: the
  precipitation ones (`tp_p10` … `tp_p90`, kg m⁻²) and `cape_p90` (J/kg); no
  member counts are published.
- **Stepped precipitation probability** — an estimate this integration derives,
  in {0, 30, 70, 95}%: the midpoint of the range implied by which percentile
  first exceeds 0.1 mm. GeoSphere publishes no probability.
- **Snow limit (`snowlmt`)** — AROME-forecast altitude (m) of the rain/snow
  transition.
- **CAPE** — Convective Available Potential Energy (J/kg). The deterministic
  value is diagnostic only; the ensemble's `cape_p90` ≥ 1000 J/kg (with
  precipitation) is one of the two thunderstorm-outlook signals.
- **European Air Quality Index** — EEA 1–6 scale (1 very good … 6 very poor).
- **`tp` / `sf`** — AROME precipitation / snowfall per hour (kg m⁻² = mm),
  each covering the hour *ending* at its stamp.
- **`pt` (precipitation type)** — nowcast code: 1 rain, 3 freezing rain, 5 snow,
  7 rain and snow, 255 none. Confirmed by GeoSphere, not in `/metadata`.
- **`sy` (weather symbol)** — GeoSphere's weather-symbol code (1–32, table
  published for `nwp-v1`, assumed for `nwp-v2`); the source of the HA
  condition and of thunder. Also a disabled diagnostic sensor.
- **Grid/point sampling** — the API returns the nearest grid-cell centre
  (`grid_latitude` / `grid_longitude`), distinct from the requested point.
- **`has_nowcast`** — capability flag set at config time; false outside Austria.

## Dependencies
- GeoSphere Austria Dataset API (sole external data source, CC BY 4.0).
- `astral` for solar elevation (day/night classification).

## Design Decisions
- GeoSphere's `sy` classification over our own thresholds for the condition;
  observations override it for what is falling now.
- "Primary must succeed, secondary degrades" — AROME/`chem` failures raise
  `UpdateFailed`; ensemble/AQI/nowcast failures degrade gracefully.
- Hourly-only forecast (no daily) — a deliberate HA-frontend-driven product
  decision.

## Known Risks
- Per-concept risks live in the owning sub-file — see [DATASETS.md](DATASETS.md)
  for the `sy` table assumed equal on `nwp-v2`, the `pt` table's source, and
  versioned resource IDs.

## Extension Guidelines
- Add a new domain concept as a new file here and index it in
  [README.md](README.md) and the sub-file table above.
- Keep business language in these docs; name concrete routes/entities only in
  this "surfaces and audiences" section.
