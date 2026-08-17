# Changelog

## 0.10.0

- Change: AROME and the C-LAEF ensemble are no longer re-fetched while the run already held cannot have been superseded. AROME reruns every 3 hours and C-LAEF every 12, against a coordinator that ticks every 30 minutes by default, so most requests were returning byte-for-byte what was already in memory — the ensemble worst of all, at roughly 24 requests per useful one. The coordinator still wakes on the configured interval and re-derives everything that depends on the clock; it just skips the network call. Same freshness policy the INCA slice has always used, keyed on the run stamp rather than on the fetch time
- Change: scheduling the fetches against the model run times was considered and rejected. GeoSphere computes a run well after the hour it is stamped for and the lag is neither published nor constant — measured 2026-08-17 05:02 UTC, the newest AROME run was 00:00 UTC and the newest ensemble run was the *previous day's* 12:00 UTC — so a cron on 00/03/06 would fetch before the data exists. Waiting for the run stamp to change needs no estimate of the lag, self-corrects if GeoSphere shifts it, and leaves the interval option meaningful
- Change: a failing ensemble *re*-fetch now keeps the previous run instead of blanking the precipitation probability across the whole forecast. The percentiles are matched to AROME by timestamp, so a superseded run still has a value for every hour it covers; hours it has run past report no probability, as before. A first fetch that fails still yields none, there being nothing to fall back to. The fallback is bounded at two cadences: a superseded run is an older and worse forecast rather than the same answer, and nothing on display says which run a probability came from, so an endpoint that never recovers drops the probability instead of quietly serving a days-old run
- Fix: the German translations cover the storm-outlook entities again. `de.json` was missing all four outlook sensors and the whole binary-sensor section, so German users saw English fallback names for exactly the entities 0.9.0 added, sitting next to fully translated current-condition sensors. Note that German is one of the languages Home Assistant derives entity ids from, so a *new* install on a German instance now gets `sensor.geosphere_next_maximale_windboen_1_h` and the like; existing installs keep the ids already in their entity registry
- Add: a **Model run** sensor showing which AROME run the forecast comes from. The value was already parsed and stored but surfaced nowhere, so there was no way to tell a forecast waiting on GeoSphere's publication lag from a stuck integration. Diagnostic category, enabled by default, for the same reason as **Observation time**

## 0.9.3

- Bump dependency (Dependabot)

## 0.9.2

- Fix: the forecast now really does start at the hour already under way. Processing skipped the first step of the series and the API trims the forecast to the current hour, so that step *was* the in-progress hour — dropped ever since the behaviour was introduced. One hour of history is now requested, anchored to the top of the hour rather than to `now`: the API honours a `start` that lands exactly on a stamp but rounds a mid-hour one up to the next, so anchoring to `now` at 15:30 comes back at 16:00 with the in-progress hour already gone
- Fix: as a consequence, current cloud cover, CAPE and CIN — and the condition derived from them — are read from the hour actually in progress. `outlook.hour_at` could never match, so the current coordinator always fell back to the *next* forecast hour; at 14:30 it reported the 15:00 hour's sky. This is what the 0.9.0 entry "current cloud cover, CAPE and CIN now follow the clock" was meant to deliver
- Fix: the storm-outlook entities' 1-hour horizon covers the in-progress hour again, as the README describes. Their windows were silently one stamp short, so a thunderstorm forecast for the current hour could not be reported at all
- Fix: **behaviour change.** Every hourly row's precipitation, snow, wind gust and min/max temperature now describes the hour the row is stamped for, instead of the hour before it. AROME publishes those five as interval values covering the step that *ends* at the stamp — the metadata says so outright ("in the last forecast intervall"), and `rr_acc`/`snow_acc` are run-accumulations, so a delta spans the interval ending at its stamp — while `t2m`, `rh2m`, wind, cloud, CAPE and CIN are instantaneous at it. The two were being read at the same index, so a row could show rain that had already stopped and the previous hour's gust peak. Interval parameters now come from the following step. The last forecast hour is dropped in exchange, having no successor to read them from
- Fix: the current wind gust no longer reports the previous hour's peak. Same cause: the current-conditions merge takes its AROME gust from the in-progress hour's row, whose gust covered the hour before it. This only ever affected installations outside the nowcast grid, where there is no `fx` to prefer
- Fix: a `start` or `end` with a non-UTC offset is now converted to UTC before being sent to the API, which reads naive stamps as UTC. Nothing passes one today, so no behaviour changes; the conversion stops a future caller silently requesting a window shifted by its offset
- Add: an **Observation time** sensor showing which hour the current conditions actually describe. INCA publishes ~30 min after the hour it analyses and the previous slice is served until the next appears, so a reading can be ~90 min old while every other entity presents it as "now" — on a fast morning ramp that reads as the current temperature contradicting the forecast rather than trailing it. The value was already computed and stored; it had simply never been surfaced anywhere, not even in diagnostics. Diagnostic category, but enabled by default, since an entity nobody enables answers nobody's question
- Change: **behaviour change.** The convective-inhibition veto added in 0.9.0 is overridden when *observed* rain reaches downpour intensity (≥ 4 mm/h). The current condition takes its rain from INCA and the nowcast — measurements — while CAPE and CIN come from AROME's forecast for that hour; inhibition answers "can convection get started?", which a downpour has already settled. A modelled lid could therefore report a thunderstorm visibly in progress as plain `rainy`. Lighter rain does *not* override it: any observed precipitation counts as "precipitating", down to drizzle, and high CAPE under a strong lid with light frontal rain is a routine pattern rather than a storm — so below 4 mm/h the full gate still applies, as it does throughout the hourly forecast
- Fix: **behaviour change.** Precipitation probability moved with the amount. The C-LAEF percentiles are interval values just like `rr_acc` — GeoSphere documents them as "in the last forecast period" — but only the AROME fields were shifted, leaving every row's probability a stamp behind its own rain. A row could show 0 mm at 95 %, or rain at 0 %, with the probability describing an hour that had already passed
- Fix: `observed_at` now reports the stamp of whichever source supplied the *temperature*, at every rung, instead of mixing in whichever source happened to be present. Three ways it went wrong: an analysis with no `RR` reported the observation time as `now` while an hour-old temperature was on display; an analysis with `RR` but no `T2M` did the reverse, dating a current nowcast temperature to an hour-old slice; and outside the nowcast grid it claimed `now` for values from the forecast hour in progress, so at 14:59 the sensor read 14:59 for values describing 14:00. The one sensor meant to expose staleness was hiding it in one direction and inventing it in the other
- Fix: with the nowcast supplying the temperature, the Observation time sensor reports that 15-minute bucket's own stamp rather than `now` — a value no source ever states. It also can no longer report a time in the future: the AROME rung is clamped to the present
- Fix: a 15-minute nowcast bucket that rounds to 0.0 no longer reports 0 mm/h in the middle of a storm. The current precipitation rate took the matched bucket alone, so in the lull between cells — `pt` still reporting precipitation — the rate read 0 mm/h, starving both the `pouring` branch and the downpour override below and showing a storm in progress as plain `rainy`. Once `pt` says it is precipitating, the peak across the last 30 minutes of buckets is now used. INCA's hourly `RR` is deliberately not used for this: it is a total over the whole past hour, so reading it as an instantaneous rate would keep a shower that ended 40 minutes ago driving the condition
- Change: the ensemble probability is now keyed to the *preceding* stamp of the C-LAEF series instead of a hardcoded one-hour step. No behaviour changes on the current hourly grid — the two are identical there — but ensembles commonly coarsen along their horizon, and if C-LAEF ever did, the fixed step would have missed every forecast row past the break and blanked the probability across the whole forecast with nothing logged
- Docs: the documented staleness bound was "~75 min"; the publish cadence actually permits ~90 (measured: a 07:00Z analysis still being served at 08:32Z). README and `docs/domain/CURRENT-CONDITIONS.md` corrected, and the FAQ entry now explains the current-vs-forecast disagreement this causes. Preferring the 15-min nowcast when INCA is stale was considered and rejected — it was measured against TAWES stations to lag diurnal ramps by up to ±2 °C, which is worse in exactly this case

