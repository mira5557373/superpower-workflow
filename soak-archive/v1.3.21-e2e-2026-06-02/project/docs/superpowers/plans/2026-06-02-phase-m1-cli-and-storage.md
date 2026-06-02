# Phase M1 — CLI and Storage — TDD Implementation Plan

**Date:** 2026-06-02  
**Phase:** M1  
**Milestone:** phase-m1-cli-and-storage  
**Target:** Implement core todo CLI with atomic JSON storage

## Overview

Implement a minimal todo-cli application with:
- Click-based CLI (add, list, done, rm subcommands)
- Atomic JSON storage to `~/.todo/store.json`
- ≥90% test coverage on `todo/` package
- Clean ruff linting

## Architecture

```
todo/
  __init__.py       — Package exports (__all__)
  models.py         — Todo, TodoList, Status enum
  store.py          — JsonStore (atomic I/O, auto-mkdir, 0o600)
  cli.py            — Click CLI entry point
tests/
  conftest.py       — Shared fixtures (temp store path, clean teardown)
  test_models.py    — Todo, TodoList behavior
  test_store.py     — JsonStore atomic writes, edge cases
  test_cli.py       — All CLI subcommands via click.testing.CliRunner
```

## Tasks (26 total, TDD order)

### 1. Project Setup
- [ ] **Task 1.1: Create pyproject.toml** (feat)
  - Hatchling with Python 3.11+ requirement
  - Dependencies: click>=8.0, pytest, pytest-cov, ruff, freezegun
  - Entry point in [project.scripts]: `todo = "todo.cli:main"`
  - pytest config: cwd=project root, asyncio_mode not needed (sync only)
  - Coverage threshold in pytest config: min-percent 90

### 1.1 Test Infrastructure
- [ ] **Task 1.1.1: Create conftest.py — Fixtures** (test)
  - `tmp_store_path` fixture (uses tmpdir, returns path to ~/.todo/store.json)
  - `monkeypatch` HOME env var to tmp root
  - `clean_store` fixture that removes store after each test
  - Note: CliRunner will inherit monkeypatched HOME via sys.path isolation

### 2. Models Layer
- [ ] **Task 2.1: Write test_models.py — Status enum** (test)
  - Test Status.OPEN, Status.DONE string values
  - Test enum membership

- [ ] **Task 2.2: Implement models.py — Status enum** (feat)
  - StrEnum with OPEN="open", DONE="done"

- [ ] **Task 2.3: Write test_models.py — Todo dataclass** (test)
  - Test id (int), status (Status), created (ISO-8601 str), text (str) fields
  - Test __str__ output format: `<id> <status> <created> <text>`
  - Test dataclasses.asdict() round-trip for JSON serialization

- [ ] **Task 2.4: Implement models.py — Todo dataclass** (feat)
  - Use @dataclass with default_factory for timestamp
  - Implement __str__ matching spec format: space-separated fields

- [ ] **Task 2.5: Write test_models.py — TodoList** (test)
  - Test empty list init
  - Test add_todo(text: str) → Todo with sequential id (max+1, no reuse)
  - Test get_todo(id: int) → Todo or None
  - Test get_todos(include_done: bool) filtering
  - Test next_id generation (should be max(existing_ids)+1, or 1 if empty)
  - Test dataclasses.asdict() for TodoList

- [ ] **Task 2.6: Implement models.py — TodoList dataclass** (feat)
  - Keep todos as dict[id, Todo]
  - Implement next_id property (max+1, or 1 if empty)
  - Implement filtering logic in get_todos

### 3. Storage Layer (Atomic I/O)
- [ ] **Task 3.1: Write test_store.py — JsonStore basic I/O** (test)
  - Test store path derived from ~/todo/store.json
  - Test load() on empty/nonexistent → TodoList()
  - Test save() creates file with 0o600 perms
  - Test save() via .tmp → rename pattern

- [ ] **Task 3.2: Implement store.py — JsonStore** (feat)
  - Load: create parent dir if needed, return empty if file missing
  - Save: write to .tmp, atomic rename, set perms
  - Error handling for permission issues

- [ ] **Task 3.3: Write test_store.py — Edge cases** (test)
  - Test corrupted JSON → raise JsonDecodeError
  - Test double-save concurrency safety (sequential writes)
  - Test perms preservation after re-save

- [ ] **Task 3.4: Enhance store.py — Error handling** (feat)
  - Wrap JSON errors as StorageError or similar
  - Ensure 0o600 is set on creation and re-saves

### 4. CLI Layer
- [ ] **Task 4.1: Write test_cli.py — todo add** (test)
  - Use @freezegun.freeze_time("2026-06-02T10:00:00+00:00") for determinism
  - Test `todo add "hello"` appends with new id, status=open, ISO-8601 timestamp
  - Test `todo add ""` (empty text edge case)
  - Test multiple adds have sequential ids
  - Test output format: plain text or confirmation
  - Test error: unknown id exit code 1

