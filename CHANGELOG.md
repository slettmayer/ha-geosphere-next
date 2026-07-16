# Changelog

## 0.7.0

- Add: optional air-quality sensors (off by default, enable via Configure) — NO₂, O₃, PM10, PM2.5 concentrations and the daily European Air Quality Index from GeoSphere's WRF-Chem forecast (`chem-v2-1h-3km` / `chem_aqi-v1-1d-3km`, 3 km grid)
- Add: each pollutant sensor exposes its +73 h hourly forecast as a `forecast` attribute (excluded from the recorder); the AQI sensor carries `today` / `tomorrow` / `in_2_days` attributes

## 0.6.0

- Fix: current temperature, humidity, dew point, and wind now prefer the INCA hourly analysis over the 15-min nowcast — the nowcast temperature extrapolates from an analysis ~2 h behind and lagged real stations by up to ±2 °C on diurnal ramps (too cold while warming, too warm while cooling)
- Fix: the INCA cache now refreshes based on the age of the newest analysis instead of the last fetch time, cutting worst-case staleness from ~2 h to ~75 min

## 0.5.0

- Add: GeoSphere Austria brand images shipped inside the integration (`brand/` directory, the Brands Proxy API mechanism for custom integrations since HA 2026.3) — the integration now shows its icon and logo in the HA UI
- Chore: enable the HACS brands check (satisfied by the local `brand/` assets) — last blocker before the HACS default-store submission

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
