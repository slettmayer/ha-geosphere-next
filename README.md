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
| Precipitation probability (per forecast hour) | C-LAEF ensemble `ensemble-v1-1h-2500m` | 2.5 km, model runs every 12 h |
| Current temperature, humidity, dew point, wind, MSL pressure, global radiation, 1 h precipitation | INCA analysis `inca-v1-1h-1km` | 1 km, hourly (observation-anchored) |
| Current precipitation type/rate, wind gusts; fallback for the INCA fields | INCA nowcast `nowcast-v1-15min-1km` | 1 km, 15 min |
| Air quality (optional): NO₂, O₃, PM10, PM2.5 (+73 h hourly) | WRF-Chem `chem-v2-1h-3km` | 3 km, model runs daily |
| Air quality (optional): daily European Air Quality Index | WRF-Chem `chem_aqi-v1-1d-3km` | 3 km, model runs daily |

No API key required. The default polling intervals use ~9 requests/hour of the
API's 240 requests/hour budget (~11 with air quality enabled).

## Entities

Everything is grouped under a single service device named after your
configured location. Entity IDs follow Home Assistant's usual pattern —
`weather.<location>` and `sensor.<location>_<name>` (e.g.
`sensor.home_temperature`).

### Weather entity

One `weather.<location>` entity carrying the current state plus an hourly
forecast. It exposes no daily forecast (hourly-only — see the FAQ).

| Attribute | Description | Source |
|---|---|---|
| `state` (condition) | HA weather condition (`sunny`, `cloudy`, `rainy`, …), derived from physical parameters — see [below](#how-the-weather-condition-is-derived) | INCA → nowcast → AROME |
| `temperature` | Current air temperature | INCA analysis |
| `apparent_temperature` | "Feels like" temperature | INCA analysis |
| `dew_point` | Current dew point | INCA analysis |
| `humidity` | Relative humidity (%) | INCA analysis |
| `pressure` | Mean-sea-level pressure (hPa) | INCA analysis |
| `wind_speed` | Current wind speed | INCA analysis |
| `wind_bearing` | Wind direction (°) | INCA analysis |
| `wind_gust_speed` | Current wind gusts | INCA nowcast |
| `cloud_coverage` | Cloud cover (%) | AROME |

The hourly forecast is read with the `weather.get_forecasts` service (`type:
hourly`). Each of the ~60 forecast hours carries: `datetime`, `condition`,
`temperature`, `dew_point`, `humidity`, `precipitation`,
`precipitation_probability` (a stepped 0 / 30 / 70 / 95 % estimate from the
C-LAEF ensemble — see the FAQ), `wind_speed`, `wind_bearing`,
`wind_gust_speed`, and `cloud_coverage`. All forecast values come from AROME
except the probability (C-LAEF ensemble).

### Current-condition sensors (enabled by default)

| Sensor | Description | Unit |
|---|---|---|
| `temperature` | Current air temperature | °C |
| `apparent_temperature` | "Feels like" temperature | °C |
| `dew_point` | Temperature at which air saturates | °C |
| `humidity` | Relative humidity | % |
| `pressure` | Mean-sea-level (MSL) pressure | hPa |
| `wind_speed` | Current wind speed | m/s |
| `wind_gust_speed` | Peak wind gust speed | m/s |
| `wind_bearing` (Wind direction) | Direction the wind blows *from* | ° |
| `cloud_coverage` | Fraction of sky covered by cloud | % |
| `precipitation_1h` (Precipitation, last hour) | Rain/snow accumulated over the last hour | mm |
| `condition` | The derived HA condition as a plain text sensor | — |
| `global_radiation` | Downward shortwave (solar) irradiance | W/m² |
| `snow_limit` | Altitude of the rain/snow line | m |

Values are merged from INCA analysis → INCA nowcast → AROME forecast with a
per-field fallback chain, so an individual field stays populated even when its
preferred dataset is briefly unavailable.

### Advanced / diagnostic sensors (disabled by default)

Enable these per-entity in Home Assistant if you want them.

| Sensor | Description | Unit |
|---|---|---|
| `cape` | Convective Available Potential Energy — thunderstorm-potential indicator used in the condition derivation | J/kg |
| `precipitation_type` | Raw GeoSphere precipitation-type code (diagnostic) | — |
| `weather_symbol` | Raw GeoSphere weather-symbol code (diagnostic; the HA condition is derived independently — see the FAQ) | — |

### Air-quality sensors (optional)

Off by default. Enable the **Air quality sensors** option (see
[Air quality](#air-quality-optional)) to add these five sensors from the
WRF-Chem forecast. Each pollutant sensor also exposes its full +73 h hourly
forecast as a `forecast` attribute (excluded from the recorder).

| Sensor | Description | Unit |
|---|---|---|
| `nitrogen_dioxide` | NO₂ concentration | µg/m³ |
| `ozone` | O₃ concentration | µg/m³ |
| `pm10` | Particulate matter ≤ 10 µm | µg/m³ |
| `pm25` | Particulate matter ≤ 2.5 µm | µg/m³ |
| `air_quality_index` | Daily European Air Quality Index (1 = very good … 6 = extremely poor); carries `today` / `tomorrow` / `in_2_days` attributes | 1–6 |

Not available from GeoSphere: UV index, visibility, and the trace pollutants
CO, SO₂, NH₃, NO — keep another source if you need those.

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
- **Air quality sensors** (default off) — see below

## Air quality (optional)

Enabling the **Air quality sensors** option adds five sensors from GeoSphere's
WRF-Chem chemical weather forecast (3 km grid, one model run per day, about
2 extra API requests per hour):

- **Nitrogen dioxide, ozone, PM10, PM2.5** (µg/m³) — the current value comes
  from the forecast hour closest to now; the full +73 h hourly forecast is
  exposed as a `forecast` attribute on each sensor (excluded from the
  recorder, so it does not grow the database).
- **Air quality index** — the daily index computed by GeoSphere on the
  thresholds of the
  [European Air Quality Index](https://airindex.eea.europa.eu/) (EEA), with
  `today` / `tomorrow` / `in_2_days` attributes:

  | Value | Meaning |
  |---|---|
  | 1 | very good |
  | 2 | good |
  | 3 | fair |
  | 4 | moderate |
  | 5 | poor |
  | 6 | very poor / extremely poor |

The chem model covers central Europe (a superset of the AROME domain), so air
quality works for every location this integration accepts. Note that these are
*model forecast* values, not station measurements — expect them to track, but
not exactly match, the nearest monitoring station.

## How the weather condition is derived

GeoSphere's own weather-symbol code table is undocumented, so the HA condition
is derived from physical parameters (cloud cover, precipitation and snow
amounts, CAPE, wind gusts, solar elevation) — the same approach open-meteo
uses for this model. The raw symbol is still exposed as a diagnostic sensor.

## FAQ

**Why does the precipitation probability only show 0 / 30 / 70 / 95 %?**
AROME itself is a *deterministic* model — each run produces a single outcome,
not an ensemble of scenarios, so it has no probability of its own. The
probability comes from GeoSphere's C-LAEF *ensemble* dataset instead, which
publishes only three precipitation percentiles per hour (p10 / p50 / p90),
not the fraction of wet ensemble members. Three percentiles can only bound
that fraction: if even the 10th percentile is wet (≥ 0.1 mm), at least 90 %
of members rain; if only the median is wet, 50–90 % do; if only the 90th
percentile is wet, 10–50 % do. The integration reports the midpoint of the
implied range — 95, 70, 30, or 0 % — which is coarser than the smooth-looking
percentages other providers show, but every step is genuinely ensemble-backed
rather than interpolated.

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
