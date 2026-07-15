# Changelog

## 0.1.1

- Bump dependency (Dependabot)

## 0.1.0

- Initial release: weather entity with AROME hourly forecast (+60 h) and derived daily forecast (~2–3 days) for arbitrary coordinates
- Current-condition sensors from INCA nowcast/analysis: temperature, apparent temperature, dew point, humidity, MSL pressure, wind speed / gusts / direction, cloud coverage, precipitation (last hour), condition, global radiation, snow limit
- Diagnostic sensors (disabled by default): CAPE, raw precipitation-type code, raw GeoSphere weather-symbol code
- Condition derived from physical parameters (cloud cover, precipitation, CAPE, wind gusts, solar elevation)
- UI config flow with map location picker; multiple locations supported
- Options for current-conditions and forecast update intervals
- Degraded AROME-only mode for locations outside Austria but inside the AROME domain
