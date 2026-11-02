"""Constants for the GeoSphere Austria Next integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "geosphere_next"

ATTRIBUTION = (
    "Data provided by GeoSphere Austria — dataset.api.hub.geosphere.at (CC BY 4.0)"
)
MANUFACTURER = "GeoSphere Austria"

# Datasets (mode, resource id). `AROME` names the deterministic forecast source
# throughout the code; the dataset itself is the control run of the C-LAEF
# AlpeAdria ensemble on a 1 km grid, and `DATASET_ENSEMBLE` is that ensemble.
DATASET_AROME = ("forecast", "nwp-v2-1h-1km")
DATASET_ENSEMBLE = ("forecast", "ensemble-v2-1h-1km")
DATASET_NOWCAST = ("forecast", "nowcast-v1-15min-1km")
DATASET_INCA = ("historical", "inca-v1-1h-1km")
DATASET_CHEM = ("forecast", "chem-v2-1h-3km")
DATASET_CHEM_AQI = ("forecast", "chem_aqi-v1-1d-3km")

# Deterministic forecast parameters. Two stampings, classified by checking
# index 0 of a request that starts at the run's t0 (null there means the value
# covers the interval *ending* at its stamp) -- see `_process`:
#   * instantaneous at the stamp: 2t, 2r, 10u/10v, tcc (%), cape, snowlmt;
#   * the interval ending at the stamp: 10fg (peak gust) and tp (per-hour
#     amount, kg m-2, not run-accumulated).
# `sy` is null at t0 too. Its precipitation classes follow `tp` at the same
# stamp, so it describes the interval ending there and is read one stamp on,
# like `tp`; its cloud classes bin `tcc` at that later stamp -- see
# `_process` and the SY_* groups below.
AROME_PARAMETERS = (
    "2t",
    "2r",
    "10u",
    "10v",
    "10fg",
    "tcc",
    "tp",
    "snowlmt",
    "cape",
    "sy",
)
# C-LAEF ensemble percentiles. The API exposes only p10/p50/p90 -- no member
# counts or true probabilities.
#   * tp_p10/p50/p90: per-hour precipitation amounts (kg m-2). Like the
#     deterministic interval parameters these cover the period *ending* at
#     their stamp ("in the last forecast interval"), so a percentile is keyed
#     to the preceding stamp to describe the hour a forecast row is stamped
#     for. The cadence is read from the series rather than assumed -- see
#     `_process`.
#   * cape_p90 (J/kg): instantaneous, like the deterministic `cape` -- it has
#     a value at the run's t0 -- so it is read at its own stamp.
ENSEMBLE_PARAMETERS = ("tp_p10", "tp_p50", "tp_p90", "cape_p90")
NOWCAST_PARAMETERS = ("t2m", "td", "rh2m", "rr", "pt", "dd", "ff", "fx")
INCA_PARAMETERS = ("T2M", "TD2M", "RH2M", "RR", "P0", "GL", "UU", "VV")
# WRF-Chem surface concentrations (µg/m³), keyed by their `AirQualityData`
# field, and the daily European AQI (1-6).
CHEM_POLLUTANTS = {
    "no2": "no2surf",
    "o3": "o3surf",
    "pm10": "pm10surf",
    "pm25": "pm25surf",
}
CHEM_PARAMETERS = tuple(CHEM_POLLUTANTS.values())
CHEM_AQI_PARAMETERS = ("aqi",)

# Config / options
CONF_HAS_NOWCAST = "has_nowcast"
CONF_CURRENT_INTERVAL = "current_interval"
CONF_FORECAST_INTERVAL = "forecast_interval"
CONF_AIR_QUALITY = "air_quality"

DEFAULT_NAME = "GeoSphere Next"
DEFAULT_CURRENT_INTERVAL_MINUTES = 15
DEFAULT_FORECAST_INTERVAL_MINUTES = 30
# Not user-configurable: the chem model runs once a day with hourly steps.
AIR_QUALITY_INTERVAL_MINUTES = 60

# Hours of history requested alongside the AROME forecast, as margin so the
# series is certain to reach back to the hour already under way. Losing that
# hour would take with it the "forecast starts at the current hour" behaviour,
# `outlook.hour_at`, and the current condition's cloud/CAPE reading.
#
# What actually protects it is the *anchor*, not this margin. Where an
# unbounded request begins is the server's choice and is not documented, so
# `start` has to be named. The API honours a `start` that lands exactly on a
# stamp and rounds a mid-hour one *up* to the next -- so `start = now` at 15:30 would come back at 16:00 and the in-progress hour
# would be gone. Anchoring to the top of the hour is therefore load-bearing;
# this lookback is slack on top of it. A `start` before the run's t0 comes
# back at t0. `_process` drops whatever precedes the cutoff.
HOURLY_LOOKBACK_HOURS = 1

# How far back the current precipitation rate may look for a wet 15-min
# nowcast bucket. A single bucket can round to 0.0 in the gap between cells of
# an active storm, so the rate takes the peak across this window rather than
# the matched bucket alone. Deliberately short, so anything inside it is still
# falling; INCA's hourly `RR` is not a wider source here (see
# docs/domain/CURRENT-CONDITIONS.md).
RATE_LOOKBACK = timedelta(minutes=30)

# How far back the nowcast request reaches, anchored to a bucket boundary.
# Without a `start` the endpoint begins at the bucket covering `now`, so the
# series carries only one stamp at or before it, which leaves the
# `RATE_LOOKBACK` peak nothing to widen. Like `HOURLY_LOOKBACK_HOURS` the anchor is
# what matters: the API rounds a mid-interval `start` *up* to the next stamp,
# so it is floored to the 15-min grid before this is subtracted. One bucket of
# slack past `RATE_LOOKBACK`; the API clamps to the newest run's own t0
# regardless, which sits ~25-35 min back, so asking for more buys nothing.
NOWCAST_LOOKBACK = RATE_LOOKBACK + timedelta(minutes=15)

# Nowcast `rr` buckets carry the millimetres that fell within one 15-min step,
# so an hourly rate is the bucket value times this. Tied to the nowcast
# cadence: a move to 10-min buckets makes it 6.
NOWCAST_BUCKETS_PER_HOUR = 4.0

# How old the cached INCA slice may get before it is re-fetched (seconds).
INCA_MAX_AGE_SECONDS = 55 * 60
# INCA analyses trail real time by <1 h; query a window of the last 3 hours.
INCA_LOOKBACK_HOURS = 3
# How old INCA's hourly `RR` may get before the condition derivation stops
# counting it as observed rain (seconds). It catches a slice that has stopped
# updating, not ordinary lag: INCA's freshest `RR` is routinely up to ~90 min
# old, so the bound sits well past that -- see
# docs/domain/CURRENT-CONDITIONS.md.
INCA_RR_MAX_AGE_SECONDS = 2 * 60 * 60

# How old the held C-LAEF run may get while its endpoint keeps failing, before
# the precipitation probability is dropped rather than derived from it. The
# thunderstorm outlook reads the ensemble only while its run is this young
# (`outlook.ensemble_is_current`). Serving an older run through a brief outage
# is worth more than a blank field; serving one indefinitely is not, because
# nothing on display says which run a probability came from. The model reruns
# every 3 h but publishes several hours behind its stamp, so the run in
# service is already that old: the bound covers the publication lag plus two
# missed reruns, with margin.
ENSEMBLE_MAX_FALLBACK_AGE = timedelta(hours=12)

# Stepped precipitation probability, an estimate derived here from the
# ensemble tp percentiles -- GeoSphere publishes no probability. A percentile
# above PRECIP_MIN_MM bounds the fraction of wet ensemble members (p10 wet ->
# >=90 %, p50 wet -> >=50 %, p90 wet -> >=10 %); the displayed value is the
# midpoint of the implied range.
POP_P10_WET_PCT = 95
POP_P50_WET_PCT = 70
POP_P90_WET_PCT = 30
POP_DRY_PCT = 0

# Observed-precipitation thresholds for the current condition (see
# condition.py), and the wet-hour floor shared with the probability.
PRECIP_MIN_MM = 0.1
# GeoSphere's heavy-rain codes (10, 19) start at 5 mm in the hour, so observed
# rain turns `pouring` where the forecast symbol does.
POURING_MM_PER_H = 5.0
# Rain/snow split when the nowcast `pt` code names no kind (absent, 255
# beside an observed rate, or outside PRECIPITATION_TYPES).
SNOW_MAX_T2M_C = 1.0
# Ensemble thunderstorm signal (see outlook.py): an hour whose C-LAEF 90th
# percentiles reach this CAPE and PRECIP_MIN_MM of precipitation.
THUNDER_CAPE_JKG = 1000.0
# Values of the thunderstorm outlook's `source` attribute: which signal fired.
THUNDER_SOURCE_SYMBOL = "symbol"
THUNDER_SOURCE_ENSEMBLE = "ensemble"
THUNDER_SOURCE_BOTH = "both"

# GeoSphere's `sy` weather-symbol code table, published in German in
# https://github.com/Geosphere-Austria/dataset-api-docs/issues/30#issuecomment-2042539848
# (confirmed there for nwp-v1 and assumed for nwp-v2, see DATASETS.md).
# Codes are grouped by the Home Assistant condition they map to; the HA
# strings themselves live in condition.py. 1-2 map to `sunny`, or
# `clear-night` at night.
SY_CLEAR = frozenset({1, 2})  # Wolkenlos, Heiter
SY_PARTLY_CLOUDY = frozenset({3})  # Wolkig
SY_CLOUDY = frozenset({4, 5})  # Stark bewölkt, Bedeckt
SY_FOG = frozenset({6, 7})  # Bodennebel, Hochnebel
# Leichter / Mäßiger Regen, Regenschauer
SY_RAIN = frozenset({8, 9, 17, 18})
# Starker Regen, Starker Regenschauer
SY_POURING = frozenset({10, 19})
# Schneeregen, Schneeregenschauer
SY_SLEET = frozenset({11, 12, 13, 20, 21, 22})
# Schneefall, Schneeschauer
SY_SNOW = frozenset({14, 15, 16, 23, 24, 25})
# Gewitter, Starkes Gewitter, either with Schneeregen or Schneefall
SY_THUNDER = frozenset(range(26, 33))
# Codes saying precipitation falls in the hour, thunderstorms included.
SY_PRECIPITATION = SY_RAIN | SY_POURING | SY_SLEET | SY_SNOW | SY_THUNDER
# Every published code.
SY_CODES = SY_CLEAR | SY_PARTLY_CLOUDY | SY_CLOUDY | SY_FOG | SY_PRECIPITATION

# Where within a forecast row's hour day/night is judged for the clear
# symbols: the middle, so an hour that is mostly dark reads `clear-night`.
FORECAST_ROW_MIDPOINT = timedelta(minutes=30)

# Forecast-outlook horizons (see outlook.py). The window rounds up to whole
# hourly steps, so an N-hour horizon spans the in-progress hour plus N more.
# The entity keys/ids keep their literal "1h"/"12h" spelling.
OUTLOOK_SHORT_HORIZON_HOURS = 1
OUTLOOK_LONG_HORIZON_HOURS = 12

# Nowcast `pt` (precipitation type) code table. Not in the API's `/metadata`;
# confirmed by GeoSphere against the data producer:
# https://github.com/Geosphere-Austria/dataset-api-docs/issues/71#issuecomment-6125846140
# 1/3/5/7 match GRIB2 Code Table 4.201, but 255 means "no precipitation", not
# GRIB2's "Missing". The names are GeoSphere's keys, used as enum states.
PT_RAIN = 1
PT_FREEZING_RAIN = 3
PT_SNOW = 5
PT_RAIN_AND_SNOW = 7
PT_NO_PRECIPITATION = 255
PRECIPITATION_TYPES: dict[int, str] = {
    PT_RAIN: "rain",
    PT_FREEZING_RAIN: "freezing_rain",
    PT_SNOW: "snow",
    PT_RAIN_AND_SNOW: "rain_and_snow",
    PT_NO_PRECIPITATION: "no_precipitation",
}
