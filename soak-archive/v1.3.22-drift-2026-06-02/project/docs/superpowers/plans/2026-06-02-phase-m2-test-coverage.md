# Phase M2 — Test Coverage & Quality Validation — TDD Completion Plan

**Date:** 2026-06-02  
**Phase:** M2  
**Milestone:** phase-m2-test-coverage  
**Target:** Achieve 100% coverage on cli.py, add edge case and stress tests, enhance test documentation

## Context

Phase M1 (CLI and Storage) was successfully implemented with 98.06% coverage on the `todo/` package, 51 passing tests, and clean ruff linting. Phase M2 completes the coverage story:

1. **Output coverage** — Add assertions on `done`/`rm` output messages (currently lines 73, 77 uncovered)
2. **Edge cases** — Parametrize status transitions, test special chars, long text, empty strings, whitespace
3. **Boundary testing** — Large datasets (1000+ todos), ID sequence edge cases
4. **Documentation** — Enhance test docstrings and add testing strategy guide
5. **Quality gates** — Verify ruff, pytest, coverage all green

## Current State

- **Test files:** test_cli.py (20 tests), test_models.py (17 tests), test_store.py (14 tests)
- **Coverage:** 98.06% overall, 95.24% on cli.py (missing lines 73, 77 — output echo calls)
- **Status:** All tests pass, ruff clean, ≥90% coverage requirement met
- **Strengths:** Tests are well-organized (TestClass groups), fixtures reusable, spec requirements covered
- **Gaps to address:**
  - Output assertions missing for `done` and `rm` commands (legitimate coverage gap)
  - No parametrized tests (tests are correct but could be clearer)
  - Limited edge case coverage (empty strings, long text, special characters tested individually, not systematically)
  - No stress/boundary tests (large datasets, ID sequence edge cases)

## Architecture (Unchanged from M1)

```
todo/
  __init__.py       — Package exports (__all__)
  models.py         — Todo, TodoList, Status enum (100% coverage)
  store.py          — JsonStore (100% coverage)
  cli.py            — Click CLI entry point (95.24% coverage)
tests/
  conftest.py       — Shared fixtures (temp store path, clean teardown)
  test_models.py    — Todo, TodoList behavior (100% coverage)
  test_store.py     — JsonStore atomic writes, edge cases (100% coverage)
  test_cli.py       — All CLI subcommands via click.testing.CliRunner (95.24% coverage)
```

## Tasks (8 total, TDD order)

### 1. Output Assertions — Fix Coverage Gap

- [ ] **Task 1.1: Add output assertions to done/rm tests** (test)
  - Add assertion to test_done_flips_status: `assert "Updated:" in result.output` and `assert str(todo) in result.output`
  - Add assertion to test_rm_removes_todo: `assert "Removed:" in result.output` and `assert str(todo) in result.output`
  - Verify cli.py lines 73, 77 now covered by running `pytest --cov=todo --cov-report=term-missing`
  - Target: 100% coverage on cli.py

### 2. Parametrized Status Transitions

- [ ] **Task 2.1: Parametrize status transition tests** (test)
  - Convert test_done_flips_status into parametrized test with scenarios: open→done, done→open
  - Use `@pytest.mark.parametrize("initial_status,final_status", [...])`
  - Verify all status transitions work correctly
  - Commit: `test: parametrize done status transitions`

### 3. Edge Case Coverage — Text Input

- [ ] **Task 3.1: Add edge case tests for text input** (test)
  - Test very long text (1000 chars): verify it's stored and displayed correctly
  - Test special characters: quotes, newlines, emoji (if supported)
  - Test whitespace-only text: `"   "`, `"\t"`
  - Test leading/trailing spaces: verify preserved in output
  - Add to test_cli.py or parametrize in TestCliAdd
  - Commit: `test: add edge case coverage for text input`

### 4. Boundary Testing — Large Datasets & ID Sequences

- [ ] **Task 4.1: Add boundary tests for large datasets** (test)
  - Add test to test_store.py: save/load 1000 todos, verify no data loss
  - Verify performance acceptable (< 1 second)
  - Commit: `test: add large dataset boundary test`

