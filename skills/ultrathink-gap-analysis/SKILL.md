---
name: ultrathink-gap-analysis
description: Use when reviewing a plan, spec section, or implementation for gaps — performs adversarial ≥20-gap analysis with categorized severity, fixes mechanical issues, and writes a convergence-tracked gap report
---

# Ultrathink Gap Analysis

Adversarial review that finds ≥20 concrete gaps, categorizes them, fixes what it can, and writes a structured gap report for convergence tracking.

## Procedure

1. **Detect mode:** `.md` target → plan review. Code files → implementation review.
2. **Read config:** If `.claude/workflow.json` exists, read `verify_commands` and `convergence` settings.
3. **Size check:** >500 lines → dispatch reviewer via Agent tool. ≤500 → analyze directly.
4. **Read prior report:** If `.claude/.gap-report.json` exists, note which gaps were already fixed.
5. **Baseline** (implementation mode only): run verify commands from config.
6. **Enumerate gaps:** ≥20 for artifacts >200 lines combined. Each gap needs: file:line reference, 1-sentence rationale, suggested action.
7. **Categorize:** 🔴-mechanical (auto-fix), 🔴-architectural (flag only), 🟡 Important, 🟢 Acceptable (defer to specific milestone), 🔵 Minor.
8. **Fix** all 🔴-mechanical + 🔵. Flag 🔴-architectural in report.
9. **Write `.claude/.gap-report.json`:**
   ```json
   {"pass": N, "critical_gaps": 0, "architectural_gaps": 1,
    "important_gaps": 2, "minor_gaps": 0, "deferred_gaps": 3,
    "total_gaps_found": 6, "gaps_fixed_this_pass": 4,
    "tests_green": true, "lint_clean": true, "converged": true}
   ```
   `critical_gaps`/`important_gaps` = remaining AFTER fixes, not total found.
10. **Verify** (implementation mode): run test + lint. Must be green.

## Convergence

Converged when: `critical_gaps == 0 AND (important_gaps <= 3 OR important_gaps <= previous * 0.5)` OR max iterations reached.

Persistent important gap across 3 passes → auto-downgrade to 🟢.
