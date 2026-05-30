---
description: Manually invoke the gap curator on an existing .gap-report.json
---

This is a debugging/exploration command. Take the contents of `.claude/.gap-report.json` (or `.claude/.gap-report.raw.json` if you want the pre-curation snapshot) and produce a curated version using the same prompt the orchestrator uses.

1. Read `.claude/.gap-report.json` (or `.gap-report.raw.json` if specified).
2. Read the spec at `config.spec`.
3. Read the focused diff for files referenced by the gaps.
4. Run the curator prompt manually (skill `superpowers:dispatching-parallel-agents` is overkill — do this inline).
5. Print before/after counts: raw_total, curated_total, attrition %, drops by category.
6. Show each dropped gap with the reason it was dropped.

Useful for: understanding why the curator made specific decisions when investigating quality.
