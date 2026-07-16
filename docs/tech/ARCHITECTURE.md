# Architecture

## Purpose
Describe the module layering, data flow, and key structural patterns of the
integration.

## Responsibilities
- Map each module to its responsibility.
- Describe the fetch → merge/derive → entity data flow.
- Document the coordinator, entity-description, and config-flow patterns.

## Non-Responsibilities
- Naming and code style — see [CONVENTIONS.md](CONVENTIONS.md).
- The meteorological meaning of the data — see [../domain/OVERVIEW.md](../domain/OVERVIEW.md).
- CI/CD — see [INFRASTRUCTURE.md](INFRASTRUCTURE.md).

## Overview

This is a standard Home Assistant integration skeleton with a clean internal
layered flow and an isolated pure-logic core. All code lives flat in
`custom_components/geosphere_next/` (no sub-packages).

### Layering

```
api.py        HTTP + GeoJSON parsing            (homeassistant-free)
models.py     dataclasses (data shapes)         (homeassistant-free)
condition.py  pure derivation + met. math       (homeassistant-free)
const.py      datasets, parameters, thresholds  (single source of truth)
   │
coordinator.py  fetch / cache / difference / merge  → model dataclasses
   │
entity.py / sensor.py / weather.py  HA platform surface
config_flow.py  onboarding + options
__init__.py     setup / unload / entity cleanup
diagnostics.py  redacted state dump
```

The `api.py` + `models.py` core is deliberately import-free of `homeassistant`
so it can become a standalone PyPI package later; `condition.py` is likewise pure
for testability (it duplicates HA's `ATTR_CONDITION_*` string literals rather
than importing them).

### Data flow

1. `__init__.async_setup_entry` builds the `GeoSphereApiClient`, then the forecast
   coordinator (first refresh), then the current coordinator (which receives the
   forecast coordinator), and optionally the air-quality coordinator. All are
   stored on `entry.runtime_data` (typed `GeoSphereNextData`).
2. Each coordinator's `_async_update_data` calls `client.get_timeseries(...)` per
   dataset, which parses GeoJSON into a `GeoSphereResponse`.
3. Coordinators `_process` / `_merge` responses into `ForecastData`,
   `CurrentConditions`, or `AirQualityData`, calling `condition.py` for derived
   values.
4. `weather.py` and `sensor.py` read `coordinator.data` and expose it as HA
   entities.

Detail on the merge chain lives in [../domain/CURRENT-CONDITIONS.md](../domain/CURRENT-CONDITIONS.md);
forecast processing in [../domain/FORECAST.md](../domain/FORECAST.md).

### Coordinators

Three `TimestampDataUpdateCoordinator[T]` subclasses, one per dataset shape:
- `GeoSphereForecastCoordinator[ForecastData]` — AROME + ensemble.
- `GeoSphereCurrentCoordinator[CurrentConditions]` — nowcast + INCA + AROME
  fallback; holds a direct reference to the forecast coordinator and caches INCA
  on the instance with a timestamp-based freshness policy.
- `GeoSphereAirQualityCoordinator[AirQualityData]` — WRF-Chem + AQI (optional).

Primary-dataset failures raise `UpdateFailed` (rate limits propagate
`retry_after`); secondary datasets (ensemble, AQI) are caught, logged at warning
level, and degrade gracefully.

### Entity-description pattern

Sensors use HA's idiomatic "one entity class + many descriptions" composition.
`SENSORS` / `AIR_QUALITY_SENSORS` are tuples of frozen
`SensorEntityDescription` subclasses carrying a `value_fn` (and `attributes_fn`
for air quality); a single `GeoSphereSensor` / `GeoSphereAirQualitySensor` class
reads `entity_description.value_fn(coordinator.data)`. All entities share one
`SERVICE` `DeviceInfo` from `entity.py`. Unique IDs: `{entry_id}` (weather),
`{entry_id}-{key}` (sensors).

### Config flow

`GeoSphereNextConfigFlow` (location picker) probes AROME (domain check) and the
nowcast (Austria check) to set `CONF_HAS_NOWCAST` in `entry.data`; unique ID is
`{lat:.4f}_{lon:.4f}`. `GeoSphereNextOptionsFlow` (`OptionsFlowWithReload`)
exposes the two interval sliders and the air-quality toggle. Toggling air quality
off triggers registry cleanup in `__init__._remove_air_quality_entities`.

## Dependencies
- Home Assistant coordinator/entity/config-entry APIs.
- The GeoSphere API via `api.py`.

## Design Decisions
- HA-free core (`api.py`, `models.py`, `condition.py`) for future extraction and
  testability.
- `const.py` is the single catalog for dataset tuples, parameter names, and every
  threshold/magic number (each named and commented with rationale).
- Coordinators wired directly (current holds forecast) rather than via a shared
  store — a simplification appropriate at this scale.
- Modern HA idioms: typed `ConfigEntry[GeoSphereNextData]` and `runtime_data`
  instead of `hass.data[DOMAIN]`.

## Known Risks
- `condition.py` duplicating HA condition literals could drift if HA renames a
  condition string.
- The current↔forecast coordinator coupling is intentional but must be preserved
  when refactoring.

## Extension Guidelines
- Add a new platform by creating its file and appending to `PLATFORMS` in
  `__init__.py`.
- Add a new data source by declaring a `DATASET_*` tuple in `const.py` and
  consuming it in the owning coordinator.
- Keep `api.py` / `models.py` / `condition.py` free of `homeassistant` imports.
