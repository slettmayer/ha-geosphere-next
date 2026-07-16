# Infrastructure

## Purpose
Document CI/CD, HACS distribution, and the automated release and dependency
workflows.

## Responsibilities
- The GitHub Actions workflows and what gates a merge.
- The automated release pipeline and versioning rules.
- Dependabot auto-bump behavior.

## Non-Responsibilities
- How to run tests locally — see [TESTING.md](TESTING.md).
- Code style — see [CONVENTIONS.md](CONVENTIONS.md).

## Overview

There is no container/cloud infrastructure — the integration is distributed via
HACS and loaded into a Home Assistant instance. "Infrastructure" here is the CI
and release automation in `.github/workflows/`.

### Validate (`validate.yml`)
Runs on push to `main`, on every PR, weekly (`cron: 0 4 * * 1`), and manual
dispatch. Four parallel jobs plus an aggregate gate:
- **ruff** — `ruff check .` and `ruff format . --check`.
- **pytest** — `pip install -r requirements_test.txt` then `pytest tests/ -v`.
- **hassfest** — `home-assistant/actions/hassfest@master` (HA manifest/schema
  validator).
- **hacs** — `hacs/action@main` with `category: integration`.
- **gate** — `needs` all four; fails unless every result is `success`. This is the
  status check to require in branch protection.

Python comes from `.python-version` via `actions/setup-python`'s
`python-version-file`.

### Auto Release (`release.yml`)
Triggered by a successful **Validate** run on `main` (`workflow_run`). It reads
the version from `manifest.json`, tags `v{version}`, extracts the matching
`## X.Y.Z` section from `CHANGELOG.md` via `awk`, and creates a GitHub release —
skipping if the tag already exists. HACS then picks up the new release. No manual
tagging.

### Dependabot Version Bump (`dependabot-version-bump.yml`)
On Dependabot PRs, a GitHub App token is used to auto-increment the patch version
in `manifest.json` and prepend a `## X.Y.Z` changelog entry, so reviewers only
approve and merge. Idempotent (skips if the changelog already has the new
version).

### Versioning and changelog
Semver mapped to integration meaning (from `CONTRIBUTING.md`):
- **MAJOR** — breaking config-flow / entity / unit changes.
- **MINOR** — new sensor, option, or forecast capability.
- **PATCH** — derivation / coordinator / API-handling fixes.

Changelog format: flat bullets under `## X.Y.Z` headers, no `[Unreleased]`
section, no subcategory headers; optional `Fix:` / `Add:` / `Chore:` bullet
prefixes. Every changelog entry ships with a `manifest.json` version bump.

### Release flow (developer)
1. Feature branch from `main`; make changes.
2. `ruff check . && ruff format . --check`; `pytest tests/ -q`.
3. Bump `version` in `manifest.json`; add a `## X.Y.Z` changelog section.
4. Open a PR (squash-merge); Validate runs automatically.
5. On merge to `main`, Auto Release tags and publishes.

## Dependencies
- GitHub Actions; `manifest.json` `codeowners: ["@slettmayer"]`.
- Dependabot workflow needs `GH_ACTION_APP_ID` / `GH_ACTION_APP_PRIVATE_KEY`
  secrets.

## Design Decisions
- Release is fully automated off the manifest version — the changelog is the
  source of release notes.
- Enforcement is CI-based; there are no git hooks.

## Known Risks
- `hacs/action@main` and hassfest `@master` are floating refs and can change
  between runs.
- The release depends on `manifest.json` and `CHANGELOG.md` staying in sync (the
  `## X.Y.Z` header must match exactly for `awk` extraction).

## Extension Guidelines
- Keep the `manifest.json` version and the top `CHANGELOG.md` header in sync in
  every PR.
- Add a new CI check as a job in `validate.yml` and to the `gate` job's `needs`.
