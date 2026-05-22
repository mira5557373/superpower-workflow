from __future__ import annotations

OPTIMISTIC_FACTOR = 0.5
MINUTES_PER_PHASE = {"plan": 30, "implement": 120, "review": 45, "push": 2}


def estimate(config: dict) -> dict:
    budgets = config.get("budgets", {})
    milestones = config.get("milestones", [])
    n = len(milestones)
    total_budget = sum(budgets.get(p, 0) for p in ("plan", "implement", "review", "push"))
    total_minutes = sum(MINUTES_PER_PHASE.values())
    return {
        "milestone_count": n,
        "cost_optimistic": round(n * total_budget * OPTIMISTIC_FACTOR, 2),
        "cost_pessimistic": round(n * total_budget, 2),
        "duration_optimistic_min": round(n * total_minutes * OPTIMISTIC_FACTOR),
        "duration_pessimistic_min": n * total_minutes,
    }