## 0.9.1

- Add: releases now carry a `geosphere_next.zip` asset and HACS installs from it (`zip_release`) instead of fetching every file individually through the GitHub API. Faster to install, and it makes installs countable — GitHub reports a download count per release asset, which is the only usage signal this project has. Nothing about the integration's behaviour changes and there is nothing to reconfigure
- Note: releases before 0.9.1 have no archive, and their tagged `hacs.json` has no `zip_release`, so HACS falls back to the file-by-file download for them — downgrading keeps working

## 0.9.0

- Add: storm-outlook entities — max wind gust for the next hour and the next 12 hours, next expected thunderstorm (timestamp), thunderstorm expected within the next hour (binary), and max CAPE for the next 12 hours (diagnostic, disabled by default). Horizons round up to whole hourly steps, so a "1 hour" window covers the in-progress hour plus the next one (an event up to ~2 h out), and `next_thunderstorm` can sit up to 59 min in the past while a storm is already under way — see the README
- Add: convective inhibition (`cin`) is now fetched from AROME and exposed as a diagnostic sensor (disabled by default)
- Change: **behaviour change.** Thunder derivation now requires weak convective inhibition (`cin > -50` J/kg) in addition to CAPE ≥ 1000 J/kg. High CAPE under a strong cap no longer produces `lightning` / `lightning-rainy`. A missing `cin` is treated as uncapped, matching previous behaviour
- Change: wind speed and wind gust sensors are now natively km/h. Displayed values are unchanged on metric systems; history is continuous
- Fix: the storm outlook no longer misses thundersnow or hours with missing cloud data — an hour also counts as a thunderstorm when the CAPE/CIN predicate holds and precipitation is forecast for it; dry high-CAPE afternoons still do not
- Fix: outlook windows are re-evaluated at every full hour, so a "next hour" value can no longer describe an hour that has already elapsed when the forecast interval is long
- Fix: `thunderstorm_expected_1h` reports `unknown` instead of `off` when the forecast window holds no usable hour, so a data gap is no longer indistinguishable from "no storm"
- Fix: the gust and CAPE outlook sensors no longer carry a `state_class`, keeping predicted values out of Home Assistant's long-term statistics
- Fix: the weather entity's hourly forecast no longer keeps already-elapsed hours between refreshes; the list is re-filtered to the current hour onward on every read and re-pushed to forecast subscribers at each hour boundary
- Fix: current cloud cover, CAPE and CIN — and the current condition derived from them — now follow the clock instead of the forecast fetch. They were read from the forecast hour that was in progress when the forecast was last fetched, so at the maximum 180-minute forecast interval they could be ~3 h old; they now update with every current-conditions refresh (15 min by default)

## 0.8.3

- Bump dependency (Dependabot)

## 0.8.2

- Bump dependency (Dependabot)

## 0.8.1

- Bump dependency (Dependabot)

## 0.8.0

- Add: hourly precipitation probability in the weather forecast, derived from GeoSphere's C-LAEF ensemble precipitation percentiles (`ensemble-v1-1h-2500m`). The API exposes only p10/p50/p90 — no member fractions — so the probability is a stepped, ensemble-backed estimate (0 / 30 / 70 / 95 %); see the README FAQ. Adds ~2 API requests/hour; an ensemble fetch failure degrades to no probability instead of breaking the forecast

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
