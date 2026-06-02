# todo-cli — Project Instructions

## What this project is

`todo-cli` is a minimal command-line todo manager. Python 3.11+, single-file JSON storage.

## Module map (dependency order)

```
todo/
  __init__.py       — Package exports
  store.py          — JsonStore class (atomic JSON I/O to ~/.todo/store.json)
  models.py         — Todo dataclass, TodoList, status enum
  cli.py            — Click-based CLI with subcommands (add, list, done, rm)
```

## Conventions

- **Python:** 3.11+, hatchling build
- **Framework:** Click for CLI
- **Storage:** Atomic JSON writes via .tmp → rename pattern
- **Testing:** pytest + pytest-cov, ≥90% coverage on todo/ package
- **Linting:** ruff with rules E, F, I, B, UP, SIM
- **Commits:** conventional format (feat:, fix:, test:, chore:)
- **Output:** Plain text, one todo per line: `<id> <status> <created> <text>`

## Hard guardrails

1. Storage file MUST be auto-created with `0o600` permissions (user only)
2. All writes MUST be atomic (write to .tmp, rename)
3. All commands MUST be deterministic
4. Unknown todo IDs MUST error with exit code 1
5. Output MUST be plain text, never JSON or other formats

## What's next

Implement Phase M1 (CLI and Storage) with TDD: write failing tests, implement, refactor, commit.
