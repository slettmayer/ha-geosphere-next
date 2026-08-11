"""Constants for the GeoSphere Austria Next integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "geosphere_next"

ATTRIBUTION = (
    "Data provided by GeoSphere Austria — dataset.api.hub.geosphere.at (CC BY 4.0)"
)
MANUFACTURER = "GeoSphere Austria"

API_BASE_URL = "https://dataset.api.hub.geosphere.at/v1"

# Datasets (mode, resource id)
DATASET_AROME = ("forecast", "nwp-v1-1h-2500m")
DATASET_ENSEMBLE = ("forecast", "ensemble-v1-1h-2500m")
DATASET_NOWCAST = ("forecast", "nowcast-v1-15min-1km")
DATASET_INCA = ("historical", "inca-v1-1h-1km")
DATASET_CHEM = ("forecast", "chem-v2-1h-3km")
DATASET_CHEM_AQI = ("forecast", "chem_aqi-v1-1d-3km")

AROME_PARAMETERS = (
    "t2m",
    "mnt2m",
    "mxt2m",
    "rh2m",
    "u10m",
    "v10m",
    "ugust",
    "vgust",
    "tcc",
    "rr_acc",
    "snow_acc",
    "snowlmt",
    "grad",
    "cape",
    "cin",
    "sy",
)
# C-LAEF ensemble precipitation percentiles (per-hour amounts, kg m-2; the
# API exposes only p10/p50/p90 — no member counts or true probabilities).
# Like AROME's interval parameters these cover the period *ending* at their
# stamp ("in the last forecast period"), so a percentile has to be shifted one
# step back to describe the hour a forecast row is stamped for.
ENSEMBLE_PARAMETERS = ("rr_p10", "rr_p50", "rr_p90")
ENSEMBLE_STEP = timedelta(hours=1)
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

# Hours of history requested alongside the AROME forecast, so the series is
# guaranteed to reach back to the hour already under way. Naming that hour as
# `start` does not work: the API rounds `start` up to the next whole stamp, so
# a request for 15:00 comes back starting 16:00 and the in-progress hour is
# gone -- taking with it the "forecast starts at the current hour" behaviour,
# `outlook.hour_at`, and the current condition's cloud/CAPE/CIN reading.
# `_process` drops whatever precedes the cutoff.
HOURLY_LOOKBACK_HOURS = 1

# How old the cached INCA slice may get before it is re-fetched (seconds).
INCA_MAX_AGE_SECONDS = 55 * 60
# INCA analyses trail real time by <1 h; query a window of the last 3 hours.
INCA_LOOKBACK_HOURS = 3

# Stepped precipitation probability from the ensemble rr percentiles: a
# percentile above PRECIP_MIN_MM bounds the fraction of wet ensemble members
# (p10 wet -> >=90 %, p50 wet -> >=50 %, p90 wet -> >=10 %); the displayed
# value is the midpoint of the implied range.
POP_P10_WET_PCT = 95
POP_P50_WET_PCT = 70
POP_P90_WET_PCT = 30
POP_DRY_PCT = 0

# Condition-derivation thresholds (see condition.py)
THUNDER_CAPE_JKG = 1000.0
# Convective inhibition cap. AROME publishes `cin` as NEGATIVE J/kg: 0.0 means
# uncapped, more negative means a stronger lid. CAPE only counts as thunder
# potential when inhibition is weaker than this magnitude.
# The recorded fixture's strongest lid is -49.5 J/kg, just inside this
# boundary, so the gate suppresses nothing on the only real sample we have and
# is exercised only by synthetic test values. 50 J/kg is a standard boundary
# for weak inhibition; discrimination against real capped situations is
# unconfirmed — see docs/domain/DATASETS.md.
CAP_CIN_JKG = 50.0
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
# Rain/snow split when the nowcast precipitation-type code is unknown.
SNOW_MAX_T2M_C = 1.0

# Forecast-outlook horizons (see outlook.py). The window rounds up to whole
# hourly steps, so an N-hour horizon spans the in-progress hour plus N more.
# The entity keys/ids keep their literal "1h"/"12h" spelling.
OUTLOOK_SHORT_HORIZON_HOURS = 1
OUTLOOK_LONG_HORIZON_HOURS = 12

# Nowcast `pt` (precipitation type): 255 = no precipitation. The remaining
# code table is undocumented; codes are therefore only used as a
# "precipitating" signal, with rain/snow decided by temperature.
PT_NO_PRECIPITATION = 255
