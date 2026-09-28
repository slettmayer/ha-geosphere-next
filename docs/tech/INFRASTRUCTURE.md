# Infrastructure

## Purpose
Document CI/CD, HACS distribution, and the automated release and dependency
workflows.

## Responsibilities
- The GitHub Actions workflows and what gates a merge.
- The automated release pipeline and versioning rules.
- Why a Dependabot merge produces no release, and its auto-merge.

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
- **ruff** — `pip install -r requirements_lint.txt` then `ruff check .` and
  `ruff format . --check`. The pin is exact, so a ruff release cannot change the
  verdict without a Dependabot PR.
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
`## X.Y.Z` section from `CHANGELOG.md` via `awk`, builds `geosphere_next.zip`
from `custom_components/geosphere_next/`, and creates a GitHub release with the
archive attached — skipping if the tag already exists. HACS then picks up the
new release. No manual tagging.

### The release archive (`zip_release`)
`hacs.json` sets `zip_release: true` and `filename: "geosphere_next.zip"`, so
HACS downloads that one asset from the release instead of fetching every file
through the GitHub API. Two constraints on how it is built:

- **The integration's files must sit at the archive root.** HACS does
  `zip_file.extractall(<config>/custom_components/geosphere_next)`, so a
  top-level `geosphere_next/` directory inside the zip would land as
  `custom_components/geosphere_next/geosphere_next/`. That is why the workflow
  `cd`s into the integration directory and zips `.`.
- **The asset name must equal `filename` exactly.** HACS requests that one name
  from the release and fails the download if it is absent. Renaming one without
  the other breaks every install.

The archive is attached in the same `gh release create` call, so a release can
never be published without it. That matters because the HACS action only checks
that `filename` is set when `zip_release` is true — it does **not** verify the
asset exists on the latest release, so a broken archive step would fail silently
at install time, never in CI.

The motive is measurement as much as speed: GitHub reports a `download_count`
per release asset, and that is the only install signal this project has.

Releases before 0.9.1 have no archive. Their tagged `hacs.json` has no
`zip_release`, so HACS falls back to the file-by-file download for them —
downgrading keeps working.

### Dependabot
`.github/dependabot.yml` opens weekly grouped PRs: `pip` on Mondays,
`github-actions` on Thursdays.
A Dependabot merge **does not produce a release**, and must not. Nothing it
updates ships: it touches `requirements_*.txt` and workflow files, the release
archive is built from `custom_components/geosphere_next/` alone, and
`manifest.json` declares `"requirements": []` (which Dependabot does not read in
any case). So the version is left alone, `release.yml` finds the tag already
exists and stops, and the update ships with the next real release.

A `dependabot-version-bump.yml` workflow used to bump the patch version on every
Dependabot PR, publishing releases that differed in their version string only —
each still prompting users to update and restart Home Assistant. Do not bring
it back.

### Dependabot Auto-merge (`dependabot-auto-merge.yml`)
On every Dependabot PR this enables auto-merge (squash), so the PR lands by
itself once `gate` passes; one that fails `gate` waits for a human. It uses a
GitHub App token rather than `GITHUB_TOKEN`, because a merge made with
`GITHUB_TOKEN` triggers no workflows and Validate would never run on `main`
afterwards.

The ruleset requires an up-to-date branch and auto-merge never updates one —
hence the two ecosystems on different days. A Dependabot PR left behind by a
feature merge needs `@dependabot rebase`. An action used only in `release.yml`
is not exercised before the merge; a breaking bump there surfaces on the next
real release.

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
- The auto-merge workflow needs `GH_ACTION_APP_CLIENT_ID` / `GH_ACTION_APP_PRIVATE_KEY`
  secrets, in both the Actions and Dependabot stores; the App needs Contents and
  Pull requests write. The client ID (`Iv23li…`) is not the numeric App ID —
  `create-github-app-token` deprecated `app-id`.

## Design Decisions
- Release is fully automated off the manifest version — the changelog is the
  source of release notes.
- Enforcement is CI-based; there are no git hooks.

## Known Risks
- `hacs/action@main` and hassfest `@master` are floating refs and can change
  between runs.
- The release depends on `manifest.json` and `CHANGELOG.md` staying in sync (the
  `## X.Y.Z` header must match exactly for `awk` extraction).
- A wrong archive name or layout is invisible to CI and only surfaces as a failed
  HACS install — keep `filename` in `hacs.json` and the zip step in `release.yml`
  in sync.

## Extension Guidelines
- Keep the `manifest.json` version and the top `CHANGELOG.md` header in sync in
  every PR.
- Add a new CI check as a job in `validate.yml` and to the `gate` job's `needs`.
