# todo-cli — Spec

A tiny command-line todo manager. Python 3.11+. Single-file storage (JSON).

## Functional requirements

- `todo add "<text>"` appends a new todo with a unique integer id, status `open`, and ISO-8601 timestamp.
- `todo list [--all]` prints todos. Default shows only `open`. `--all` includes `done`.
- `todo done <id>` flips status from `open` to `done`. Errors with exit 1 if id is unknown.
- `todo rm <id>` removes a todo permanently. Errors with exit 1 if id is unknown.

## Non-functional requirements

- Storage at `~/.todo/store.json` (auto-created with `0o600` permissions).
- Atomic writes (write to `.tmp`, rename).
- All commands deterministic — output identical across runs given identical state.
- All output is plain text, one todo per line: `<id> <status> <created> <text>`.

## Quality gates

- `ruff check .` clean
- `pytest -q` passes (write tests covering every CLI subcommand + storage edge cases)
- `pytest --cov` reports ≥ 90 % coverage on the `todo/` package

## Out of scope

- No tags, due dates, priorities, or recurring tasks.
- No interactive mode.
- No multi-user / network features.