- [ ] **Task 4.2: Add ID sequence boundary tests** (test)
  - Test ID sequence with 1000+ operations: verify next_id always max+1
  - Test deletion of non-sequential IDs (1, 3, 5, ...) then re-add: verify correct ID assignment
  - Add to test_models.py or test_cli.py
  - Commit: `test: add ID boundary tests`

### 5. Documentation & Verification

- [ ] **Task 5.1: Enhance test docstrings** (chore)
  - Improve docstrings for all test functions (already good, just add detail)
  - Ensure each includes: what is tested, expected behavior, edge cases if applicable
  - Template: `"""Test <feature>. Verify <behavior>."""`
  - Commit: `test: enhance test docstrings for clarity`

- [ ] **Task 5.2: Verify all quality gates** (chore)
  - Run `pytest --cov=todo --cov-report=term-missing` → verify 100% on cli.py, ≥98% overall
  - Run `ruff check .` → must be clean
  - Run `pytest -q` → all tests pass (target 60+ tests)
  - Verify no unintended code changes: `git diff todo/` should be empty
  - If any gaps, iterate Tasks 1–4
  - Commit: `chore: verify all M2 quality gates pass`

### 6. Final Documentation & Commit

- [ ] **Task 6.1: Document test strategy** (chore)
  - Create `docs/testing-strategy.md`:
    - Test structure (unit/integration/E2E)
    - Coverage model and thresholds
    - How to run tests locally
    - Gap analysis from Phase M2 (output assertions, edge cases, boundary tests)
  - Commit: `docs: add testing strategy guide`

- [ ] **Task 6.2: Final M2 completion commit** (chore)
  - Verify all previous commits are made
  - Run full test suite: `pytest -q`
  - Run coverage: `pytest --cov=todo`
  - Run lint: `ruff check .`
  - All green ✓
  - Final summary: task count, coverage, gaps closed

## Key Decisions

1. **Coverage target:** Achieve 100% on cli.py, maintain 98%+ overall
2. **Output assertions:** Explicitly verify done/rm confirmation messages (currently uncovered)
3. **Parametrization:** Use for status transitions (clarity, not necessity)
4. **Edge cases:** Text input (long, special chars, whitespace), ID sequences (1000+)
5. **Boundary tests:** Large datasets (1000+ todos), ID sequence edge cases

## Testing Strategy

- **Unit tests:** Models (status, todo, todolist) — 100% coverage ✓
- **Integration tests:** Storage (I/O, atomicity, perms) — 100% coverage ✓
- **E2E tests:** CLI (all subcommands, workflows, error cases) — add output assertions
- **Edge cases:** Text input (long, special chars, whitespace), large datasets
- **Coverage:** ≥90% threshold (required), ≥98% target, 100% on cli.py (goal)

## Risk Mitigations

1. **Uncovered output branches:** Add explicit result.output assertions to existing done/rm tests (Task 1.1)
2. **Edge case coverage:** Systematize parametrization for status transitions (Task 2.1)
3. **Large dataset robustness:** Add stress tests for 1000+ todos (Task 4.1)
4. **ID sequence edge cases:** Test deletion patterns and re-addition (Task 4.2)
5. **Regression prevention:** Run pytest after each task commit

## Acceptance Criteria

- [ ] All 8 tasks completed and committed individually
- [ ] `ruff check .` passes (no E, F, I, B, UP, SIM violations)
- [ ] `pytest -q` passes all tests (100% pass rate, 60+ tests)
- [ ] `pytest --cov=todo` reports 100% coverage on cli.py, ≥98% overall
- [ ] Output assertions added to done/rm tests (cli.py lines 73, 77 covered)
- [ ] Edge cases covered: long text, special characters, whitespace, large datasets, ID boundaries
- [ ] Documentation: `docs/testing-strategy.md` explains test model and coverage approach
- [ ] No functionality changes to todo/ package (only tests and documentation)

## Verification

1. **Run full test suite:** `pytest -q` → all pass
2. **Check coverage:** `pytest --cov=todo` → ≥98%
3. **Lint:** `ruff check .` → clean
4. **Format:** `ruff format --check .` → no changes needed
5. **Verify no code changes:** `git diff --stat todo/` → only test files modified
