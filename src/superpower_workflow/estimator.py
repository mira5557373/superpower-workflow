"""Cost and duration estimates from workflow config and historical telemetry."""

from __future__ import annotations

import json
from pathlib import Path

COST_PER_MS_SMALL = 8.0
COST_PER_MS_LARGE = 18.0
BUDGET_CAP_FRACTION = 0.15
MINUTES_PER_PHASE = {"plan": 30, "implement": 120, "review": 45, "push": 2}
OPTIMISTIC_FACTOR = 0.5


def _load_historical_costs(project_root: Path | None) -> list[float]:
    if project_root is None:
        return []
    telemetry_path = project_root / ".claude" / "telemetry.jsonl"
    if not telemetry_path.exists():
        return []
    costs: list[float] = []
    try:
        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "milestone_completed":
                    cost = event.get("cost_usd", 0.0)
                    if cost > 0:
                        costs.append(cost)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return costs


def estimate(config: dict, project_root: Path | None = None) -> dict:
    budgets = config.get("budgets", {})
    milestones = config.get("milestones", [])
    n = len(milestones)
    total_minutes = sum(MINUTES_PER_PHASE.values())

    historical = _load_historical_costs(project_root)
    if historical:
        avg_cost = sum(historical) / len(historical)
        cost_optimistic = round(n * avg_cost * 0.8, 2)
        cost_pessimistic = round(n * avg_cost * 1.3, 2)
    else:
        total_budget = sum(budgets.get(p, 0) for p in ("plan", "implement", "review", "push"))
        cap_based = total_budget * BUDGET_CAP_FRACTION
        avg_ms_cost = COST_PER_MS_SMALL if n <= 5 else COST_PER_MS_LARGE
        per_ms = min(avg_ms_cost, cap_based) if cap_based > 0 else avg_ms_cost
        cost_optimistic = round(n * per_ms * OPTIMISTIC_FACTOR, 2)
        cost_pessimistic = round(n * per_ms, 2)

    return {
        "milestone_count": n,
        "cost_optimistic": cost_optimistic,
        "cost_pessimistic": cost_pessimistic,
        "duration_optimistic_min": round(n * total_minutes * OPTIMISTIC_FACTOR),
        "duration_pessimistic_min": n * total_minutes,
    }
