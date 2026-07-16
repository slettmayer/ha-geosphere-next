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
    derive_condition,
    derive_current_condition,
    dew_point_from_t_rh,
    is_night,
    wind_from_components,
)
from .const import (
    AROME_PARAMETERS,
    CONF_CURRENT_INTERVAL,
    CONF_FORECAST_INTERVAL,
    CONF_HAS_NOWCAST,
    DATASET_AROME,
    DATASET_INCA,
    DATASET_NOWCAST,
    DEFAULT_CURRENT_INTERVAL_MINUTES,
    DEFAULT_FORECAST_INTERVAL_MINUTES,
    DOMAIN,
    INCA_LOOKBACK_HOURS,
    INCA_MAX_AGE_SECONDS,
    INCA_PARAMETERS,
    NOWCAST_PARAMETERS,
    PT_NO_PRECIPITATION,
)
from .models import (
    CurrentConditions,
    ForecastData,
    GeoSphereResponse,
    HourlyForecast,
)

_LOGGER = logging.getLogger(__name__)

type GeoSphereNextConfigEntry = ConfigEntry[GeoSphereNextData]


@dataclass(slots=True)
class GeoSphereNextData:
    """Runtime data stored on the config entry."""

    client: GeoSphereApiClient
    forecast: GeoSphereForecastCoordinator
    current: GeoSphereCurrentCoordinator


def _percent(value: float | None) -> float | None:
    """Normalize AROME tcc (verified 0-1 scale) to percent."""
    if value is None:
        return None
    return round(value * 100.0, 0)


