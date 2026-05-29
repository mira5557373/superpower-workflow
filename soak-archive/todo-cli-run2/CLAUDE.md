# todo-cli

A tiny command-line todo manager. Python 3.11+, single-file JSON storage.

## Tech stack

- Python 3.11+
- Storage: JSON file at `~/.todo/store.json`
- Linting: ruff
- Testing: pytest with pytest-cov
- No external runtime dependencies

## Module map

```
todo/              # main package
  __init__.py
  storage.py       # JSON file I/O, atomic writes, schema
  models.py        # Todo dataclass / typed dict
  cli.py           # argparse CLI entry point
  __main__.py      # python -m todo support
tests/
  conftest.py      # shared fixtures (tmp storage paths)
  test_storage.py  # storage layer unit tests
  test_cli.py      # CLI integration tests
```

## Conventions

- Use conventional commits (feat:, fix:, test:, chore:, docs:)
- TDD: write failing tests first, then implement
- One todo per line output: `<id> <status> <created> <text>`
- ISO-8601 timestamps (UTC)
- Atomic writes: write to `.tmp` then rename
- File permissions `0o600` on store.json
- All commands deterministic given identical state

## Quality gates

- `ruff check .` clean
- `pytest -q` passes
- `pytest --cov` reports >= 90% coverage on `todo/` package

## Hard guardrails

- No tags, due dates, priorities, or recurring tasks
- No interactive mode
- No multi-user / network features
- No external runtime dependencies beyond stdlib
