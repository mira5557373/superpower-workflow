---
name: cost-investigator
description: Diagnose why a milestone overshot its cost projection by >50%. Reads telemetry, computes per-phase deltas, identifies the spike, recommends specific config changes.
keywords: cost, budget, overrun, investigation, telemetry
triggers:
  - "/sw-cost-investigate"
  - "milestone cost overrun"
  - "why did this cost so much"
---

# Cost investigator

You're diagnosing a milestone that cost significantly more than expected.

## Instructions

1. **Read `.claude/telemetry.jsonl`** and identify the most recent milestone (look for `milestone_completed` events).
2. **Read `.claude/reports/<milestone>/` archives** for that milestone's raw data (gap reports, spec compliance, feature verification).
3. **Compute per-phase deltas**: actual cost vs estimator's per-phase ratio. Which phase spiked?
4. **Identify common cost spikes**:
   - **Plan phase spike**: usually means convergence loop ran more passes than usual. Look at `gap_report` events — was `total_gaps_found` high, low attrition?
   - **Implement phase spike**: usually means context churn. Look at `cache_hit_rate` (post-v1.1.6). If <0.8, context isn't being reused well — could be a too-large milestone scope.
   - **Review phase spike**: usually means many strict_mode_iteration events. The first implementation didn't pass compliance/verification, triggered fix loops.
   - **Spec compliance/verification overspend**: rare, usually means a spec change mid-milestone.
5. **Look at strict_mode_iteration events**: each iteration costs `strict_iteration_budget`. How many fired?
6. **Look at gap_curation_completed events**: if curator dropped many items but cost still spiked, the LLM might be over-producing gaps. Recommend tightening `convergence.max_iterations`.

## Output

A structured cost analysis:

```
COST OVERRUN REPORT — milestone <name>

Projected: $X
Actual:    $Y  (+Z%)

Phase breakdown:
  plan:        $a (projected $a', delta +%)
  implement:   ...
  review:      ...

Cost spike location: <phase>
Likely cause: <root cause>

Recommendations:
  1. ... (specific config change with rationale)
  2. ...
```

Be concrete. "Reduce budgets" is not a recommendation; "set `budgets.implement` to 15 (was 25); milestone size suggests medium preset" is.