- [ ] **Task 4.2: Implement cli.py — add subcommand** (feat)
  - Click command @cli.command()
  - Load store, create Todo with datetime.now(timezone.utc).isoformat(), save, output
  - Error handling and output message

- [ ] **Task 4.3: Write test_cli.py — todo list** (test)
  - Test `todo list` (default: open only)
  - Test `todo list --all` (both open and done)
  - Test output format: one todo per line, space-separated: `<id> <status> <created> <text>`
  - Test empty list (no output lines)
  - Test output matches Todo.__str__() format

- [ ] **Task 4.4: Implement cli.py — list subcommand** (feat)
  - @cli.command()
  - Load store, filter by status (include_done param), print each todo via str()
  - Output one per line

- [ ] **Task 4.5: Write test_cli.py — error message format** (test)
  - Test `todo done <unknown>` outputs error to stderr
  - Test `todo rm <unknown>` outputs error to stderr
  - Verify exit code is 1 (via result.exit_code)
  - Error message format: "Error: todo <id> not found" or similar

- [ ] **Task 4.6: Write test_cli.py — todo done** (test)
  - Test `todo done <id>` where status is open → flips to done, persists
  - Test `todo done <unknown>` exits 1 with error message
  - Test `todo done <already-done-id>` (spec says "flip", so done→open is expected; decide: succeed or fail? Plan: allow re-flipping)

- [ ] **Task 4.7: Implement cli.py — done subcommand** (feat)
  - Load, find todo (error if not found, exit 1), flip status, save
  - Status flips: open→done, done→open (idempotent via toggle)
  - Output confirmation or no output (decide per test)

- [ ] **Task 4.8: Write test_cli.py — todo rm** (test)
  - Test `todo rm <id>` removes (verify not in list after)
  - Test `todo rm <unknown>` exits 1 with error message
  - Test persistence after rm

- [ ] **Task 4.9: Implement cli.py — rm subcommand** (feat)
  - Load, find todo (error if not found, exit 1), delete, save
  - Output confirmation or no output

- [ ] **Task 4.10: Write test_cli.py — Integration tests** (test)
  - Sequence: add → list → done → list → rm → list
  - Verify state transitions work end-to-end
  - Test --help outputs for all commands
  - Test with multiple todos

- [ ] **Task 4.11: Implement cli.py — main entry point** (feat)
  - Wrap in @click.group(name='todo') with invoke_without_command=False
  - Main entry point function: def main()
  - Ensure all subcommands registered

### 5. Quality Gates
- [ ] **Task 5.1: Achieve ≥90% coverage** (test)
  - Run `pytest --cov=todo --cov-report=term-missing`
  - Identify any uncovered branches
  - Add missing edge case tests

- [ ] **Task 5.2: Lint and format cleanup** (chore)
  - `ruff check . --fix`
  - `ruff format .`
  - Verify no E, F, I, B, UP, SIM issues remain

- [ ] **Task 5.3: Final integration test** (test)
  - Run full test suite: `pytest -q`
  - Run coverage: `pytest --cov=todo`
  - Verify all tests pass

- [ ] **Task 5.4: Commit final M1** (chore)
  - Conventional commit message: `feat: implement phase-m1-cli-and-storage`
  - Include test coverage summary in commit body

## Key Decisions

1. **Storage path:** `~/.todo/store.json` (user home)
2. **Serialization:** Plain JSON, no schema versioning for M1
3. **CLI:** Click framework for simplicity and click.testing
4. **Timestamps:** ISO-8601 UTC from datetime.now(UTC).isoformat()
5. **IDs:** Sequential integers, next_id = max(existing) + 1

## Testing Strategy

- **Unit tests** for models (dataclass behavior, filtering)
- **Integration tests** for storage (I/O, atomicity, perms)
- **E2E tests** via CliRunner (all subcommands + edge cases)
- **Coverage target:** ≥90% on todo/ package

## Risk Mitigations

1. **Atomic writes:** Test double-save, verify .tmp pattern
2. **Permissions:** Verify 0o600 on creation and subsequent saves
3. **Unknown IDs:** Test exit code 1 and proper error message
4. **Timestamp determinism:** Use fixed datetime in tests via freezegun or fixture

## Acceptance Criteria

- [ ] All 26 tasks completed and committed individually
- [ ] `ruff check .` passes (no E, F, I, B, UP, SIM violations)
- [ ] `pytest -q` passes all tests (100% pass rate)
- [ ] `pytest --cov=todo` reports ≥90% coverage on todo/ package
- [ ] All CLI subcommands work as per spec: add, list, done, rm
- [ ] Atomic storage verified (via .tmp → rename pattern)
- [ ] Unknown ID errors exit code 1 with clear error message
- [ ] Timestamp output deterministic (via freezegun in tests)
- [ ] Storage permissions verified as 0o600
