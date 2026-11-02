# Testing

## Purpose
Document the test framework, fixtures, patterns, and commands for the test suite.

## Responsibilities
- How to run the tests and what runs in CI.
- Fixture and mocking conventions.
- Test organization and naming.

## Non-Responsibilities
- CI workflow definitions and release automation — see [INFRASTRUCTURE.md](INFRASTRUCTURE.md).
- Code conventions — see [CONVENTIONS.md](CONVENTIONS.md).

## Overview

### Commands
- Install: `pip install -r requirements_test.txt`.
- Run: `python -m pytest tests/ -q` (CI uses `-v`).
- Lint/format: `ruff check . --fix && ruff format .` (CI runs the non-mutating
  `ruff check .` and `ruff format . --check`).

### Framework and configuration
- **pytest** via **pytest-homeassistant-custom-component**. `pyproject.toml` sets
  `testpaths = ["tests"]`, `pythonpath = ["."]`, `asyncio_mode = "auto"` (async
  tests need no marker), and disables the cache provider.
- **freezegun** (`freezer` fixture) freezes time for deterministic
  time-dependent assertions.

### Organization
- Test files track behavior areas, usually one per source module: `test_api.py`,
  `test_binary_sensor.py`, `test_condition.py`, `test_config_flow.py`,
  `test_coordinator.py`, `test_outlook.py`, `test_sensor.py`, `test_weather.py`.
  The exception is `test_air_quality.py`, which keeps the optional air-quality
  feature readable in isolation even though its sensors are declared in
  `sensor.py`.
  `test_explore_script.py` covers `scripts/explore_api.py`: that it loads the
  integration's `const.py` by path, without importing Home Assistant.
- `models.py` (plain dataclasses) and `entity.py` (the shared entity base) have no
  dedicated test file — both are exercised through the platform tests.
- Functions are `test_<behavior>` with descriptive snake_case names.
- Pure functions (`condition.py`) use `@pytest.mark.parametrize` table-driven
  cases; coordinator/integration tests arrange via a `_setup(hass, entry)` helper
  and assert against `coordinator.data`. `pytest.approx` for floats.
- Test comments tie assertions back to fixture values (e.g. which stamp an
  interval-ending `tp` or `10fg` value is read from).

### Fixtures and mocking (`tests/conftest.py`)
- `mock_config_entry` — a `MockConfigEntry` with lat/lon and `has_nowcast=True`.
- `mock_api` — registers recorded GeoJSON responses against per-dataset URL
  regexes on `AiohttpClientMocker` (`aioclient_mock`).
- `auto_enable_custom_integrations` — autouse fixture enabling custom-integration
  loading.
- `load_fixture(name)` — reads `tests/fixtures/*.json`.
- `stormy_arome(...)` — a *synthetic* copy of `arome.json` with a weather
  symbol (a thunderstorm code by default), the hour's `tp` and its CAPE patched
  into chosen hours. `sy` and `tp` go one stamp on, since both cover the
  interval ending at their stamp. The recording has no thunderstorm symbol, so
  the thunder `on` paths would otherwise be untestable; patching the recorded
  payload keeps every other field real.
- `stormy_ensemble(...)` — the same for `ensemble.json`: `cape_p90` at the
  hour's own stamp, `tp_p90` one stamp on. The recording peaks at 48 J/kg
  `cape_p90`.
- Recorded fixtures include the happy path (`arome.json`, `ensemble.json`,
  `nowcast.json`, `inca.json`, `chem.json`, `chem_aqi.json`), metadata files, and
  edge cases (`arome_out_of_domain.json`, `nowcast_out_of_domain.json`,
  `arome_prev_run.json`).
- The forecast fixtures (`arome*.json`, `ensemble.json`) are recorded by
  `scripts/explore_api.py --forecast-only` from `nwp-v2-1h-1km` /
  `ensemble-v2-1h-1km` at 46.63,14.15, requested from the run's own t0 so they
  keep the `null` first row of every interval-ending parameter. The script then
  shifts every stamp by one offset so that the run's `reference_time` lands on
  2026-07-15T12:00Z, the suite's frozen timeline that `nowcast.json`,
  `inca.json` and the chem fixtures were recorded on; values are untouched.
  `ensemble.json`'s `cape_p90` was added later from the same C-LAEF run
  (2026-11-01T03:00Z at 46.63,14.15; its `tp_p*` series matched the fixture
  value for value), so no other value moved. The script now requests it.
  Their weather is a wet November day (CAPE ≤ 29 J/kg, cloud 75–100 %), so the
  frozen 16:00Z row is index 4.

### What is covered
Config-flow validation and out-of-domain handling, API error mapping, coordinator
merging/stamping/fallback, the full `sy` → condition table (unknown codes and
night included), the current-condition precedence between observations and
the symbol, the thunderstorm outlook's symbol and ensemble signals (with
the ensemble's 12 h age bound and the binary sensor's unknown state), the
bounded ensemble fallback, sensor value extraction, weather
forecast assembly, and air-quality processing.

## Dependencies
- `pytest-homeassistant-custom-component` (pinned; tracks HA core).

## Design Decisions
- Recorded real API responses as fixtures keep tests deterministic without
  network access.
- Pure `condition.py` enables fast, exhaustive table-driven unit tests.

## Known Risks
- Fixtures are point-in-time snapshots; a GeoSphere response-shape change would
  need refreshed fixtures.
- Time-frozen tests assume the fixture timestamps stay consistent with the frozen
  clock. Outlook tests use two clocks (16:00Z and 18:00Z on 2026-07-15) so the
  1 h and 12 h horizons cannot be swapped unnoticed.
- `diagnostics.py` has no test coverage, so its coordinate redaction (`TO_REDACT`
  over `entry_data` and the forecast payload) is unverified by the suite.

## Extension Guidelines
- Add a test file mirroring any new source module, or extend the closest
  behavior-area file when the code lands in an existing module.
- Record a new fixture rather than hand-writing GeoJSON; wire it in `mock_api`.
- For pure logic, prefer a parametrized case in `test_condition.py`.
