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
- One test file per source module: `test_api.py`, `test_condition.py`,
  `test_config_flow.py`, `test_coordinator.py`, `test_sensor.py`,
  `test_weather.py`, `test_air_quality.py`.
- Functions are `test_<behavior>` with descriptive snake_case names.
- Pure functions (`condition.py`) use `@pytest.mark.parametrize` table-driven
  cases; coordinator/integration tests arrange via a `_setup(hass, entry)` helper
  and assert against `coordinator.data`. `pytest.approx` for floats.
- Test comments tie assertions back to fixture values (e.g. the exact
  `rr_acc[1] - rr_acc[0]` differencing math).

### Fixtures and mocking (`tests/conftest.py`)
- `mock_config_entry` — a `MockConfigEntry` with lat/lon and `has_nowcast=True`.
- `mock_api` — registers recorded GeoJSON responses against per-dataset URL
  regexes on `AiohttpClientMocker` (`aioclient_mock`).
- `auto_enable_custom_integrations` — autouse fixture enabling custom-integration
  loading.
- `load_fixture(name)` — reads `tests/fixtures/*.json`.
- Recorded fixtures include the happy path (`arome.json`, `ensemble.json`,
  `nowcast.json`, `inca.json`, `chem.json`, `chem_aqi.json`), metadata files, and
  edge cases (`arome_out_of_domain.json`, `nowcast_out_of_domain.json`,
  `arome_prev_run.json`).

### What is covered
Config-flow validation and out-of-domain handling, API error mapping, coordinator
merging/differencing/fallback, sensor value extraction, weather forecast
assembly, air-quality processing, and condition derivation.

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
  clock.

## Extension Guidelines
- Add a test file mirroring any new source module.
- Record a new fixture rather than hand-writing GeoJSON; wire it in `mock_api`.
- For pure logic, prefer a parametrized case in `test_condition.py`.
