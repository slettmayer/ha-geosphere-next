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
outlook.py    forecast-window scans (gust/storm) (homeassistant-free)
const.py      datasets, parameters, thresholds  (single source of truth)
   │
coordinator.py  fetch / cache / difference / merge  → model dataclasses
   │
entity.py / sensor.py / binary_sensor.py / weather.py  HA platform surface
config_flow.py  onboarding + options
__init__.py     setup / unload / entity cleanup
diagnostics.py  redacted state dump
```

The `api.py` + `models.py` core is deliberately import-free of `homeassistant`
so it can become a standalone PyPI package later; `condition.py` and
`outlook.py` are likewise pure for testability (`condition.py` duplicates HA's
`ATTR_CONDITION_*` string literals rather than importing them, and `outlook.py`
depends only on `condition.py`, `const.py`, and `models.py`).

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
- `GeoSphereForecastCoordinator[ForecastData]` — AROME + ensemble; caches both
  responses on the instance and re-fetches each only once its model rerun
  cadence has elapsed (`_run_is_current`), while still re-processing every
  cycle because `_process` depends on `now`.
- `GeoSphereCurrentCoordinator[CurrentConditions]` — nowcast + INCA + AROME
  fallback; holds a direct reference to the forecast coordinator and caches INCA
  on the instance with a timestamp-based freshness policy.
- `GeoSphereAirQualityCoordinator[AirQualityData]` — WRF-Chem + AQI (optional).

### Failure handling

Two layers, and the lower one absorbs most of what the upper one used to see.

`GeoSphereApiClient.get_timeseries` retries transient faults — anything under
`GeoSphereTransientError`, i.e. 5xx responses and connection errors including
timeouts — up to `MAX_ATTEMPTS` (3) times, waiting `RETRY_BASE_DELAY` doubled
per attempt and spread by `RETRY_JITTER` in both directions. The retry sits in
the client rather than the coordinators on purpose: a fault that clears on a
later attempt is never *observed* upstream, so nothing logs it, nothing falls
back, and no entity is blanked for a request that was about to succeed. Only
the final attempt's failure propagates. A 429, every 4xx, and a 200 whose body
is unusable propagate on the first attempt without retry, spending none of the
budget: the 429 means the request budget is already gone, a 4xx would be
rejected identically three times, and an unusable body raises
`GeoSphereApiError`.

The split is response-level vs transport-level, not `aiohttp` class: a
`ClientResponseError` (typically `ContentTypeError`) means the server answered
and the answer is unusable, so it is reported rather than retried, while a
fault mid-body (`ClientPayloadError`, `ServerDisconnectedError`) is a transport
failure and stays retryable. A 200 whose body will not decode raises
`GeoSphereApiError` too — the `ValueError` it produces is not an
`aiohttp.ClientError` and would otherwise escape the hierarchy altogether.

What retrying costs: a failing dataset now issues `MAX_ATTEMPTS` requests
instead of one, so a sustained outage triples that dataset's request rate
against the 240 req/h budget, and a single `get_timeseries` can block for
roughly `MAX_ATTEMPTS × REQUEST_TIMEOUT` plus backoff (~94 s) instead of 30 s.
Both are bounded and well inside the poll intervals, but they are the price of
not surfacing a fault that clears by itself.

Above that, primary-dataset failures raise `UpdateFailed` (rate limits
propagate `retry_after`); secondary datasets (ensemble, AQI) are caught, logged
at warning level, and degrade gracefully.

### Entity-description pattern

Sensors use HA's idiomatic "one entity class + many descriptions" composition.
`SENSORS` / `AIR_QUALITY_SENSORS` are tuples of frozen
`SensorEntityDescription` subclasses carrying a `value_fn` (and `attributes_fn`
for air quality); a single `GeoSphereSensor` / `GeoSphereAirQualitySensor` class
reads `entity_description.value_fn(coordinator.data)`. All entities share one
`SERVICE` `DeviceInfo` from `entity.py`. Unique IDs: `{entry_id}` (weather),
`{entry_id}-{key}` (sensors).

`binary_sensor.py` holds two groups on two coordinators: `BINARY_SENSORS`
(forecast-outlook, `GeoSphereBinarySensor`) and `CURRENT_BINARY_SENSORS`
(current conditions, `GeoSphereCurrentBinarySensor`) — the latter is a plain
`value_fn(data)` on the current coordinator, with no hour-boundary refresh.

The forecast-outlook entities (`OUTLOOK_SENSORS` in `sensor.py`,
`BINARY_SENSORS` in `binary_sensor.py`) follow the same shape but take a
`value_fn(data, now)` and delegate to `outlook.py`. Because their answers are
anchored on `now` rather than on the coordinator payload alone, they also mix
in `entity.HourBoundaryRefreshMixin`, which re-writes their state at hh:00:05
so an elapsed hour never lingers in a "next hour" window.
`GeoSphereOutlookSensor` recomputes its state and its attributes together in
`_refresh_outlook` — on coordinator updates and at each hour boundary — so both
always come from one scan at one sample of the clock.

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
- Keep `api.py` / `models.py` / `condition.py` / `outlook.py` free of
  `homeassistant` imports.
