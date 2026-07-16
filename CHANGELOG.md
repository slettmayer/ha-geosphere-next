# Changelog

## 0.4.0

- Chore: migrate the test harness to Python 3.14 + pytest-homeassistant-custom-component 0.13.346 (HA 2026.7.2)
- Chore: replace aioresponses (incompatible with aiohttp 3.14) with Home Assistant's own `aioclient_mock` test mocker — no runtime changes

## 0.3.0

- Remove: the daily forecast. AROME's +60 h horizon yields at most 2–3 aggregable days, and the Home Assistant frontend only renders forecasts with more than 2 entries — the daily view would intermittently spin forever (evenings). The weather entity is hourly-only now; see the README FAQ

## 0.2.0

- Add: hourly forecast dew point, derived from AROME temperature + humidity via the Magnus formula
- Fix: the daily forecast no longer shows a misleading partial "today" built only from evening hours — days now need at least 3 daytime hours (06:00–17:59 local) to be included
- Docs: FAQ on the deterministic AROME model (no precipitation probability) and the daily-forecast horizon

## 0.1.2

- Fix: the hourly forecast now includes the current, in-progress hour instead of starting at the next full hour, matching OpenWeatherMap and the Open-Meteo AROME view

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
