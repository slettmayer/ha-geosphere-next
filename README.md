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
| Hourly forecast (+60 h) | Deterministic forecast `nwp-v2-1h-1km` (the C-LAEF AlpeAdria control run) | 1 km, model runs every 3 h |
| Precipitation-probability estimate (per forecast hour), ensemble thunderstorm signal | C-LAEF ensemble `ensemble-v2-1h-1km` | 1 km, model runs every 3 h |
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
| `state` (condition) | HA weather condition (`sunny`, `cloudy`, `rainy`, …): GeoSphere's own weather symbol for the hour, with observations deciding what is falling now — see [below](#how-the-weather-condition-is-derived) | nowcast / INCA → forecast symbol |
| `temperature` | Current air temperature | INCA analysis |
| `apparent_temperature` | "Feels like" temperature | INCA analysis |
| `dew_point` | Current dew point | INCA analysis |
| `humidity` | Relative humidity (%) | INCA analysis |
| `pressure` | Mean-sea-level pressure (hPa) | INCA analysis |
| `wind_speed` | Current wind speed | INCA analysis |
| `wind_bearing` | Wind direction (°) | INCA analysis |
| `wind_gust_speed` | Current wind gusts | INCA nowcast |
| `cloud_coverage` | Cloud cover (%) | forecast |

The hourly forecast is read with the `weather.get_forecasts` service (`type:
hourly`). Each of the ~60 forecast hours carries: `datetime`, `condition`
(GeoSphere's weather symbol for that hour, mapped to HA's conditions),
`temperature`, `dew_point`, `humidity`, `precipitation`,
`precipitation_probability` (a stepped 0 / 30 / 70 / 95 % **estimate this
integration derives** from the C-LAEF ensemble percentiles — GeoSphere
publishes no probability; see the FAQ), `wind_speed`, `wind_bearing`,
`wind_gust_speed`, and `cloud_coverage`. All forecast values come from the
deterministic forecast except the probability (C-LAEF ensemble).

The list is re-filtered to the current hour onward on every read, not just at
fetch time — so it never carries already-elapsed hours even at the 180-minute
forecast interval — and re-pushed to any live subscribers at every full hour.

### Current-condition sensors (enabled by default)

