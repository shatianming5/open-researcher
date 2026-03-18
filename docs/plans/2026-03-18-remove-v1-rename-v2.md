# Remove v1 Code & Rename v2 to open_researcher

**Date:** 2026-03-18
**Status:** Approved

## Goal

Delete all v1 code (`src/open_researcher/`, v1 tests), rename `open_researcher_v2` → `open_researcher`, unify CLI entry point.

## Context

- v1: 105 .py files + 10 Jinja2 templates + 97 test files
- v2: 10 .py files + 4 skill templates + 11 test files
- v2 has ZERO imports from v1 — fully decoupled

## Design

### Delete

| Target | Count | Notes |
|--------|-------|-------|
| `src/open_researcher/` | 105 .py + 10 .j2 | Entire v1 package |
| `tests/test_*.py` (v1) | ~25 | Top-level v1 tests |
| `tests/unit/` | ~34 | v1 unit tests |
| `tests/integration/` | ~3 | v1 integration tests |

### Rename

- `src/open_researcher_v2/` → `src/open_researcher/`
- `tests/v2/` → `tests/` (merge into top-level)
- All `from open_researcher_v2` → `from open_researcher`
- All `import open_researcher_v2` → `import open_researcher`

### pyproject.toml

- `open-researcher = "open_researcher.cli:app"` (sole entry point)
- Remove `open-researcher-v2`, `paperfarm` aliases
- Remove `[project.entry-points."open_researcher.plugins"]` block
- Remove `jinja2` from dependencies

### Keep

- `examples/`, `docs/`, `imgs/`, `README.md`, `LICENSE`

## Execution Order

1. Delete `src/open_researcher/`
2. Delete v1 tests
3. Move `src/open_researcher_v2/` → `src/open_researcher/`
4. Move `tests/v2/` → `tests/`
5. Global rename imports (`open_researcher_v2` → `open_researcher`)
6. Update pyproject.toml
7. Run tests, verify imports
