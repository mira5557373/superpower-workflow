# Phase M3 — Quality Gates & Validation — Gate Lock

**Date:** 2026-06-02  
**Phase:** M3  
**Milestone:** phase-m3-quality-gates  
**Target:** Verify, document, and lock quality gates as enforcement checkpoint

## Context

Phase M2 (Test Coverage & Quality Validation) successfully delivered 98.06% coverage on the `todo/` package with 51 passing tests and clean linting. All spec-defined quality gates are met:

- ✓ `ruff check .` clean
- ✓ `pytest -q` passes (51 tests, all edge cases and CLI subcommands covered)
- ✓ `pytest --cov` reports 98.06% coverage (exceeds ≥90% requirement)

Phase M3 shifts from implementation to **validation and enforcement**. It follows the P1.M14 "Polish" pattern from e2e_agent: rather than add features or close coverage gaps, M3 documents the baseline and adds validation tests that verify quality gates remain enforced.

**Uncovered lines (73, 77 in cli.py):** These are Click framework scaffolding (`cli()` group decorator, `main()` entry point). The spec explicitly requires "write tests covering every CLI subcommand + storage edge cases" — not 100% coverage of framework infrastructure. Lines are intentional and documented as such.

## Architecture (Unchanged from M1/M2)

```
todo/
  __init__.py       — Package exports (__all__)
  models.py         — Todo, TodoList, Status enum (100% coverage)
  store.py          — JsonStore (100% coverage)
  cli.py            — Click CLI entry point (95.24% coverage, lines 73/77 intentional)
tests/
  conftest.py       — Shared fixtures (temp store path, clean teardown)
  test_models.py    — Todo, TodoList behavior (100% coverage)
  test_store.py     — JsonStore atomic writes, edge cases (100% coverage)
  test_cli.py       — All CLI subcommands via click.testing.CliRunner (95.24% coverage)
  test_validation.py — NEW: Quality gate verification tests (NEW)
```

## Tasks (7 total, TDD order)

### 1. Document Coverage Baseline

- [ ] **Task 1.1: Mark intentional coverage exemptions in cli.py** (chore)
  - Add `# pragma: no cover` comment on lines 73 (cli group decorator) and 77 (main entry point)
  - Example: Replace `def cli() -> None:` with `def cli() -> None:  # pragma: no cover`
  - Rationale: Click entry point scaffolding is framework infrastructure, not application logic
  - Commit: `docs: mark intentional coverage exemptions with pragma directives`

- [ ] **Task 1.2: Update README with quality gates section** (chore)
  - Add this exact section to README.md after "## What's next" or at end of file:
    ```markdown
    ## Quality Gates & Validation
    
    All commits must pass these automated checks:
    - **Linting:** `ruff check .` and `ruff format --check .` (no violations)
    - **Coverage:** `pytest --cov=todo` minimum ≥90% per spec (M2 baseline: 98.06%)
    - **Tests:** All 51+ tests passing via `pytest -q`
    
    Lines 73, 77 in cli.py use `# pragma: no cover` (Click entry point scaffolding, not logic).
    ```
  - Commit: `docs: add quality gates section to README`

### 2. Add Validation Tests

- [ ] **Task 2.1: Test ruff config is valid** (test)
  - Create tests/test_validation.py with `TestValidation` class
  - Implement `test_ruff_config_valid()`:
    - Verify `[tool.ruff]` exists in pyproject.toml
    - Parse and validate: line-length, select rules (E, F, I, B, UP, SIM)
    - Do NOT call subprocess; validate via file parsing
  - Rationale: Tests ruff config, not ruff itself (which is tested by CI)
  - Commit: `test: validate ruff configuration`

- [ ] **Task 2.2: Test coverage meets spec minimum** (test)
  - Implement `test_coverage_spec_minimum()` in test_validation.py:
    - Import coverage.py API (or parse JSON report if available)
    - Run coverage.report() and read total percentage
    - Assert coverage ≥90% (spec requirement per CLAUDE.md)
    - Rationale: Lock the minimum required; 98.06% is a bonus, not a floor
  - Commit: `test: lock coverage at spec minimum ≥90%`

- [ ] **Task 2.3: Test package has no circular imports** (test)
  - Implement `test_no_circular_imports()`:
    - Verify `import todo` succeeds (basic smoke test)
    - Verify all __all__ exports are accessible immediately after import
    - Rationale: Smoke test only; full circular import detection requires linter
  - Commit: `test: verify package imports cleanly`

- [ ] **Task 2.4: Test package __all__ is complete and correct** (test)
  - Implement `test_package_exports_complete()`:
    - Assert exact __all__ = {"Status", "Todo", "TodoList", "JsonStore"}
    - Verify each name is actually present in module namespace
    - Rationale: Prevent accidental export changes or leaks
  - Commit: `test: verify package __all__ completeness`

### 3. Final Acceptance & Commit

- [ ] **Task 3.1: Acceptance verification checklist** (chore)
  - Before final commit, verify all gates pass (non-executable checklist):
    - [ ] `ruff check .` returns 0
    - [ ] `ruff format --check .` returns 0
    - [ ] `pytest -q` passes all 55 tests (51 existing + 4 new validation)
    - [ ] `pytest --cov=todo` reports ≥90% coverage, 98.06% actual
    - [ ] `git diff todo/` shows only pragmas and comments, no logic changes
    - [ ] All validation tests pass locally
  - Commit: `chore: verify all M3 quality gates pass`

## Key Decisions

1. **M3 scope:** Gate verification and enforcement, NOT code completion
2. **Coverage baseline:** Lock spec minimum at ≥90% (per CLAUDE.md). 98.06% from M2 is documented as achievement, not enforcement floor
3. **Uncovered lines (73, 77):** Intentional (Click entry point scaffolding), marked with `# pragma: no cover`
4. **Validation tests:** Add 4 tests to test_validation.py (ruff config, coverage minimum, imports, exports)
5. **Subprocess testing:** Avoid fragile subprocess calls; validate config via file/API parsing instead
6. **No code logic changes:** Only pragma comments, documentation additions, and test additions

