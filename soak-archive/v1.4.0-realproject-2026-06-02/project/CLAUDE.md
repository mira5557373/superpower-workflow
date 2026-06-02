# shrt — URL Shortener CLI Project Instructions

## What this project is

`shrt` is a minimal command-line URL shortener in Python 3.11+. Single-file JSON storage with atomic writes and deterministic base62 hashing. Full spec: `spec.md`.

## Architecture at a glance

- **Core:** Python package `shrt/` with types, storage layer, and hash computation
- **Storage:** StoreBackend protocol + JsonStore implementation (atomic writes, auto-creation)
- **CLI:** Click-based command routing (add, resolve, list, rm, stats)
- **Data:** Single JSON file at `~/.shrt/store.json` with schema versioning

## Module map (dependency order)

```
shrt/
  __init__.py       — Package exports
  types.py          — Entry (dataclass), ShortCode (NewType), schema versioning
  hash.py           — base62_encode, base62_decode, hash_url (deterministic 6-char)
  storage.py        — StoreBackend protocol, JsonStore implementation
  cli.py            — Click commands (add, resolve, list, rm, stats)
```

## Conventions

- **Internal contracts:** `@dataclass` (no runtime validation needed)
- **Type annotations:** Full coverage, PEP 561 compliance
- **Enums/types:** Plain dataclasses and NewType (no Pydantic needed for internal types)
- **Schema versioning:** `SCHEMA_VERSION = 1` in types.py
- **Commits:** Conventional format (`feat:`, `test:`, `fix:`, `chore:`, `style:`, `refactor:`)
- **Testing:** TDD (red → green → commit). pytest with 90%+ branch coverage
- **Linting:** ruff with rules E, F, I, B, UP, SIM. 88-char line length
- **Dependencies:** click>=8.0, pytest, pytest-cov (minimal)
- **Build:** hatchling

## Hard guardrails (from spec)

1. All writes MUST be atomic (write to `.tmp`, fsync, os.rename)
2. Storage permissions MUST be `0o600` (user read/write only)
3. All output MUST be plain text (no ANSI colors, support piping)
4. All behavior MUST be deterministic (same input → same output, always)

## Milestones (9 total)

- **p1-m1-core-types-storage:** Core types (Entry, ShortCode), schema versioning, base62 computation
- **p1-m2-storage-layer:** StoreBackend protocol, JsonStore with atomic writes
- **p1-m3-add-command:** URL validation, alias validation, add subcommand
- **p1-m4-resolve-command:** Resolve subcommand with error handling
- **p1-m5-list-command:** List subcommand with limit and sorting
- **p1-m6-rm-command:** Remove subcommand with permanent deletion
- **p1-m7-stats-command:** Stats subcommand with time-based queries
- **p1-m8-cli-main:** Main CLI entry point and routing
- **p1-m9-quality-gates:** Ruff verification, 90% coverage, comprehensive tests

## When implementing new milestones

- Follow existing patterns in the codebase
- New modules go in `shrt/`. Tests go in `tests/test_<module>.py`
- Run `pytest -q` and `ruff check . && ruff format --check .` before committing
- Use conventional commits with present-tense verbs
- Never modify behavior without tests first (TDD)
