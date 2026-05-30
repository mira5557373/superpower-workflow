---
description: Summarize the most recent soak-archive run (cost, quality, curator attrition)
---

Look in `soak-archive/` for the most recent dated directory. For each trial in that archive:

1. Read `metrics.json` for cost, duration, status.
2. Read `telemetry.jsonl` and report:
   - Spec compliance: total / implemented / missing
   - Feature verification: total / verified / broken / manual_review
   - Curator: raw vs curated counts, attrition %, drops by category
   - Strict mode iterations (if any)
   - Cache hit rate per phase (post-v1.1.6)

Tabulate trials side-by-side. Then summarize: which config performed best on cost-per-quality? Recommend defaults for v1.2.x+.

Pull from `REPORT.md` if it exists — but verify the numbers from telemetry, don't just paraphrase.
