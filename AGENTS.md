# GeoSphere Austria Next
> Home Assistant custom integration for point weather forecast, current conditions, and optional air quality from the GeoSphere Austria Dataset API.

> **Editing this guide:** `AGENTS.md` is the single source of truth for project context, read by all AI
> coding agents and humans. Keep it concise — put detail in `docs/` and link it. When you change code that
> alters documented behavior, update the matching `docs/` file in the **same PR** (CodeRabbit enforces this
> — see [docs/README.md](docs/README.md)).

## Quick Reference
- **Build**: none — pure Python custom component distributed via HACS
- **Run**: load into Home Assistant (HACS custom repository, or copy `custom_components/geosphere_next/`)
- **Test**: `pip install -r requirements_test.txt && python -m pytest tests/ -q`
- **Lint**: `ruff check . --fix && ruff format .`

## Where to Find Things
| I need to... | Read |
|--------------|------|
| Understand the architecture | [ARCHITECTURE.md](docs/tech/ARCHITECTURE.md) |
| Write code that fits conventions | [CONVENTIONS.md](docs/tech/CONVENTIONS.md) |
| Know the tech stack | [TECH-STACK.md](docs/tech/TECH-STACK.md) |
| Write or run tests | [TESTING.md](docs/tech/TESTING.md) |
| Understand CI / release | [INFRASTRUCTURE.md](docs/tech/INFRASTRUCTURE.md) |
| Understand the weather domain | [docs/domain/](docs/domain/README.md) |

## Architecture Overview
Standard Home Assistant integration skeleton, all code flat in
`custom_components/geosphere_next/`. Internal layering: `api.py` (HTTP + GeoJSON
parsing) and `models.py` (dataclasses) form a `homeassistant`-free core;
`coordinator.py` fetches, caches, differences, and merges datasets into models;
`condition.py` derives HA conditions from physical parameters (also pure);
`const.py` catalogs datasets, parameters, and thresholds; `sensor.py` /
`weather.py` / `entity.py` are the HA platform surface; `config_flow.py` handles
onboarding and options. Three `DataUpdateCoordinator`s (forecast, current, air
quality) poll the GeoSphere Dataset API at independent intervals for one
configured lat/lon. See [ARCHITECTURE.md](docs/tech/ARCHITECTURE.md).

## Tech Stack
- Python 3.14; Home Assistant Core (min `2025.7.0`).
- aiohttp (API client), astral (day/night), voluptuous (config schema).
- Ruff (lint + format); pytest + pytest-homeassistant-custom-component.
- No runtime PyPI requirements; HACS-distributed. See [TECH-STACK.md](docs/tech/TECH-STACK.md).

## Core Conventions
- Keep `api.py`, `models.py`, and `condition.py` free of `homeassistant` imports (future PyPI extraction + testability).
- All datasets, parameters, and thresholds live in `const.py` — never inline literals.
- Classes use the `GeoSphere*` prefix; private helpers are `_`-prefixed; derived logic is `derive_*`.
- Sensors are declared as entity descriptions with a `value_fn`, read by one generic entity class per group (`GeoSphereSensor` / `GeoSphereAirQualitySensor`).
- Primary dataset failure raises `UpdateFailed`; secondary datasets (ensemble, AQI) degrade with a warning.
- Ruff-enforced: 4 spaces, double quotes, line length 88, rule set `E,W,F,I,UP,B,SIM,C4,RUF`. See [CONVENTIONS.md](docs/tech/CONVENTIONS.md).

## Business Domain
Samples GeoSphere Austria's gridded datasets (AROME forecast, C-LAEF ensemble,
INCA analysis/nowcast, WRF-Chem) at any coordinate and maps them to an HA weather
entity plus sensors. Current conditions merge INCA → nowcast → AROME with an
explicit per-field fallback chain; precipitation probability is a stepped value
derived from ensemble percentiles; the condition is derived from physical
parameters, not GeoSphere's proprietary symbol code. See
[docs/domain/OVERVIEW.md](docs/domain/OVERVIEW.md).

## Structural Risks
- `condition.py` duplicates HA `ATTR_CONDITION_*` string literals (to stay import-free) — could drift if HA renames a condition.
- The current coordinator holds a direct reference to the forecast coordinator (intentional coupling) — preserve it when refactoring.
- Dataset resource IDs are versioned; `hacs/action@main` and hassfest `@master` are floating CI refs.

## Detailed Guides
- [Technical Context](docs/tech/README.md) -- architecture, tech stack, conventions, testing, infrastructure
- [Domain Context](docs/domain/README.md) -- datasets, forecast, current conditions, condition derivation, air quality
