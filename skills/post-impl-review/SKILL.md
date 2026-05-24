---
name: post-impl-review
description: Use after completing implementation of a milestone or feature — reviews changed files for bugs, gaps, and needed enhancements with stricter convergence than ultrathink
---

# Post-Implementation Review

Reviews all files changed since the plan was committed. Stricter than ultrathink: requires `important_gaps == 0`.

## Procedure

1. Identify scope: `git diff --name-only <plan-commit>..HEAD`.
2. Run verify commands (test + lint). Fix if not green.
3. Follow ultrathink-gap-analysis procedure on the changed files.

3.5. **Test assertion quality:**
     Weak (flag): `assert True`, `assert result`, `assert x is not None`, `assert len(x)`
     Strong (pass): `assert result == expected_value`, `assert x.name == "foo"`

3.6. **Cross-module consistency:**
     - Same exception hierarchy (project-specific base exception subclasses)
     - Same import ordering (ruff-enforced but verify)
     - Same test structure (matching existing pattern — function-based or class-based)

3.7. **Full test suite:**
     Run ALL tests, not just for changed files. Flag regressions in existing tests.

3.8. **Package hygiene:**
     - `__init__.py` exports public API only — no internal implementation details
     - No circular imports — test: `python -c "import package_name"`
     - All pyproject.toml dependencies actually imported somewhere
     - Type hints on all public function signatures (exception: decorators/metaclasses)

3.9. **Commit strategy:**
     Single commit unless >10 files changed. If >10: group by category (security, observability, tests).

4. **Stricter convergence:** `critical_gaps == 0 AND important_gaps == 0 AND tests_green AND lint_clean`.
5. Commit all fixes as single commit: `fix: post-impl review fixes for {milestone}`.
6. Write `.claude/.gap-report.json` with current gap counts.

## When to use

After `subagent-driven-development` completes a milestone's implementation, before pushing.
