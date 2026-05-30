---
name: convergence-coach
description: Offline analysis of why a milestone needed N ultrathink passes. Identifies whether the spec was the issue, the model was, or the convergence threshold was. Recommends config changes.
keywords: convergence, ultrathink, passes, plan-phase
triggers:
  - "/sw-convergence"
  - "too many ultrathink passes"
---

# Convergence coach

You're analyzing why a milestone's Phase A (plan) needed multiple ultrathink convergence passes.

## Instructions

1. **Read `.claude/reports/<milestone>/plan/` archives**. Note each `gap_report` event for the plan phase — `total_gaps_found` per pass, drop categories, convergence flag.
2. **Compute pass-over-pass attrition**: pass 1 found X gaps, pass 2 found Y, did Y < X? By how much?
3. **Classify the pattern**:
   - **Healthy convergence**: attrition >= 30% per pass, converges in <=3 passes.
   - **Slow convergence**: 10-30% attrition per pass, takes 4-5 passes. Often means spec ambiguity.
   - **No convergence**: attrition <10%, hit max_iterations. Almost always spec quality.
   - **Oscillation**: gaps go up then down then up. Often means model's thinking differs across passes — try lower effort or temperature.
4. **Recommend ONE intervention** per milestone:
   - Spec problem → recommend `sw lint-spec --strict` and specific spec sections to clarify.
   - Model problem → recommend trying a different model via `sw recommend-model`.
   - Convergence threshold problem → recommend tightening `convergence.max_iterations` (false-positive convergence) or raising it (genuinely needed more passes).

## Output

```
CONVERGENCE ANALYSIS — milestone <name>

Plan-phase passes: N
Pass-over-pass gap counts: [22, 14, 7, 3]
Attrition rate: 32% / 50% / 57%

Pattern: healthy / slow / none / oscillation

Diagnosis: <one sentence>

Recommendation: <ONE concrete config change>
```

One recommendation only. Internal users won't act on a list of 5.
