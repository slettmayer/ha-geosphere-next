# Tech Stack

## Purpose
Enumerate the languages, frameworks, libraries, and tooling used to build and
test this Home Assistant custom integration.

## Responsibilities
- List runtime and test dependencies and their role.
- Record the Python version and packaging/distribution model.

## Non-Responsibilities
- CI/CD and release automation — see [INFRASTRUCTURE.md](INFRASTRUCTURE.md).
- Code layering — see [ARCHITECTURE.md](ARCHITECTURE.md).
- Test patterns — see [TESTING.md](TESTING.md).

## Overview

### Language and runtime
- **Python 3.14** — pinned in `.python-version` (consumed by CI's
  `actions/setup-python` via `python-version-file`) and targeted by Ruff
  (`target-version = "py314"`). Every module starts with
  `from __future__ import annotations` and uses modern idioms (`X | None`
  unions, the `type` statement).

### Framework
- **Home Assistant Core** — the integration provides `weather` and `sensor`
  platform entities and uses HA's config-entry, coordinator, entity, device
  registry, and diagnostics APIs. Minimum HA version `2025.7.0` (`hacs.json`).

### Runtime libraries
- **aiohttp** — async HTTP client for the GeoSphere API (shared HA client
  session; 30 s timeout).
- **astral** — solar-elevation calculation for day/night condition classification.
- **voluptuous** — config-flow schema validation (HA selectors).
- (`homeassistant`, `aiohttp`, `astral`, `voluptuous` are all provided by the HA
  environment; `manifest.json` declares `"requirements": []` — no extra PyPI
  installs at runtime.)

### Test dependencies (`requirements_test.txt`)
- **pytest-homeassistant-custom-component** (pinned, tracks HA core) — brings
  pytest, `MockConfigEntry`, `AiohttpClientMocker`, `freezegun`, and the
  `enable_custom_integrations` fixture.
- **ruff** — linter + formatter.

### Tooling
- **Ruff** — lint + format; config in `pyproject.toml` (line length 88, rule set
  `E, W, F, I, UP, B, SIM, C4, RUF`, `E501` ignored). See
  [CONVENTIONS.md](CONVENTIONS.md).
- **hassfest** — HA's official manifest/schema validator (CI only).
- **HACS action** — validates the repo as a HACS integration (CI only).

### Packaging and distribution
- Distributed via **HACS** as a custom integration; no build step. The
  integration lives in `custom_components/geosphere_next/` with `manifest.json`
  as the entry point. `hacs.json` declares the display name and minimum HA
  version. `integration_type: service`, `iot_class: cloud_polling`.

## Dependencies
- External data source: GeoSphere Austria Dataset API (no key). See
  [../domain/DATASETS.md](../domain/DATASETS.md).

## Design Decisions
- `api.py` and `models.py` are deliberately free of `homeassistant` imports so
  they can be extracted into a standalone PyPI package later.
- No runtime PyPI requirements — everything needed is already in the HA
  environment.

## Known Risks
- The test dependency pin tracks HA core and must be bumped together with
  `.python-version`.
- CI uses floating action refs — see [INFRASTRUCTURE.md](INFRASTRUCTURE.md).

## Extension Guidelines
- Add a runtime dependency only by declaring it in `manifest.json`'s
  `requirements`; prefer libraries already shipped with HA.
- When bumping Python, update `.python-version`, Ruff `target-version`, and the
  test pin together.
