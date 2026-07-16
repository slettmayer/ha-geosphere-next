# Air Quality

## Purpose
Document the optional air-quality feature: the WRF-Chem pollutant forecast and
the daily European Air Quality Index, and how they map to sensors.

## Responsibilities
- Explain the air-quality coordinator, its pollutants, and the daily AQI.
- Document the per-pollutant hourly forecast attribute and recorder exclusion.
- Explain how enabling/disabling the option adds or removes the entities.

## Non-Responsibilities
- The weather condition and current-conditions fields — see
  [CURRENT-CONDITIONS.md](CURRENT-CONDITIONS.md).
- Dataset definitions — see [DATASETS.md](DATASETS.md).

## Overview

Air quality is off by default and toggled by the `air_quality` option (see
[../tech/ARCHITECTURE.md](../tech/ARCHITECTURE.md)). When enabled,
`GeoSphereAirQualityCoordinator`
(`custom_components/geosphere_next/coordinator.py`) polls every 60 min (fixed,
not user-configurable — the WRF-Chem model runs once daily).

### Pollutants and AQI

- **Pollutant concentrations** (µg/m³): `no2`, `o3`, `pm10`, `pm25` from the
  WRF-Chem `chem` dataset. The current value is the forecast hour closest to now;
  the full ~73 h hourly series per pollutant is stored in `AirQualityData.forecast`.
- **Daily European AQI** (1–6, EEA scale) from the `chem_aqi` dataset, matched to
  the local calendar day and stored as the `AirQualityData` fields `aqi_today` /
  `aqi_tomorrow` / `aqi_in_2_days` (surfaced on the sensor as the `today` /
  `tomorrow` / `in_2_days` attributes). AQI stamps are 00:00 UTC, matched by local
  date.

The AQI fetch is isolated in its own try/except: its failure logs a warning and
keeps the concentration sensors alive; only a `chem` failure raises `UpdateFailed`.

### Sensors

`sensor.py` declares five `GeoSphereAirQualitySensorEntityDescription` entries
(`nitrogen_dioxide`, `ozone`, `pm10`, `pm25`, `air_quality_index`), each with a
`value_fn` and an `attributes_fn`. The four pollutant sensors expose their hourly
series as a `forecast` attribute; the AQI sensor exposes `today` / `tomorrow` /
`in_2_days`.

The `forecast` attribute (the full ~73 h hourly series per pollutant) is
excluded from the HA recorder via
`_unrecorded_attributes = frozenset({"forecast"})` so history does not grow the
database — it is meant for dashboards, not long-term storage.

### Lifecycle

Turning the option on creates the coordinator and adds the five sensors. Turning
it off removes the leftover entities from the registry in
`__init__._remove_air_quality_entities`, matched by the
`{entry_id}-{key}` unique-id pattern in `AIR_QUALITY_SENSOR_KEYS`.

## Dependencies
- WRF-Chem `chem` and `chem_aqi` datasets — see [DATASETS.md](DATASETS.md).

## Design Decisions
- The daily AQI degrades independently of the pollutant concentrations
  ("primary must succeed, secondary degrades").
- The hourly forecast lives in an entity attribute (recorder-excluded) rather
  than as separate history-tracked sensors.

## Known Risks
- These are model-forecast values, not station measurements — expect them to
  track but not match the nearest monitoring station.
- WRF-Chem does not provide CO, SO₂, NH₃, NO, UV index, or visibility.

## Extension Guidelines
- To add a pollutant, extend `CHEM_PARAMETERS`, the `CHEM_POLLUTANTS` map, the
  `AirQualityData` fields, and the `AIR_QUALITY_SENSORS` tuple.
- Keep large series in recorder-excluded attributes.
