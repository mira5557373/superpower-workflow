---
description: Preview what sw run would do without spending any LLM budget
---

Run `sw run --dry-run` in the current project. Summarize:

1. The decomposed milestones with their `description` and `paths`
2. Estimated cost range (optimistic / pessimistic)
3. Per-phase budgets and convergence settings
4. Verify commands and quality gates that will run
5. Trust-but-verify config (gap_curator, strict_mode, spec_linter)

If the spec linter reports blockers, surface them prominently — the user should fix the spec before running.