def _diff(series: list[float | None], index: int) -> float | None:
    """Hourly value from a run-accumulated series: acc[i] - acc[i-1].

    Negative deltas (accumulation reset on a new model run) clamp to 0.
    Index 0 has no predecessor and returns None.
    """
    if index < 1 or index >= len(series):
        return None
    current, previous = series[index], series[index - 1]
    if current is None or previous is None:
        return None
    return max(round(current - previous, 2), 0.0)


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

    async def _async_update_data(self) -> ForecastData:
        try:
            response = await self._client.get_timeseries(
                *DATASET_AROME,
                parameters=AROME_PARAMETERS,
                latitude=self.latitude,
                longitude=self.longitude,
            )
        except GeoSphereRateLimitError as err:
            raise UpdateFailed(
                f"GeoSphere rate limit hit: {err}", retry_after=err.retry_after
            ) from err
        except GeoSphereApiError as err:
            raise UpdateFailed(f"AROME update failed: {err}") from err
        return self._process(response)

    def _process(self, response: GeoSphereResponse) -> ForecastData:
        now = dt_util.utcnow()
        hourly: list[HourlyForecast] = []
        first_future_index: int | None = None

        # Keep the in-progress hour so the forecast starts at the current hour
        # (matching OWM / Open-Meteo), comparing against the top of the hour
        # rather than the exact instant. Index 0 is still skipped: accumulated
        # parameters have no predecessor step, so its hourly precipitation is
        # unknowable (verified spike finding E-7).
        cutoff = now.replace(minute=0, second=0, microsecond=0)
        for i in range(1, len(response.timestamps)):
            ts = response.timestamps[i]
            if ts < cutoff:
                continue
            if first_future_index is None:
                first_future_index = i
            wind_speed, wind_bearing = wind_from_components(
                response.value_at("u10m", i), response.value_at("v10m", i)
            )
            gust_speed, _ = wind_from_components(
                response.value_at("ugust", i), response.value_at("vgust", i)
            )
            precipitation = _diff(response.series("rr_acc"), i)
            snow = _diff(response.series("snow_acc"), i)
            cloud = _percent(response.value_at("tcc", i))
            cape = response.value_at("cape", i)
            temperature = response.value_at("t2m", i)
            humidity = response.value_at("rh2m", i)
            hourly.append(
                HourlyForecast(
                    datetime=ts,
                    temperature=temperature,
                    templow=response.value_at("mnt2m", i),
                    temphigh=response.value_at("mxt2m", i),
                    humidity=humidity,
                    precipitation=precipitation,
                    snow=snow,
                    wind_speed=wind_speed,
                    wind_bearing=wind_bearing,
                    wind_gust_speed=gust_speed,
                    cloud_coverage=cloud,
                    cape=cape,
                    dew_point=dew_point_from_t_rh(temperature, humidity),
                    condition=derive_condition(
                        precipitation,
                        snow,
                        cloud,
                        cape,
                        gust_speed,
                        is_night(self.latitude, self.longitude, ts),
                    ),
                )
            )

        if not hourly:
            raise UpdateFailed("AROME response contained no future forecast hours")

        symbol = (
            response.value_at("sy", first_future_index)
            if first_future_index is not None
            else None
        )
        return ForecastData(
            reference_time=response.reference_time,
            grid_latitude=response.grid_latitude,
            grid_longitude=response.grid_longitude,
            hourly=hourly,
            current=hourly[0],
            snow_limit=(
                response.value_at("snowlmt", first_future_index)
                if first_future_index is not None
                else None
            ),
            weather_symbol=int(symbol) if symbol is not None else None,
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
        self._inca_fetched_at: datetime | None = None

    async def _async_update_data(self) -> CurrentConditions:
        nowcast: GeoSphereResponse | None = None
        if self.has_nowcast:
            try:
                nowcast = await self._client.get_timeseries(
                    *DATASET_NOWCAST,
                    parameters=NOWCAST_PARAMETERS,
                    latitude=self.latitude,
                    longitude=self.longitude,
                )
            except GeoSphereApiError as err:
                _LOGGER.warning("Nowcast update failed, falling back: %s", err)

        inca = await self._async_get_inca()

        arome = self._forecast.data.current if self._forecast.data else None
        if nowcast is None and inca is None and arome is None:
            raise UpdateFailed("No GeoSphere data source available")
        return self._merge(nowcast, inca)

    async def _async_get_inca(self) -> GeoSphereResponse | None:
        """Return the cached INCA slice, refreshing it when older than ~55 min."""
        now = dt_util.utcnow()
        if (
            self._inca is not None
            and self._inca_fetched_at is not None
            and (now - self._inca_fetched_at).total_seconds() < INCA_MAX_AGE_SECONDS
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
            self._inca_fetched_at = now
        except GeoSphereApiError as err:
            _LOGGER.warning("INCA update failed, falling back: %s", err)
        return self._inca

    def _merge(
        self, nowcast: GeoSphereResponse | None, inca: GeoSphereResponse | None
    ) -> CurrentConditions:
        now = dt_util.utcnow()
        arome = self._forecast.data.current if self._forecast.data else None
        forecast_data = self._forecast.data

        def now_value(name: str) -> float | None:
            if nowcast is None or not nowcast.timestamps:
                return None
            index = min(
                range(len(nowcast.timestamps)),
                key=lambda i: abs((nowcast.timestamps[i] - now).total_seconds()),
            )
            return nowcast.value_at(name, index)

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
        temperature = chain(
            now_value("t2m"),
            inca_latest("T2M")[0],
            arome.temperature if arome else None,
        )
        humidity = chain(
            now_value("rh2m"),
            inca_latest("RH2M")[0],
            arome.humidity if arome else None,
        )
        wind_speed = chain(
            now_value("ff"), inca_wind_speed, arome.wind_speed if arome else None
        )
        gust = chain(now_value("fx"), arome.wind_gust_speed if arome else None)
        cloud = chain(arome.cloud_coverage if arome else None)
        cape = arome.cape if arome else None

        p0, _ = inca_latest("P0")
        rr_1h, observed_at = inca_latest("RR")
        if rr_1h is None and nowcast is not None:
            # Sum the last four 15-min nowcast buckets at/before now.
            past = [
                value
                for ts, value in zip(
                    nowcast.timestamps, nowcast.series("rr"), strict=True
                )
                if ts <= now and value is not None
            ]
            rr_1h = round(sum(past[-4:]), 2) if past else None

        pt_raw = now_value("pt")
        precipitation_type = int(pt_raw) if pt_raw is not None else None
        nowcast_rr = now_value("rr")
        rate_mm_h = nowcast_rr * 4.0 if nowcast_rr is not None else (rr_1h or 0.0)
        night = is_night(self.latitude, self.longitude, now)

        return CurrentConditions(
            observed_at=observed_at or now,
            temperature=temperature,
            apparent_temperature=apparent_temperature(
                temperature, humidity, wind_speed
            ),
            dew_point=chain(now_value("td"), inca_latest("TD2M")[0]),
            humidity=humidity,
            pressure_hpa=round(p0 / 100.0, 1) if p0 is not None else None,
            wind_speed=wind_speed,
            wind_bearing=chain(
                now_value("dd"),
                inca_wind_bearing,
                arome.wind_bearing if arome else None,
            ),
            wind_gust_speed=gust,
            precipitation_1h=rr_1h,
            precipitation_type=precipitation_type,
            is_precipitating=(
                precipitation_type is not None
                and precipitation_type != PT_NO_PRECIPITATION
            ),
            cloud_coverage=cloud,
            global_radiation=inca_latest("GL")[0],
            snow_limit=forecast_data.snow_limit if forecast_data else None,
            cape=cape,
            weather_symbol=forecast_data.weather_symbol if forecast_data else None,
            condition=derive_current_condition(
                precipitation_type=precipitation_type,
                precipitation_rate_mm_h=rate_mm_h,
                temperature=temperature,
                humidity=humidity,
                wind_speed=wind_speed,
                cloud_coverage=cloud,
                cape=cape,
                gust_speed=gust,
                night=night,
            ),
        )
