"""DataUpdateCoordinators for GeoSphere Austria Next."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import (
    GeoSphereApiClient,
    GeoSphereApiError,
    GeoSphereRateLimitError,
)
from .condition import (
    apparent_temperature,
    derive_condition_from_symbol,
    derive_current_condition,
    derive_precipitation_type,
    dew_point_from_t_rh,
    is_night,
    is_precipitating,
    wind_from_components,
)
from .const import (
    AIR_QUALITY_INTERVAL_MINUTES,
    AROME_PARAMETERS,
    CHEM_AQI_PARAMETERS,
    CHEM_PARAMETERS,
    CHEM_POLLUTANTS,
    CONF_CURRENT_INTERVAL,
    CONF_FORECAST_INTERVAL,
    CONF_HAS_NOWCAST,
    DATASET_AROME,
    DATASET_CHEM,
    DATASET_CHEM_AQI,
    DATASET_ENSEMBLE,
    DATASET_INCA,
    DATASET_NOWCAST,
    DEFAULT_CURRENT_INTERVAL_MINUTES,
    DEFAULT_FORECAST_INTERVAL_MINUTES,
    DOMAIN,
    ENSEMBLE_PARAMETERS,
    FORECAST_ROW_MIDPOINT,
    HOURLY_LOOKBACK_HOURS,
    INCA_LOOKBACK_HOURS,
    INCA_MAX_AGE_SECONDS,
    INCA_PARAMETERS,
    INCA_RR_MAX_AGE_SECONDS,
    NOWCAST_BUCKETS_PER_HOUR,
    NOWCAST_LOOKBACK,
    NOWCAST_PARAMETERS,
    POP_DRY_PCT,
    POP_P10_WET_PCT,
    POP_P50_WET_PCT,
    POP_P90_WET_PCT,
    PRECIP_MIN_MM,
    PRECIPITATION_TYPES,
    PT_NO_PRECIPITATION,
    RATE_LOOKBACK,
    SY_CODES,
)
from .models import (
    AirQualityData,
    CurrentConditions,
    ForecastData,
    GeoSphereResponse,
    HourlyForecast,
)
from .outlook import ensemble_is_current, hour_at

_LOGGER = logging.getLogger(__name__)

type GeoSphereNextConfigEntry = ConfigEntry[GeoSphereNextData]


@dataclass(slots=True)
class GeoSphereNextData:
    """Runtime data stored on the config entry."""

    forecast: GeoSphereForecastCoordinator
    current: GeoSphereCurrentCoordinator
    air_quality: GeoSphereAirQualityCoordinator | None = None


def _precipitation_probability(
    p10: float | None, p50: float | None, p90: float | None
) -> int | None:
    """Stepped probability of a wet hour (>= PRECIP_MIN_MM) from tp percentiles.

    The ensemble API only publishes p10/p50/p90 (no member fractions), so the
    wettest percentile above the threshold bounds the share of wet members and
    the midpoint of that range is reported: 95 / 70 / 30 / 0 %.
    """
    if p90 is None:
        return None
    if p10 is not None and p10 >= PRECIP_MIN_MM:
        return POP_P10_WET_PCT
    if p50 is not None and p50 >= PRECIP_MIN_MM:
        return POP_P50_WET_PCT
    if p90 >= PRECIP_MIN_MM:
        return POP_P90_WET_PCT
    return POP_DRY_PCT


class GeoSphereForecastCoordinator(TimestampDataUpdateCoordinator[ForecastData]):
    """Fetches and processes the AROME point forecast."""

    config_entry: GeoSphereNextConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GeoSphereNextConfigEntry,
        client: GeoSphereApiClient,
    ) -> None:
        minutes = config_entry.options.get(
            CONF_FORECAST_INTERVAL, DEFAULT_FORECAST_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} forecast",
            update_interval=timedelta(minutes=minutes),
        )
        self._client = client
        self.latitude: float = config_entry.data[CONF_LATITUDE]
        self.longitude: float = config_entry.data[CONF_LONGITUDE]
        self._ensemble: GeoSphereResponse | None = None
        # `sy` codes outside GeoSphere's table already reported, so a new one
        # warns once rather than on every update for as long as it is served.
        self._unknown_sy_codes: set[int] = set()

    async def _async_update_data(self) -> ForecastData:
        arome = await self._async_get_arome()
        ensemble = await self._async_get_ensemble()
        return self._process(arome, ensemble)

    def _series_start(self) -> datetime:
        """Left bound for the AROME and ensemble requests.

        Anchored to the top of the hour, plus an hour of margin — see
        HOURLY_LOOKBACK_HOURS. The anchor is the part that matters: the API
        rounds a mid-hour `start` up to the next whole stamp, so anchoring to
        `now` at 15:30 would come back at 16:00 and drop the hour already
        under way. `_process` drops whatever precedes the cutoff.
        """
        return dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(
            hours=HOURLY_LOOKBACK_HOURS
        )

    async def _async_get_arome(self) -> GeoSphereResponse:
        """Fetch the AROME run; a failure fails the whole forecast update."""
        try:
            return await self._client.get_timeseries(
                *DATASET_AROME,
                parameters=AROME_PARAMETERS,
                latitude=self.latitude,
                longitude=self.longitude,
                start=self._series_start(),
            )
        except GeoSphereRateLimitError as err:
            raise UpdateFailed(
                f"GeoSphere rate limit hit: {err}", retry_after=err.retry_after
            ) from err
        except GeoSphereApiError as err:
            raise UpdateFailed(f"AROME update failed: {err}") from err

    async def _async_get_ensemble(self) -> GeoSphereResponse | None:
        """Fetch the C-LAEF run, degrading to the last one held on failure.

        The percentiles add the precipitation probability and the outlook's
        ensemble storm signal, so a failure must not take the forecast down.
        A failed fetch serves the run already held rather than nothing -- the
        percentiles are matched to AROME by timestamp, so an older run still
        has a value for every hour it covers -- but only while that run is
        younger than `ENSEMBLE_MAX_FALLBACK_AGE`. Past that it is dropped and
        the probability disappears, visibly, instead of an ever older run
        staying in service with nothing on display to say so.
        """
        try:
            self._ensemble = await self._client.get_timeseries(
                *DATASET_ENSEMBLE,
                parameters=ENSEMBLE_PARAMETERS,
                latitude=self.latitude,
                longitude=self.longitude,
                start=self._series_start(),
            )
        except GeoSphereApiError as err:
            _LOGGER.warning(
                "Ensemble update failed, omitting precipitation probability: %s", err
            )
        else:
            return self._ensemble

        cached = self._ensemble
        if cached is not None and ensemble_is_current(
            cached.reference_time, dt_util.utcnow()
        ):
            return cached
        return None

    def _process(
        self, response: GeoSphereResponse, ensemble: GeoSphereResponse | None
    ) -> ForecastData:
        now = dt_util.utcnow()
        hourly: list[HourlyForecast] = []

        # Ensemble hours align with AROME's whole-hour stamps (both 1 h grids,
        # matched by exact timestamp); missing hours yield no probability.
        #
        # The tp percentiles are interval values, like the AROME fields below:
        # "total amount of ... precipitation in the last forecast interval". The
        # probability stamped `ts` therefore belongs to the period *ending* at
        # `ts`, so it is keyed by that period's start — which is simply the
        # preceding stamp, the row that reports the matching amount.
        #
        # Read from the series itself rather than by subtracting a fixed step:
        # if C-LAEF ever coarsens along its horizon (3-hourly tails are common
        # for ensembles) or drops a stamp, a fixed step would miss every key
        # and silently blank the probability across the whole forecast, with
        # nothing logged. The predecessor is right at any cadence. Index 0 is
        # the run start, whose "last period" precedes the run, so it has no
        # row to land on.
        #
        # `cape_p90` is instantaneous, like `cape`, so it stays on its stamp.
        pop_by_ts: dict[datetime, int | None] = {}
        tp_p90_by_ts: dict[datetime, float | None] = {}
        cape_p90_by_ts: dict[datetime, float | None] = {}
        if ensemble is not None:
            for i in range(1, len(ensemble.timestamps)):
                start = ensemble.timestamps[i - 1]
                tp_p90 = ensemble.value_at("tp_p90", i)
                pop_by_ts[start] = _precipitation_probability(
                    ensemble.value_at("tp_p10", i),
                    ensemble.value_at("tp_p50", i),
                    tp_p90,
                )
                tp_p90_by_ts[start] = tp_p90
            cape_p90_by_ts = {
                ts: ensemble.value_at("cape_p90", i)
                for i, ts in enumerate(ensemble.timestamps)
            }

        # Keep the in-progress hour so the forecast starts at the current hour
        # (matching OWM / Open-Meteo), comparing against the top of the hour
        # rather than the exact instant.
        #
        # A row stamped `ts` describes the hour *beginning* at `ts` — Home
        # Assistant's forecast convention. The dataset mixes two stampings (see
        # AROME_PARAMETERS for how each was classified):
        #   * instantaneous AT the stamp: 2t, 2r, 10u/10v, tcc, cape, snowlmt;
        #   * the interval ENDING at the stamp: 10fg and tp ("... in the last
        #     forecast interval"), each already a per-hour value.
        # The interval fields covering the hour that *starts* at `ts` therefore
        # live one step later, at `nxt`. Reading them at `i` would report the
        # hour that already ended — rain that has stopped, the previous hour's
        # gust peak. The final stamp has no successor and so cannot be emitted.
        #
        # `sy` is read at `nxt` too. Its precipitation classes follow `tp` at
        # their own stamp, so only there does the symbol agree with the row's
        # precipitation: at `i` a row would show rain for the hour after it
        # stopped and none for the hour it started. Its cloud classes bin `tcc`
        # at that same later stamp, i.e. the sky at the end of the row's hour.
        cutoff = now.replace(minute=0, second=0, microsecond=0)
        for i in range(len(response.timestamps) - 1):
            ts = response.timestamps[i]
            if ts < cutoff:
                continue
            nxt = i + 1
            wind_speed, wind_bearing = wind_from_components(
                response.value_at("10u", i), response.value_at("10v", i)
            )
            gust_speed = response.value_at("10fg", nxt)
            precipitation = response.value_at("tp", nxt)
            cloud = response.value_at("tcc", i)
            cape = response.value_at("cape", i)
            temperature = response.value_at("2t", i)
            humidity = response.value_at("2r", i)
            raw_symbol = response.value_at("sy", nxt)
            symbol = int(raw_symbol) if raw_symbol is not None else None
            if (
                symbol is not None
                and symbol not in SY_CODES
                and symbol not in self._unknown_sy_codes
            ):
                self._unknown_sy_codes.add(symbol)
                _LOGGER.warning(
                    "Forecast reported weather-symbol code %s, which is not in "
                    "GeoSphere's published table; its hours' condition reads unknown",
                    symbol,
                )
            hourly.append(
                HourlyForecast(
                    datetime=ts,
                    temperature=temperature,
                    humidity=humidity,
                    precipitation=precipitation,
                    wind_speed=wind_speed,
                    wind_bearing=wind_bearing,
                    wind_gust_speed=gust_speed,
                    cloud_coverage=cloud,
                    cape=cape,
                    snow_limit=response.value_at("snowlmt", i),
                    dew_point=dew_point_from_t_rh(temperature, humidity),
                    precipitation_probability=pop_by_ts.get(ts),
                    ensemble_cape_p90=cape_p90_by_ts.get(ts),
                    ensemble_precipitation_p90=tp_p90_by_ts.get(ts),
                    weather_symbol=symbol,
                    condition=derive_condition_from_symbol(
                        symbol,
                        is_night(
                            self.latitude, self.longitude, ts + FORECAST_ROW_MIDPOINT
                        ),
                    ),
                )
            )

        if not hourly:
            raise UpdateFailed("AROME response contained no future forecast hours")

        return ForecastData(
            reference_time=response.reference_time,
            grid_latitude=response.grid_latitude,
            grid_longitude=response.grid_longitude,
            hourly=hourly,
            current=hourly[0],
            ensemble_reference_time=ensemble.reference_time if ensemble else None,
        )


class GeoSphereCurrentCoordinator(TimestampDataUpdateCoordinator[CurrentConditions]):
    """Merges nowcast + INCA (+ AROME fallback) into current conditions."""

    config_entry: GeoSphereNextConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GeoSphereNextConfigEntry,
        client: GeoSphereApiClient,
        forecast_coordinator: GeoSphereForecastCoordinator,
    ) -> None:
        minutes = config_entry.options.get(
            CONF_CURRENT_INTERVAL, DEFAULT_CURRENT_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} current",
            update_interval=timedelta(minutes=minutes),
        )
        self._client = client
        self._forecast = forecast_coordinator
        self.latitude: float = config_entry.data[CONF_LATITUDE]
        self.longitude: float = config_entry.data[CONF_LONGITUDE]
        self.has_nowcast: bool = config_entry.data.get(CONF_HAS_NOWCAST, True)
        self._inca: GeoSphereResponse | None = None
        # `pt` codes outside GeoSphere's table already reported, so a new one
        # warns once rather than on every poll for as long as it is falling.
        self._unknown_pt_codes: set[int] = set()

    async def _async_update_data(self) -> CurrentConditions:
        nowcast: GeoSphereResponse | None = None
        if self.has_nowcast:
            # Anchored to the 15-min grid: the API rounds a mid-interval
            # `start` up to the next stamp, which would drop the bucket
            # covering `now` along with everything before it.
            now = dt_util.utcnow()
            bucket = now.replace(
                minute=now.minute - now.minute % 15, second=0, microsecond=0
            )
            try:
                nowcast = await self._client.get_timeseries(
                    *DATASET_NOWCAST,
                    parameters=NOWCAST_PARAMETERS,
                    latitude=self.latitude,
                    longitude=self.longitude,
                    start=bucket - NOWCAST_LOOKBACK,
                )
            except GeoSphereApiError as err:
                _LOGGER.warning("Nowcast update failed, falling back: %s", err)

        inca = await self._async_get_inca()
        return self._merge(nowcast, inca)

    async def _async_get_inca(self) -> GeoSphereResponse | None:
        """Return the cached INCA slice, refreshing once its newest analysis ages out.

        Freshness is keyed on the newest analysis timestamp, not the fetch
        time: once the latest published hour is older than ~55 min, every
        update cycle retries until the next hourly analysis appears (at most
        a few extra requests per hour against the 240 req/h budget).
        """
        now = dt_util.utcnow()
        if (
            self._inca is not None
            and self._inca.timestamps
            and (now - self._inca.timestamps[-1]).total_seconds() < INCA_MAX_AGE_SECONDS
        ):
            return self._inca
        if not self.has_nowcast:
            # INCA shares the nowcast's Austria-only grid.
            return None
        try:
            self._inca = await self._client.get_timeseries(
                *DATASET_INCA,
                parameters=INCA_PARAMETERS,
                latitude=self.latitude,
                longitude=self.longitude,
                start=now - timedelta(hours=INCA_LOOKBACK_HOURS),
                end=now,
            )
        except GeoSphereApiError as err:
            _LOGGER.warning("INCA update failed, falling back: %s", err)
        return self._inca

    def _merge(
        self, nowcast: GeoSphereResponse | None, inca: GeoSphereResponse | None
    ) -> CurrentConditions:
        now = dt_util.utcnow()
        forecast_data = self._forecast.data
        # The AROME-sourced fields must follow the clock rather than the
        # forecast fetch: this coordinator runs every 15 min by default while
        # the forecast one can be up to 180 min apart. The step-0 snapshot —
        # the hour that was in progress when the forecast was last fetched —
        # can therefore be hours old. Cloud cover, CAPE, the snow limit and the
        # weather symbol have no other source, and the symbol feeds the derived
        # condition, so the reported condition would go stale with it. Pick the
        # hour covering `now` instead, degrading to that snapshot only when the
        # series no longer covers now at all. The forecast coordinator's first
        # refresh succeeds before this coordinator exists, so a forecast is
        # always held.
        arome = hour_at(forecast_data.hourly, now) or forecast_data.current

        # Index of the nowcast bucket nearest `now`. Resolved once and reused by
        # every nowcast field below and by `observed_at`: the bucket cannot
        # change within this call. Nearest in *either* direction -- see the
        # clamp on `observed_at`.
        nowcast_index: int | None = None
        if nowcast is not None and nowcast.timestamps:
            nowcast_index = min(
                range(len(nowcast.timestamps)),
                key=lambda i: abs((nowcast.timestamps[i] - now).total_seconds()),
            )

        def now_value(name: str) -> float | None:
            if nowcast is None or nowcast_index is None:
                return None
            return nowcast.value_at(name, nowcast_index)

        def inca_latest(name: str) -> tuple[float | None, datetime | None]:
            if inca is None:
                return None, None
            data = inca.series(name)
            for i in range(len(inca.timestamps) - 1, -1, -1):
                if data[i] is not None:
                    return data[i], inca.timestamps[i]
            return None, None

        def chain(*values: float | None) -> float | None:
            for value in values:
                if value is not None:
                    return value
            return None

        inca_wind_speed, inca_wind_bearing = wind_from_components(
            inca_latest("UU")[0], inca_latest("VV")[0]
        )
        # INCA (observation-anchored hourly analysis) beats the 15-min nowcast
        # for thermodynamic fields and wind: the nowcast extrapolates from an
        # analysis ~2 h behind, lagging diurnal ramps by up to ~2 °C.
        inca_t2m, inca_t2m_at = inca_latest("T2M")
        temperature = chain(
            inca_t2m,
            now_value("t2m"),
            arome.temperature,
        )
        humidity = chain(
            inca_latest("RH2M")[0],
            now_value("rh2m"),
            arome.humidity,
        )
        wind_speed = chain(inca_wind_speed, now_value("ff"), arome.wind_speed)
        gust = chain(now_value("fx"), arome.wind_gust_speed)
        symbol = arome.weather_symbol

        p0, _ = inca_latest("P0")
        # INCA `RR` is the only source for the hourly accumulation: the
        # nowcast serves a single run clamped to its own t0, so its buckets
        # never cover a whole hour.
        rr_1h, rr_1h_time = inca_latest("RR")

        pt_raw = now_value("pt")
        precipitation_type = int(pt_raw) if pt_raw is not None else None
        if (
            precipitation_type is not None
            and precipitation_type not in PRECIPITATION_TYPES
            and precipitation_type not in self._unknown_pt_codes
        ):
            self._unknown_pt_codes.add(precipitation_type)
            _LOGGER.warning(
                "Nowcast reported precipitation-type code %s, which is not in "
                "GeoSphere's published table; reporting it as unknown",
                precipitation_type,
            )
        nowcast_rr = now_value("rr")
        # `None`, not 0.0, when the nowcast observed nothing: `is_precipitating`
        # has to tell "no precipitation" apart from "no observation", which it
        # cannot do once the absence has been defaulted away.
        nowcast_rate_mm_h = (
            nowcast_rr * NOWCAST_BUCKETS_PER_HOUR if nowcast_rr is not None else None
        )
        # INCA's hourly `RR` is an accumulation, not an observation of *now*:
        # it never feeds `is_precipitating` or the peak below. It stands in for
        # the condition's rate only while the nowcast reports neither `pt` nor
        # `rr` (a `pt` of 255 is an observed "dry" it must not overrule), only
        # when it is wet, and only while it is younger than
        # INCA_RR_MAX_AGE_SECONDS -- see docs/domain/CURRENT-CONDITIONS.md.
        # The age is bounded at both ends: an observation is never in the
        # future.
        rr_1h_age_s = (
            (now - rr_1h_time).total_seconds() if rr_1h_time is not None else None
        )
        rr_1h_is_current = (
            rr_1h_age_s is not None and 0 <= rr_1h_age_s <= INCA_RR_MAX_AGE_SECONDS
        )
        nowcast_observes = (
            precipitation_type is not None or nowcast_rate_mm_h is not None
        )
        rr_1h_is_wet = rr_1h_is_current and rr_1h is not None and rr_1h >= PRECIP_MIN_MM
        # `None` when nothing observes precipitation, which the condition
        # derivation tells apart from an observed "dry".
        rate_mm_h = (
            nowcast_rate_mm_h if nowcast_observes else (rr_1h if rr_1h_is_wet else None)
        )
        # A single bucket can round to 0.0 in the gap between cells of an
        # active storm, reporting 0 mm/h mid-downpour and starving the
        # `pouring` branch of `condition.derive_current_condition`. So once the
        # nowcast's own `pt` code says it is precipitating, take the peak
        # across the last RATE_LOOKBACK rather than the matched bucket alone.
        if (
            nowcast is not None
            and precipitation_type is not None
            and precipitation_type != PT_NO_PRECIPITATION
        ):
            recent = [
                value
                for ts, value in zip(
                    nowcast.timestamps, nowcast.series("rr"), strict=True
                )
                if now - RATE_LOOKBACK <= ts <= now and value is not None
            ]
            if recent:
                rate_mm_h = max(
                    rate_mm_h or 0.0, max(recent) * NOWCAST_BUCKETS_PER_HOUR
                )
        night = is_night(self.latitude, self.longitude, now)

        # When the conditions below actually describe: the stamp of whichever
        # source supplied the *temperature*, the field the reading is judged
        # by. Every rung follows that one field. Anchoring to any other lets
        # one field's freshness vouch for another's -- an analysis carrying RR
        # but no T2M would otherwise report a time the temperature never had,
        # and does so in whichever direction happens to be wrong.
        #
        # INCA publishes ~30 min after the hour it analyses and the previous
        # slice is served until the next appears, so this can trail real time
        # by ~90 min. The nowcast runs every 15 min; its own bucket stamp is
        # the honest answer there, not `now` -- no source ever states `now`.
        # Outside the nowcast grid every field comes from an AROME row,
        # stamped at the top of its hour and up to an hour old: exactly the
        # staleness this sensor exists to show.
        #
        # Both of those rungs are clamped to `now`, because an observation
        # time can never be in the future. The nowcast needs it as much as the
        # AROME row does: the bucket match is *nearest*, not nearest-in-the-
        # past, so at 15:38 it selects the 15:45 bucket.
        if inca_t2m is not None:
            observed_at = inca_t2m_at
        elif now_value("t2m") is not None:
            observed_at = min(nowcast.timestamps[nowcast_index], now)
        else:
            observed_at = min(arome.datetime, now)

        return CurrentConditions(
            observed_at=observed_at,
            temperature=temperature,
            apparent_temperature=apparent_temperature(
                temperature, humidity, wind_speed
            ),
            dew_point=chain(inca_latest("TD2M")[0], now_value("td")),
            humidity=humidity,
            pressure_hpa=round(p0 / 100.0, 1) if p0 is not None else None,
            wind_speed=wind_speed,
            wind_bearing=chain(
                inca_wind_bearing,
                now_value("dd"),
                arome.wind_bearing,
            ),
            wind_gust_speed=gust,
            precipitation_1h=rr_1h,
            precipitation_type=precipitation_type,
            precipitation_kind=derive_precipitation_type(precipitation_type, rate_mm_h),
            is_precipitating=is_precipitating(precipitation_type, nowcast_rate_mm_h),
            cloud_coverage=arome.cloud_coverage,
            global_radiation=inca_latest("GL")[0],
            snow_limit=arome.snow_limit,
            cape=arome.cape,
            weather_symbol=symbol,
            condition=derive_current_condition(
                precipitation_type=precipitation_type,
                precipitation_rate_mm_h=rate_mm_h,
                temperature=temperature,
                symbol=symbol,
                night=night,
            ),
        )


class GeoSphereAirQualityCoordinator(TimestampDataUpdateCoordinator[AirQualityData]):
    """Fetches the WRF-Chem pollutant forecast and the daily European AQI."""

    config_entry: GeoSphereNextConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GeoSphereNextConfigEntry,
        client: GeoSphereApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} air quality",
            update_interval=timedelta(minutes=AIR_QUALITY_INTERVAL_MINUTES),
        )
        self._client = client
        self.latitude: float = config_entry.data[CONF_LATITUDE]
        self.longitude: float = config_entry.data[CONF_LONGITUDE]

    async def _async_update_data(self) -> AirQualityData:
        try:
            chem = await self._client.get_timeseries(
                *DATASET_CHEM,
                parameters=CHEM_PARAMETERS,
                latitude=self.latitude,
                longitude=self.longitude,
            )
        except GeoSphereRateLimitError as err:
            raise UpdateFailed(
                f"GeoSphere rate limit hit: {err}", retry_after=err.retry_after
            ) from err
        except GeoSphereApiError as err:
            raise UpdateFailed(f"Air-quality update failed: {err}") from err

        # The daily AQI is a nice-to-have on top of the pollutant series;
        # its failure must not take the concentration sensors down.
        aqi: GeoSphereResponse | None = None
        try:
            aqi = await self._client.get_timeseries(
                *DATASET_CHEM_AQI,
                parameters=CHEM_AQI_PARAMETERS,
                latitude=self.latitude,
                longitude=self.longitude,
            )
        except GeoSphereApiError as err:
            _LOGGER.warning("AQI update failed, keeping pollutants only: %s", err)

        return self._process(chem, aqi)

    def _process(
        self, chem: GeoSphereResponse, aqi: GeoSphereResponse | None
    ) -> AirQualityData:
        now = dt_util.utcnow()
        data = AirQualityData(reference_time=chem.reference_time)

        if chem.timestamps:
            now_index = min(
                range(len(chem.timestamps)),
                key=lambda i: abs((chem.timestamps[i] - now).total_seconds()),
            )
            for key, parameter in CHEM_POLLUTANTS.items():
                setattr(data, key, chem.value_at(parameter, now_index))
                data.forecast[key] = list(
                    zip(chem.timestamps, chem.series(parameter), strict=True)
                )

        if aqi is not None:
            # Daily stamps are 00:00 UTC; match by local calendar day.
            today = dt_util.now().date()
            values: dict[int, int] = {}
            for ts, value in zip(aqi.timestamps, aqi.series("aqi"), strict=True):
                if value is not None:
                    values[(dt_util.as_local(ts).date() - today).days] = int(value)
            data.aqi_today = values.get(0)
            data.aqi_tomorrow = values.get(1)
            data.aqi_in_2_days = values.get(2)

        return data
