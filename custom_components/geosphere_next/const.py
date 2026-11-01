"""Constants for the GeoSphere Austria Next integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "geosphere_next"

ATTRIBUTION = (
    "Data provided by GeoSphere Austria — dataset.api.hub.geosphere.at (CC BY 4.0)"
)
MANUFACTURER = "GeoSphere Austria"

API_BASE_URL = "https://dataset.api.hub.geosphere.at/v1"

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
#   * the interval ending at the stamp: 10fg (peak gust), tp and sf (per-hour
#     amounts, kg m-2, not run-accumulated).
# `sy` is null at t0 too, yet its cloud classes bin on `tcc` at its own stamp,
# so it is read at the stamp like the instantaneous fields.
AROME_PARAMETERS = (
    "2t",
    "2r",
    "10u",
    "10v",
    "10fg",
    "tcc",
    "tp",
    "sf",
    "snowlmt",
    "cape",
    "sy",
)
# C-LAEF ensemble precipitation percentiles (per-hour amounts, kg m-2; the
# API exposes only p10/p50/p90 — no member counts or true probabilities).
# Like the deterministic interval parameters these cover the period *ending*
# at their stamp ("in the last forecast interval"), so a percentile is keyed
# to the preceding stamp to describe the hour a forecast row is stamped for.
# The cadence is read from the series rather than assumed -- see `_process`.
ENSEMBLE_PARAMETERS = ("tp_p10", "tp_p50", "tp_p90")
NOWCAST_PARAMETERS = ("t2m", "td", "rh2m", "rr", "pt", "dd", "ff", "fx")
INCA_PARAMETERS = ("T2M", "TD2M", "RH2M", "RR", "P0", "GL", "UU", "VV")
# WRF-Chem surface concentrations (µg/m³) and the daily European AQI (1-6).
CHEM_PARAMETERS = ("no2surf", "o3surf", "pm10surf", "pm25surf")
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
# stamp and rounds a mid-hour one *up* to the next (measured 2026-11-01:
# `start = 07:00` came back at 07:00, `start = 07:30` at 08:00) -- so
# `start = now` at 15:30 would come back at 16:00 and the in-progress hour
# would be gone. Anchoring to the top of the hour is therefore load-bearing;
# this lookback is slack on top of it. A `start` before the run's t0 comes
# back at t0. `_process` drops whatever precedes the cutoff.
HOURLY_LOOKBACK_HOURS = 1

# How far back the current precipitation rate may look for a wet 15-min
# nowcast bucket. A single bucket can round to 0.0 in the gap between cells of
# an active storm, so the rate takes the peak across this window rather than
# the matched bucket alone. Deliberately short: INCA's hourly `RR` would be
# the obvious wider source, but it is a *total* over the past hour, and using
# it as an instantaneous rate keeps a shower that ended 40 min ago driving the
# condition. Anything inside this window is still falling.
RATE_LOOKBACK = timedelta(minutes=30)

# How far back the nowcast request reaches, anchored to a bucket boundary.
# Without a `start` the endpoint begins at the bucket covering `now`, so the
# series carries exactly one stamp at or before it -- measured 2026-09-11 at
# all three configured locations, 11 buckets each, ten of them in the future.
# That silently disabled the `RATE_LOOKBACK` peak, which needs more than the
# matched bucket to mean anything. Like `HOURLY_LOOKBACK_HOURS` the anchor is
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
# treating it as evidence about *now* (seconds). Only that derivation consults
# it; the `precipitating` binary sensor never does.
#
# This bound catches a slice that has stopped updating, NOT ordinary lag. INCA
# publishes ~30 min after the hour it analyses and the previous slice is
# served until the next appears, so the freshest `RR` in existence is
# routinely up to ~90 min old (see `_merge`, which says the same of
# `observed_at`). A bound at or below that would reject the best data the
# source has for part of every publish cycle, flapping the condition between
# `rainy` and cloud-derived once an hour through steady rain — worse than the
# staleness it set out to fix. Two hours is comfortably past the normal worst
# case: by then INCA should have published two newer analyses, so a slice this
# old means refreshes are failing and `_async_get_inca` is serving a cached
# one indefinitely. That is the unbounded case this exists for.
INCA_RR_MAX_AGE_SECONDS = 2 * 60 * 60

# Model rerun cadences, used to gate re-fetches (see `_run_is_current`). A run
# cannot be superseded before its cadence has elapsed, so until then a re-fetch
# returns byte-for-byte what is already cached and the request is pure waste.
#
# These are *cadences*, not publication times: GeoSphere computes a run well
# after the hour it is stamped for. Measured 2026-11-01 from 08:49Z to 09:19Z,
# the newest run of both datasets was 03:00Z: the 06:00Z run was still
# unpublished more than 3 h after its stamp, so the lag exceeds the cadence
# itself. Gating on the bare cadence therefore under-caches — once
# `reference_time + cadence` passes, every update cycle retries until the new
# run appears, and with a lag that long a freshly published run is usually
# already past its own cadence, so the gate rarely holds a run at all. That
# is the intended behaviour: it never serves a run that has been superseded,
# and it picks the new one up within one update interval of publication.
# Adding a latency estimate here would cache longer at the risk of sitting on
# a stale run whenever GeoSphere publishes early.
AROME_RUN_INTERVAL = timedelta(hours=3)
ENSEMBLE_RUN_INTERVAL = timedelta(hours=3)

# How old the held C-LAEF run may get while its endpoint keeps failing, before
# the precipitation probability is dropped rather than derived from it. Serving
# a superseded run through a brief outage is worth more than a blank field;
# serving one indefinitely is not, because nothing on display says which run a
# probability came from. The bound has to cover one whole missed rerun on top
# of the publication lag, and that lag is longer than the 3 h cadence itself
# (see above): the newest run in service is already several hours old, so a
# bound of a few cadences would drop it on the first failed fetch. Twelve hours
# is the lag plus two cadences, with margin.
ENSEMBLE_MAX_FALLBACK_AGE = timedelta(hours=12)

# Stepped precipitation probability from the ensemble tp percentiles: a
# percentile above PRECIP_MIN_MM bounds the fraction of wet ensemble members
# (p10 wet -> >=90 %, p50 wet -> >=50 %, p90 wet -> >=10 %); the displayed
# value is the midpoint of the implied range.
POP_P10_WET_PCT = 95
POP_P50_WET_PCT = 70
POP_P90_WET_PCT = 30
POP_DRY_PCT = 0

# Condition-derivation thresholds (see condition.py)
THUNDER_CAPE_JKG = 1000.0
PRECIP_MIN_MM = 0.1
POURING_MM_PER_H = 4.0
WINDY_GUST_MS = 15.0
CLOUDY_TCC_PCT = 62.5
CLEAR_TCC_PCT = 12.5
WINDY_CLOUD_TCC_PCT = 60.0
# Fog heuristic (current condition only); disable by setting to False.
FOG_HEURISTIC_ENABLED = True
FOG_MIN_RH_PCT = 98.0
FOG_MAX_WIND_MS = 2.0
FOG_MIN_TCC_PCT = 87.5
# Rain/snow split when the nowcast `pt` code names no kind (absent, 255
# beside an observed rate, or outside PRECIPITATION_TYPES).
SNOW_MAX_T2M_C = 1.0

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
