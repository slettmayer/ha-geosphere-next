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
| Hourly forecast (+60 h) | AROME `nwp-v1-1h-2500m` | 2.5 km, model runs every 3 h |
| Current temperature, humidity, dew point, wind, MSL pressure, global radiation, 1 h precipitation | INCA analysis `inca-v1-1h-1km` | 1 km, hourly (observation-anchored) |
| Current precipitation type/rate, wind gusts; fallback for the INCA fields | INCA nowcast `nowcast-v1-15min-1km` | 1 km, 15 min |

No API key required. The default polling intervals use ~7 requests/hour of the
API's 240 requests/hour budget.

## Entities

- **Weather entity** with current conditions plus an hourly forecast
  (`weather.get_forecasts`). No daily forecast — see the FAQ.
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

## FAQ

**Why is there no precipitation probability in the forecasts?**
AROME is a *deterministic* model — each run produces a single outcome, not an
ensemble of scenarios, so there is no probability to report. Integrations that
show one (OpenWeatherMap, Open-Meteo) derive it from ensemble or statistically
post-processed products. If GeoSphere's C-LAEF ensemble dataset becomes
practical to sample per point, this may be added later.

**Why can the current temperature trail nearby stations by up to ~1 °C?**
Current thermodynamic values come from the INCA hourly analysis, which is
anchored on real station observations but publishes with some delay — the
newest available hour can be up to ~75 minutes old, so steep morning/evening
ramps show up slightly late. The 15-min nowcast product is *not* used as the
primary source on purpose: its temperature extrapolates from an analysis
roughly 2 hours behind, which was measured to lag real stations by up to
±2 °C on diurnal ramps (too cold while warming, too warm while cooling).

**Why is there no daily forecast?**
AROME is a deliberately high-resolution, *short-range* model: its +60 h
horizon covers at most 2–3 aggregable local days (and no GeoSphere dataset
forecasts further ahead — the C-LAEF ensemble has the same 61 h length).
The Home Assistant frontend only renders forecasts with more than 2 entries,
so a daily view would intermittently show a perpetual loading spinner
depending on the time of day. Hourly-only is the honest fit; pair the
integration with a long-range provider if you need multi-day forecasts.

## Attribution

Data provided by [GeoSphere Austria](https://www.geosphere.at/) via the
Dataset API, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The GeoSphere Austria name and logo (`custom_components/geosphere_next/brand/`)
are trademarks of GeoSphere Austria, used for identification purposes only.
They are **not** covered by this repository's MIT license.

This is a third-party integration, not affiliated with GeoSphere Austria.
