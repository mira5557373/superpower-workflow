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
4. **Stricter convergence:** `critical_gaps == 0 AND important_gaps == 0 AND tests_green AND lint_clean`.
5. Commit all fixes as single commit: `fix: post-impl review fixes for {milestone}`.
6. Write `.claude/.gap-report.json` with current gap counts.

## When to use

After `subagent-driven-development` completes a milestone's implementation, before pushing.
