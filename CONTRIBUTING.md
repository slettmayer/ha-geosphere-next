# Contributing

## Development Cycle

### Making Changes

1. Create a feature branch from `main`
2. Make your changes
3. Run linting locally: `ruff check . && ruff format . --check`
4. Run tests locally: `python -m pytest tests/ -q`
5. Bump `version` in `custom_components/geosphere_next/manifest.json`
6. Add a new `## X.Y.Z` section at the top of `CHANGELOG.md` with your changes
7. Create a PR — CI runs automatically (ruff, pytest, hassfest, HACS validation)
8. Merge PR (squash)
9. Release is created automatically after validation passes on `main`

### Releasing

Releases are fully automated. When a PR that changes the version in `manifest.json` is merged to `main`:

1. The `Validate` workflow runs (ruff, pytest, hassfest, HACS validation)
2. On success, the `Auto Release` workflow creates a git tag and GitHub release
3. Release notes are extracted from `CHANGELOG.md`
4. HACS picks up the new release

No manual tagging or release creation needed.

### Dependabot PRs

Dependabot PRs are auto-bumped: a workflow increments the patch version in `manifest.json` and prepends a changelog entry. Reviewers only need to approve and merge.

### Versioning

- **MAJOR** (1.0.0): Breaking changes (config flow changes, removed entities, changed entity IDs or units)
- **MINOR** (0.2.0): New features (new sensor, new config option, new forecast capability)
- **PATCH** (0.1.1): Bug fixes (condition-derivation fix, coordinator/differencing fix, API handling fix)

### Changelog Format

```
## X.Y.Z

- Description of change
- Another change
```

- No `[Unreleased]` section — every changelog entry ships with a version bump
- Version headers: `## X.Y.Z` (no brackets, no dates)
- Flat bullet points (no subcategory headers like `### Fixed`)
- Prefix bullets with context if helpful: `- Fix: ...`, `- Add: ...`

### Testing

- Tests use [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
  with recorded API fixtures in `tests/fixtures/`
- Install test dependencies: `pip install -r requirements_test.txt`
- Run: `python -m pytest tests/ -q`

### Code Style

- Enforced by [Ruff](https://docs.astral.sh/ruff/) — runs in CI
- Run locally: `pip install ruff && ruff check . --fix && ruff format .`
- See `pyproject.toml` for rule configuration
