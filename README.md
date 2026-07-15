# GeoSphere Austria Next

Home Assistant custom integration for the official
[GeoSphere Austria Dataset API](https://dataset.api.hub.geosphere.at/v1/docs/) —
point forecast and current conditions for **your exact location**, not just
weather stations.

Unlike the core `zamg` integration (station observations only, no forecast, no
condition), this integration samples GeoSphere's gridded datasets at any
coordinate:

| Data | Dataset | Resolution |
|---|---|---|
| Hourly forecast (+60 h) + derived daily (~2–3 days) | AROME `nwp-v1-1h-2500m` | 2.5 km, model runs every 3 h |
| Current conditions | INCA nowcast `nowcast-v1-15min-1km` | 1 km, 15 min |
| MSL pressure, global radiation, 1 h precipitation | INCA analysis `inca-v1-1h-1km` | 1 km, hourly |

No API key required. The default polling intervals use ~7 requests/hour of the
API's 240 requests/hour budget.

## Entities

- **Weather entity** with current conditions plus hourly and daily forecasts
  (`weather.get_forecasts`).
- **Sensors**: temperature, apparent temperature, dew point, humidity, pressure
  (MSL), wind speed / gusts / direction, cloud coverage, precipitation (last
  hour), condition, global radiation, snow limit.
- **Disabled by default**: CAPE, raw precipitation-type code, raw GeoSphere
  weather-symbol code (diagnostic).

Not available from GeoSphere: UV index, visibility, air pollution — keep
another source if you need those.

## Installation

1. Add this repository as a [HACS custom repository](https://hacs.xyz/docs/faq/custom_repositories/)
   (type: Integration), then install **GeoSphere Austria Next**.
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → **GeoSphere Austria Next**.
4. Pick a location (defaults to your home coordinates).

The AROME forecast covers Austria and the surrounding Alpine region; current
conditions (INCA/nowcast) are available inside Austria only. Locations inside
the AROME domain but outside Austria fall back to forecast-based current
values automatically.

## Options

Settings → Devices & Services → GeoSphere Austria Next → Configure:

- **Current conditions update interval** (default 15 min)
- **Forecast update interval** (default 30 min — the AROME model itself only
  reruns every 3 h)

## How the weather condition is derived

GeoSphere's own weather-symbol code table is undocumented, so the HA condition
is derived from physical parameters (cloud cover, precipitation and snow
amounts, CAPE, wind gusts, solar elevation) — the same approach open-meteo
uses for this model. The raw symbol is still exposed as a diagnostic sensor.

## Attribution

Data provided by [GeoSphere Austria](https://www.geosphere.at/) via the
Dataset API, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

This is a third-party integration, not affiliated with GeoSphere Austria.
