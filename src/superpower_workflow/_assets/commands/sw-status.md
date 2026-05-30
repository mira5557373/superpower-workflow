---
description: Quick sw run status — current phase, milestone progress, cumulative cost
---

Run `sw status` in the current project and summarize:

1. Active run id (if any)
2. Current milestone + phase
3. Milestones complete / total
4. Cumulative cost vs `max_total_budget_usd`
5. Any blocked locks (run `sw lock status` to check)

If no `sw run` is active, report "idle".