| Sensor | Description | Unit |
|---|---|---|
| `temperature` | Current air temperature | °C |
| `apparent_temperature` | "Feels like" temperature | °C |
| `dew_point` | Temperature at which air saturates | °C |
| `humidity` | Relative humidity | % |
| `pressure` | Mean-sea-level (MSL) pressure | hPa |
| `wind_speed` | Current wind speed | km/h |
| `wind_gust_speed` | Peak wind gust speed | km/h |
| `wind_bearing` (Wind direction) | Direction the wind blows *from* | ° |
| `cloud_coverage` | Fraction of sky covered by cloud | % |
| `precipitation_1h` (Precipitation, last hour) | Rain/snow accumulated over the last hour, from INCA's hourly `RR`. `unknown` when INCA has none: the 15-min nowcast serves one model run clamped to its own start, so its buckets cover a fraction of an hour and summing them reported a quarter-hour as a full one | mm |
| `precipitating` (binary sensor, `moisture`) | On while precipitation is falling now — from the nowcast `pt` code or its instantaneous rate ≥ 0.1 mm/h. `unknown`, never `off`, whenever the nowcast is unavailable (outside the Austrian grid, or a failed fetch): INCA's hourly `RR` is an accumulation, not evidence about *now*, so there is nothing left to answer with and a "dry" would be invented | — |
| `condition` | The weather entity's current condition as a plain text sensor | — |
| `precipitation_kind` (Precipitation type) | What is falling now, decoded from the nowcast `pt` code: `rain`, `freezing_rain`, `snow`, `rain_and_snow` or `no_precipitation` ([GeoSphere's code table](https://github.com/Geosphere-Austria/dataset-api-docs/issues/71#issuecomment-6125846140)). `unknown` for a code outside that table, for `255` while the measured rate says it is precipitating, or when the nowcast is unavailable | — |
| `global_radiation` | Downward shortwave (solar) irradiance | W/m² |
| `snow_limit` | Altitude of the rain/snow line | m |
| `observation_time` (Observation time) | Which hour the current conditions actually describe — the INCA analysis they came from, which can be ~90 min old (diagnostic category, but enabled: see the FAQ) | timestamp |
| `model_run` (Model run) | Which deterministic run the forecast comes from — its `reference_time`, which can be several hours behind (diagnostic category, but enabled: see the FAQ) | timestamp |

Values are merged from INCA analysis → INCA nowcast → deterministic forecast with a
per-field fallback chain, so an individual field stays populated even when its
preferred dataset is briefly unavailable. `wind_speed` and `wind_gust_speed`
are natively km/h (Home Assistant converts for imperial units); the
`weather.<location>` entity's `wind_speed` / `wind_gust_speed` attributes stay
natively m/s, matching HA's weather-platform convention.

### Advanced / diagnostic sensors (disabled by default)

Enable these per-entity in Home Assistant if you want them.

| Sensor | Description | Unit |
|---|---|---|
| `cape` | Convective Available Potential Energy of the forecast hour covering now — a thunderstorm-potential indicator, informational only (neither the condition nor the storm outlook reads it) | J/kg |
| `precipitation_type` (Precipitation type code) | Raw GeoSphere precipitation-type code (diagnostic): 1 rain, 3 freezing rain, 5 snow, 7 rain and snow, 255 no precipitation. The decoded `precipitation_kind` sensor is usually what you want; this one shows a code outside that table, which that sensor reports as `unknown` | — |
| `weather_symbol` | GeoSphere weather-symbol code (1–32) of the forecast hour covering now — the code the condition is mapped from (diagnostic) | — |

### Storm outlook (enabled by default, except `cape_max_12h`)

Forecast-derived signals scanned from the hourly forecast series. The gust
maxima are deliberately threshold-free: what counts as "too windy" is your
automation's policy, not this integration's.

Thunder has two signals, and both thunder entities apply the same per-hour
test — an hour with either signal is a thunderstorm hour, so whenever the
binary sensor is on, `next_thunderstorm` names an hour inside its window:

- **Symbol** — GeoSphere's own weather symbol for the hour is a thunderstorm
  code (26–32, thunder with rain, sleet or snow).
- **Ensemble** — the C-LAEF ensemble's 90th percentiles reach both
  1000 J/kg CAPE and 0.1 mm of precipitation for the hour, so at least a tenth
  of the ensemble members allow a storm the deterministic run may not show.

It leans towards false alarms on purpose: for storm blinds a needless close is
cheap and a missed storm is not. Both entities carry a `source` attribute
saying which signal fired — `symbol`, `ensemble` or `symbol_and_ensemble` —
so you can tell why they turned on, or ignore the ensemble branch in your own
automation. The binary sensor judges it across its window, `next_thunderstorm`
for the hour it names.

| Sensor | Description | Unit |
|---|---|---|
| `wind_gust_max_1h` | Peak forecast wind gust over the 1-hour horizon (see the rounding note below) | km/h |
| `wind_gust_max_12h` | Peak forecast wind gust over the 12-hour horizon; carries a `peak_time` attribute | km/h |
| `cape_max_12h` | Peak CAPE over the 12-hour horizon (diagnostic, disabled by default; informational only) | J/kg |
| `next_thunderstorm` | Start of the first forecast hour with a thunderstorm symbol or the ensemble storm signal (`unknown` if none in the ~57 h horizon); carries `cape` and `source` attributes for that hour | — |
| `thunderstorm_expected_1h` (binary sensor; entity id: `thunderstorm_expected_next_hour`) | On when any hour in the 1-hour horizon has a thunderstorm symbol or the ensemble storm signal; `source` attribute names which. `unknown` when the window holds no hour with a symbol or ensemble data | — |

Gust maxima are natively km/h, matching the current-condition wind sensors.
The three numeric sensors carry no `state_class`: they are predictions, so
Home Assistant deliberately keeps them out of long-term statistics.

**The horizon rounds up to whole hourly steps.** The forecast is an hourly series,
and the scan starts at the top of the *current* hour so the in-progress hour
still counts. An N-hour horizon therefore spans N + 1 hourly stamps: the
1-hour sensors cover the current hour **and the next one**, and can report an
event up to ~2 h ahead. Concretely, at 14:30 the "1 hour" window covers the
14:00 and 15:00 forecast hours — so `wind_gust_max_1h` may already show a gust
that arrives at 15:50. Treat these as "soon", not "within 60 minutes"; if you
need a strict lead time, close external blinds off `wind_gust_max_1h` and
compare `wind_gust_max_12h`'s `peak_time` attribute against `now()` yourself.

For the same reason `next_thunderstorm` can be **up to 59 minutes in the
past**: when the storm hour is the one already under way, its timestamp is
the top of the current hour. That is intentional — it means "storm in
progress" — but it breaks naive lead-time math. Clamp it:

```jinja
{% set t = states('sensor.geosphere_next_next_thunderstorm') | as_datetime %}
{% if t %}
  {% set lead = ((t - now()).total_seconds() / 60) | round %}
  {{ 'storm in progress' if lead <= 0 else lead ~ ' min' }}
{% endif %}
```

Outlook *data* refreshes on the forecast coordinator's update interval
(default 30 min, configurable — see [Options](#options)), so the values carry
that granularity, not minute-by-minute precision. The window itself is
additionally re-evaluated at every full hour, so a "next hour" answer never
describes an hour that has already elapsed, even at the 180-minute interval.

Home Assistant derives entity ids from the translated display name, not the
sensor key above — that is why `thunderstorm_expected_1h` ends up as
`thunderstorm_expected_next_hour`; the other four outlook sensors' entity ids
match their keys.

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

Requires Home Assistant 2025.12.0 or newer. The integration is in the
[HACS](https://hacs.xyz/) default store.

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=slettmayer&repository=ha-geosphere-next&category=integration)

1. In HACS, search for **GeoSphere Austria Next** and download it (or use the
   button above).
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → **GeoSphere Austria Next**.
4. Pick a location (defaults to your home coordinates).

The forecast covers Austria and the surrounding Alpine region (latitude
43.0–51.5°, longitude 5.03–22.57°); current
conditions (INCA/nowcast) are available inside Austria only. Locations inside
the forecast domain but outside Austria fall back to forecast-based current
values automatically.

## Options

Settings → Devices & Services → GeoSphere Austria Next → Configure:

- **Current conditions update interval** (default 15 min)
- **Forecast update interval** (default 30 min — the forecast model itself only
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

The chem model covers central Europe (a superset of the forecast domain), so air
quality works for every location this integration accepts. Note that these are
*model forecast* values, not station measurements — expect them to track, but
not exactly match, the nearest monitoring station.

## How the weather condition is derived

Every forecast hour takes GeoSphere's own weather symbol (`sy`), using the
[code table GeoSphere published](https://github.com/Geosphere-Austria/dataset-api-docs/issues/30#issuecomment-2042539848):

| Symbol | Condition |
|---|---|
| clear, fair (1–2) | `sunny`, or `clear-night` at night |
| cloudy (3) | `partlycloudy` |
| mostly cloudy, overcast (4–5) | `cloudy` |
| ground fog, high fog (6–7) | `fog` |
| light / moderate rain, rain showers (8, 9, 17, 18) | `rainy` |
| heavy rain, heavy rain showers (10, 19) | `pouring` |
| sleet, sleet showers (11–13, 20–22) | `snowy-rainy` |
| snow, snow showers (14–16, 23–25) | `snowy` |
| thunderstorms of any kind (26–32) | `lightning-rainy` |

A missing or unknown code shows `unknown` rather than a guess. The table has
no `windy` codes, so `windy` and `windy-variant` never appear.

The **current** condition comes from a model run that is often 3–6 hours old,
so observations decide what is falling now. When the nowcast (or a recent INCA
analysis) observes precipitation, its kind — rain, snow, sleet — decides the
condition, and a thunderstorm symbol for the hour turns it into
`lightning-rainy` (except observed snow at or below 1 °C, which stays `snowy`).
When observations say it is dry, the hour's symbol applies — but a rain, snow
or thunder symbol shows `cloudy`, because the model expects precipitation that
is not falling. Where nothing observes precipitation (outside Austria), the
symbol applies unchanged.

GeoSphere confirmed the table for the previous forecast dataset; that the
current `nwp-v2` dataset uses the same table is measured, not published. All
observed classes match — but no fog code appeared anywhere in the domain when
it was checked, so if `nwp-v2` never emits one, **`fog` will not appear**.
Details in [docs/domain/CONDITION-DERIVATION.md](docs/domain/CONDITION-DERIVATION.md).

## FAQ

**Why does the precipitation probability only show 0 / 30 / 70 / 95 %?**
Because it is an estimate this integration derives, not a number GeoSphere
publishes. The forecast itself is a *deterministic* run — each run produces a single outcome,
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

**Why does the weather entity say `cloudy` when this hour's forecast says rain?**
The forecast row shows GeoSphere's symbol for the hour, from a model run that
is often several hours old. The current condition checks it against what is
actually observed: if the nowcast sees nothing falling, a rain or thunder
symbol becomes `cloudy`. The reverse holds too — observed rain shows `rainy`
even under a dry symbol. The thunderstorm outlook is not affected by this; it
reads the forecast symbol and the ensemble directly.

**Why does the current temperature disagree with the forecast for this hour?**
Current thermodynamic values come from the INCA hourly analysis, which is
anchored on real station observations but publishes about 30 minutes after the
hour it describes — and the previous analysis is served until the next one
exists, so the reading on display can be ~90 minutes old. On a fast morning
ramp that is easily several degrees, and it looks like a contradiction rather
than a delay: on 2026-08-11 in the Bregenzerwald, "current" showed 19.4 °C (the
09:00 analysis) while the forecast row for 11:00 showed 26.1 °C. Both were
right; they described hours two apart.

The **Observation time** sensor (diagnostic, enabled by default) shows exactly
which hour the current conditions describe, so you can tell a stale reading
from a wrong one. Nothing can make INCA publish sooner.

The 15-min nowcast product is *not* used as the primary source on purpose, and
switching to it when INCA is stale would make this worse rather than better:
its temperature extrapolates from an analysis roughly 2 hours behind, which was
measured against TAWES stations to lag by up to ±2 °C on diurnal ramps (too
cold while warming, too warm while cooling) — precisely the situation above.

**How often does the integration actually hit the API?**
About as often as the interval sliders suggest, and well inside GeoSphere's
240 requests/hour. Both forecast models rerun every 3 hours, and a request
that could only return the run the integration already holds is skipped: the
forecast coordinator still wakes on your configured interval and re-derives
everything that depends on the clock, but only reaches the network once the
run it holds could have been superseded. In practice that is most of the
time, because GeoSphere publishes a run more than 3 hours after its stamp —
so the forecast costs up to two requests per interval.

That last part is why the intervals are not simply scheduled against the model
run times. GeoSphere computes a run well after the hour it is stamped for, and
the lag is neither published nor constant — on 2026-11-01 at 09:19 UTC, the
newest run of both models was still 03:00 UTC (the 06:00 run was not out yet).
A schedule pinned to 00/03/06 would fetch before the data exists; waiting for
the run stamp to change needs no guess about the lag and adapts on its own if
GeoSphere shifts it.

The **Model run** sensor (diagnostic, enabled by default) shows which run is on
display. If it looks old, that is usually GeoSphere's publication lag rather
than a stuck integration — compare it against the run cadence above.

**Why is there no daily forecast?**
The forecast is a deliberately high-resolution, *short-range* model: its +60 h
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
