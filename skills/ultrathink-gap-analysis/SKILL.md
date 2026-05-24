---
name: ultrathink-gap-analysis
description: Use when reviewing a plan, spec, or implementation for gaps — performs adversarial gap analysis with categorized severity, fixes mechanical issues, and writes a convergence-tracked gap report
---

# Ultrathink Gap Analysis

## Procedure

1. **Read context:** Read CLAUDE.md. Read __init__.py and main module of each dependency.
2. **Detect mode:** .md target = plan review. Code files = implementation review.
3. **Read config:** Check .claude/workflow.json for verify_commands and convergence settings.
4. **Size check:** >500 lines combined → dispatch reviewer via Agent tool.
5. **Read prior report:** If .claude/.gap-report.json exists, note already-fixed gaps.
6. **Enumerate gaps:** Minimum scales with artifact size: min(20, max(10, total_lines / 20)). First pass = broad (all categories). Later passes = focused (categories with remaining gaps).
7. **Categorize + fix:** Fix in priority order: 🔴 first, then 🟡, then 🔵. Flag 🔴-architectural (don't auto-fix).
8. **Write gap report:** .claude/.gap-report.json with gap_summaries tagged [ultrathink].
9. **Verify:** (implementation mode) Run test + lint. Must be green.

For detailed heuristics, severity calibration, quality standards, and anti-patterns, read references/heuristics.md in this skill directory.

## Convergence

critical_gaps == 0 AND (important_gaps <= 3 OR important_gaps <= previous * 0.5) OR max iterations reached.