## Testing Strategy

- **Unit tests:** Models (100%) + Storage (100%) + CLI (95.24%) — locked, no changes
- **Integration tests:** All CLI subcommands via CliRunner — locked, no changes
- **Validation tests (NEW):** Gate verification (ruff, coverage, imports, exports)
- **Coverage:** Lock at ≥98% overall, ≥90% on todo/ package
- **Regression prevention:** All validation tests run as part of `pytest -q`

## Risk Mitigations

1. **Coverage regression:** Lock spec minimum (≥90%) with test_coverage_spec_minimum(); alert if below 90%
2. **Lint regressions:** Validate ruff config with test_ruff_config_valid() (config-based, not subprocess)
3. **Package breakage:** Verify circular imports and __all__ completeness with smoke tests
4. **Pragma directive maintenance:** `# pragma: no cover` survives refactoring better than line-number comments
5. **Subprocess fragility on Windows:** Avoid subprocess calls; use config validation instead
6. **Test count clarity:** Explicit: 51 existing + 4 new = 55 total

## Acceptance Criteria

- [ ] All 7 tasks completed and committed individually
- [ ] `ruff check .` passes (no E, F, I, B, UP, SIM violations)
- [ ] `pytest -q` passes all tests (55 total: 51 existing + 4 new validation)
- [ ] `pytest --cov=todo` reports ≥90% coverage (spec minimum per CLAUDE.md)
- [ ] test_validation.py added with 4 tests: ruff_config_valid, coverage_spec_minimum, no_circular_imports, package_exports_complete
- [ ] cli.py lines 73, 77 marked with `# pragma: no cover` (not line-number comments)
- [ ] README.md includes "Quality Gates & Validation" section with exact spec and exemptions
- [ ] No logic changes to todo/ package (only pragmas, docs, tests)
- [ ] All validation tests passing and verifying gates remain enforced

## Verification

1. **Run full test suite:** `pytest -q` → all pass (55+)
2. **Check coverage:** `pytest --cov=todo` → ≥98% overall, ≥90% on package
3. **Lint:** `ruff check . && ruff format --check .` → clean
4. **Verify no package changes:** `git diff todo/` → only comments/docs, no logic
5. **Validate gate tests:** `pytest tests/test_validation.py -v` → all 4 tests pass

## Summary

Phase M3 is a **gate enforcement milestone** that locks quality gates and adds validation infrastructure. Unlike M1 (implementation) and M2 (coverage), M3 focuses on **verification and documentation** — ensuring that quality standards are checked and enforced going forward. The outcome is a hardened, validated baseline ready for orchestrator integration.
