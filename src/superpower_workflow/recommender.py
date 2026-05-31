"""Model recommender from historical telemetry (T1.9.3 + v1.3.2 #20).

Reads .claude/telemetry.jsonl and produces a per-model quality/cost score so
internal users can see whether opus/sonnet/haiku is best for their workload.

Quality score (each in [0,1], higher is better):
  0.4 * spec_compliance_rate   (implemented / total_requirements)
  0.3 * (1 - strict_iter_rate) (1 - normalized strict iterations)
  0.2 * first_pass_rate        (milestones that completed with ZERO strict iters)
  0.1 * curator_health         (1 - excessive attrition penalty)

v1.3.2 #20 fix: previously `first_pass_rate = 1 - strict_iter_rate`, which
made the 0.3 and 0.2 terms collapse into a single 0.5-weighted signal.
Now `first_pass_rate` is computed independently as the fraction of
completed milestones with NO strict_mode_iteration events. The two signals
disagree when a model converges fast on some milestones but takes many
strict loops on others — exactly the contour the documented weights are
supposed to discriminate.

Cost score: simply $ per milestone (lower is better).

Output ranks models with at least 1 completed milestone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelStats:
    model: str = ""
    milestone_count: int = 0
    total_cost: float = 0.0
    avg_cost_per_milestone: float = 0.0
    spec_compliance_rate: float = 0.0
    strict_iter_rate: float = 0.0
    # v1.3.2 #20: first_pass_rate is now an independent signal — the share
    # of milestone_completed events with ZERO subsequent strict iterations.
    # Distinct from strict_iter_rate (which averages normalized iter counts).
    first_pass_rate: float = 0.0
    first_pass_milestones: int = 0  # numerator used during accumulation
    curator_attrition_avg: float = 0.0
    quality_score: float = 0.0


@dataclass
class RecommendationReport:
    models: list[ModelStats] = field(default_factory=list)
    recommended: str = ""
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "models": [m.__dict__ for m in self.models],
            "recommended": self.recommended,
            "rationale": self.rationale,
        }


def _read_telemetry(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return events


def _compute_stats(events: list[dict]) -> dict[str, ModelStats]:
    """Per-model aggregates from a telemetry stream."""
    by_run: dict[str, str] = {}
    for e in events:
        if e.get("type") == "run_started":
            by_run[e.get("run_id", "")] = e.get("model", "")

    stats: dict[str, ModelStats] = {}
    for run_id, model in by_run.items():
        if not model:
            continue
        s = stats.setdefault(model, ModelStats(model=model))

        ms_events = [
            e
            for e in events
            if e.get("type") == "milestone_completed" and e.get("run_id") == run_id
        ]
        s.milestone_count += len(ms_events)
        s.total_cost += sum(e.get("cost_usd", 0.0) for e in ms_events)

        sc_events = [
            e
            for e in events
            if e.get("type") == "spec_compliance_completed" and e.get("run_id") == run_id
        ]
        for sc in sc_events:
            total = sc.get("total_requirements", 0) or 1
            s.spec_compliance_rate += sc.get("implemented", 0) / total

        strict_events = [
            e
            for e in events
            if e.get("type") == "strict_mode_iteration" and e.get("run_id") == run_id
        ]
        # Normalize: each strict iter is a small quality penalty
        s.strict_iter_rate += min(len(strict_events) / 4.0, 1.0)

        # v1.3.2 #20: independent first-pass signal. Group strict iters by
        # milestone, then count milestones whose strict-iter count is zero.
        strict_by_ms: dict[str, int] = {}
        for se in strict_events:
            ms_name = se.get("milestone", "")
            strict_by_ms[ms_name] = strict_by_ms.get(ms_name, 0) + 1
        for me in ms_events:
            ms_name = me.get("milestone", "")
            if strict_by_ms.get(ms_name, 0) == 0:
                s.first_pass_milestones += 1

        cur_events = [
            e
            for e in events
            if e.get("type") == "gap_curation_completed" and e.get("run_id") == run_id
        ]
        for c in cur_events:
            s.curator_attrition_avg += c.get("attrition_pct", 0.0)

    # Finalize averages
    for s in stats.values():
        n = max(s.milestone_count, 1)
        s.avg_cost_per_milestone = round(s.total_cost / n, 2)
        s.spec_compliance_rate = round(s.spec_compliance_rate / n, 3)
        s.strict_iter_rate = round(s.strict_iter_rate / n, 3)
        # v1.3.2 #20: independent first-pass rate, not a function of strict_iter_rate.
        s.first_pass_rate = round(s.first_pass_milestones / n, 3)
        s.curator_attrition_avg = round(s.curator_attrition_avg / n, 1)

        curator_health = (
            1.0
            if 20.0 <= s.curator_attrition_avg <= 80.0
            else max(0.0, 1.0 - abs(s.curator_attrition_avg - 50.0) / 100.0)
        )
        s.quality_score = round(
            0.4 * s.spec_compliance_rate
            + 0.3 * (1 - s.strict_iter_rate)
            + 0.2 * s.first_pass_rate
            + 0.1 * curator_health,
            3,
        )
    return stats


def recommend(telemetry_path: Path) -> RecommendationReport:
    """Read telemetry, score models, return the highest quality_score per dollar.

    Recommends the model with highest `quality_score / avg_cost_per_milestone`
    ratio (efficiency). Ties broken by raw quality_score. When fewer than 3
    completed milestones exist for ANY model, returns an `insufficient_data`
    rationale.
    """
    events = _read_telemetry(telemetry_path)
    stats = _compute_stats(events)
    report = RecommendationReport(models=sorted(stats.values(), key=lambda s: -s.quality_score))

    if not report.models:
        report.rationale = "No model data available — run at least one milestone."
        return report

    eligible = [s for s in report.models if s.milestone_count >= 3]
    if not eligible:
        report.recommended = report.models[0].model
        report.rationale = (
            f"Insufficient data — only one model has >=3 milestones. "
            f"Provisional pick: {report.recommended}."
        )
        return report

    def efficiency(s: ModelStats) -> float:
        cost = s.avg_cost_per_milestone or 0.001
        return s.quality_score / cost

    best = max(eligible, key=efficiency)
    report.recommended = best.model
    report.rationale = (
        f"{best.model} has quality_score={best.quality_score:.3f} at "
        f"${best.avg_cost_per_milestone:.2f}/milestone over {best.milestone_count} "
        f"milestone(s) — best efficiency ratio."
    )
    return report
