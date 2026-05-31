---
name: code-quality-loop
description: Invoke when Phase C ends but quality gates (lint, bandit, radon, pip-audit) still report failures. Loops focused fixes until gates pass or attempts exhausted.
keywords: quality, gates, bandit, radon, lint, fix-loop
triggers:
  - "/sw-quality-fix"
  - "fix quality gate failures"
---

# Code quality loop

You are fixing quality-gate failures after Phase C of a milestone.

## Context

- `quality_gates` block in `.claude/workflow.json` lists shell commands per gate (lint, sast, dep_scan, complexity, type_check).
- Each gate has been run and produced a result in `.claude/.quality-gate-results.json`.
- You're invoked when at least one gate reports `passed: false`.

## Instructions

1. **Read `.claude/.quality-gate-results.json`.** Identify failing gates and capture the `detail` field per gate.
2. **For each failing gate, fix the SPECIFIC issues it flagged** — not unrelated cleanup:
   - **lint** (ruff/eslint/clippy): apply auto-fixes (`ruff check --fix`, `eslint --fix`) first; fix remaining errors manually.
   - **sast** (bandit/gosec): every finding needs either a fix, a `# noqa: ...` with justification comment, or addition to the project's suppression file.
   - **dep_scan** (pip-audit/npm audit/cargo audit): update affected packages; if no fix available, document the risk in `SECURITY.md` and add to `quality_gates` exception list.
   - **complexity** (radon): refactor named functions only. Don't reformat unrelated code.
   - **type_check** (mypy/tsc): add missing annotations or fix existing ones. Don't blanket `# type: ignore`.
3. **Commit fixes per gate** with conventional-commit messages: `fix(security): remediate bandit B608` etc.
4. **Re-run the gate command** to verify the fix.
5. **Cap effort**: stop after `validation.strict_iteration_budget` (default $8.0) — don't burn the milestone budget chasing edge cases.

## What NOT to do

- Don't refactor for "code quality" beyond what gates flagged.
- Don't change quality gate commands themselves.
- Don't bypass with `# noqa` / `# type: ignore` without writing a 1-line justification.
- Don't touch files unrelated to the failing gates.
