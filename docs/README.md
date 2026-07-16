# Documentation Contributing Guide

> Rules for maintaining the AI-agent documentation. Follow these when adding, updating, or restructuring any `.md` files in this system. They apply to both human developers and AI coding agents.

## Why This Architecture Exists

Coding agents read `AGENTS.md` on every session (Claude Code loads it via the `@AGENTS.md` import in
`CLAUDE.md`; Cursor/Codex/Copilot read `AGENTS.md` directly). If it is bloated with detail, it wastes the
context window on content that may not be relevant to the task. The architecture solves this:

- **`AGENTS.md`** is loaded every time — must stay concise (index + critical one-liners). `CLAUDE.md` is a 3-line pointer that imports it; never edit `CLAUDE.md`.
- **`docs/tech/*.md`** — technical docs loaded on demand when a task touches that topic. `README.md` in that folder is the index.
- **`docs/domain/*.md`** — domain docs loaded on demand when a task touches that topic. `README.md` in that folder is the index.
- **Directory-scoped `AGENTS.md`** (with a sibling `CLAUDE.md` pointer) — loaded when working in that directory.

This gives the agent the right information at the right time without burning context on irrelevant detail.
CodeRabbit reviews against these docs and requests changes when they go stale — so keeping them current is
enforced, not optional.

## File Locations and Scope

| Location | Purpose | Loaded when |
|----------|---------|-------------|
| `/AGENTS.md` | Concise index: tech stack, critical one-liners, links to detail | Every session |
| `/CLAUDE.md` | 3-line pointer importing `AGENTS.md` for Claude Code | Every Claude Code session (never edit) |
| `/docs/tech/README.md` | Index of technical topic guides | Agent reads it for a technical task |
| `/docs/tech/*.md` | Detailed technical guides (one topic per file) | Agent reads it for that topic |
| `/docs/domain/README.md` | Index of domain topic guides | Agent reads it for a domain task |
| `/docs/domain/*.md` | Detailed domain guides (one topic per file) | Agent reads it for that domain |
| `<dir>/AGENTS.md` (+ `CLAUDE.md` pointer) | Conventions for a specific directory | Working in that directory |

### What goes where

- **Rule in `AGENTS.md`**: one-liner that fits a bullet (with a link to detail).
- **Detail in `docs/tech`**: anything technical needing explanation, examples, tables, checklists, or code blocks.
- **Detail in `docs/domain`**: anything domain-specific needing the same.
- **Directory-scoped `AGENTS.md`**: conventions that only apply in that directory.

### Domain doc layout (per-concept, with an index)

- Domain docs are **per-concept** — one entity, flow, lifecycle, or integration per file. A new concept is a
  **new file**, indexed in `docs/domain/README.md`.
- `docs/domain/OVERVIEW.md` is an **index**, not a detail dump: domain classification, an entity/concept
  catalog (one-liner + link), the glossary, cross-cutting decisions, and a **surfaces and audiences**
  section. When the change touches one concept, update that concept's file — don't bloat OVERVIEW.
- **Surfaces and audiences:** domain docs use business language (avoid class/method names) **except** the
  OVERVIEW "data/event surfaces and audiences" section, which names the real surfaces (here, the published HA
  entities and the consumed GeoSphere datasets) and who each serves — that *is* the domain boundary. Keep it
  current when a surface or its audience changes.

## Naming Conventions

- `/docs` files: `UPPERCASE-KEBAB-CASE.md` (e.g., `TECH-STACK.md`, `CONDITION-DERIVATION.md`).
- Directory guides: always `AGENTS.md` with a sibling `CLAUDE.md` pointer.
- Keep names descriptive and short (2-3 words max).

## File Size Guidelines

- **`/AGENTS.md`**: <150 lines — if larger, content is leaking in that belongs in `docs/`.
- **`/docs/**/*.md`**: <300 lines per file — split into focused files if larger.
- **Directory-scoped `AGENTS.md`**: <100 lines — tightly scoped.
- **Line length**: keep every line **under 200 characters** (org coding guideline; CodeRabbit flags it).
  Hard-wrap prose; indent bullet continuations; never wrap a table row — shorten the cell instead.

## Checklist: Adding a New Doc

1. Create the file in `/docs/tech` (technical) or `/docs/domain` (domain), following the naming convention.
2. Add an entry to that folder's `README.md` index.
3. If there is a critical rule, add a one-liner + link in `/AGENTS.md`.
4. Add cross-references from related docs.
5. Use relative links between `/docs/` files (e.g., `[DATASETS.md](DATASETS.md)`).
6. Use relative links from `/AGENTS.md` (e.g., `[ARCHITECTURE.md](docs/tech/ARCHITECTURE.md)`).

## Checklist: Updating an Existing Doc

1. Keep changes within the doc's defined scope.
2. If new content doesn't fit, create a new doc instead.
3. **Never move detailed content into `/AGENTS.md`** — add a one-liner + link.
4. Update cross-references if you rename sections or files.
5. Check that the `AGENTS.md` link still accurately describes the doc's purpose.

## Common Mistakes to Avoid

| Mistake | What to do instead |
|---------|-------------------|
| Inlining detailed content in `/AGENTS.md` | Create/update a doc in `docs/`, add a one-liner + link |
| Editing `/CLAUDE.md` | It is a generated pointer — edit `/AGENTS.md` instead |
| Creating a doc without indexing it | Always add it to the folder's `README.md` |
| Putting directory-specific rules in `/docs/` | Use that directory's `AGENTS.md` instead |
| Using absolute paths in links | Use relative paths so links work regardless of clone location |
| Duplicating content across docs | Put it in one place, cross-reference from others |
| Letting a doc grow unbounded | Split into focused files when it exceeds ~300 lines |
| A line over 200 characters | Hard-wrap it (org guideline; CodeRabbit flags it) |
| Bloating `docs/domain/OVERVIEW.md` with detail | Split into a per-concept file and index it; keep OVERVIEW an index |
