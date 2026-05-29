"""Cost and duration estimates from workflow config and historical telemetry."""

from __future__ import annotations

import json
from pathlib import Path

# Calibrated from a real soak (2026-05-29): 1 small milestone, opus, $7.00 total
# including trust-but-verify ($0.83 / 12% overhead).
# Historical avg from prior runs (35 milestones, $665): ~$19/milestone on opus.
COST_PER_MS_SMALL = 8.0  # ≤5 milestones (each milestone tends to be wider)
COST_PER_MS_LARGE = 18.0  # >5 milestones (each tends to be narrower but more of them)

# Optimistic = pessimistic × OPTIMISTIC_FACTOR. Previously 0.5 (way too aggressive —
# real soak landed at the pessimistic end).
OPTIMISTIC_FACTOR = 0.7

# Overhead added when trust-but-verify (spec_compliance or feature_verification)
# is enabled. Measured: $0.83 / $6.17 = 13.5% on the 2026-05-29 soak.
TRUST_BUT_VERIFY_OVERHEAD = 0.15

MINUTES_PER_PHASE = {"plan": 30, "implement": 120, "review": 45, "push": 2}


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


def _trust_but_verify_enabled(config: dict) -> bool:
    validation = config.get("validation", {})
    return bool(
        validation.get("spec_compliance", False) or validation.get("feature_verification", False)
    )


def estimate(config: dict, project_root: Path | None = None) -> dict:
    milestones = config.get("milestones", [])
    n = len(milestones)
    total_minutes = sum(MINUTES_PER_PHASE.values())

    historical = _load_historical_costs(project_root)
    if historical:
        avg_cost = sum(historical) / len(historical)
        cost_pessimistic = round(n * avg_cost * 1.3, 2)
        cost_optimistic = round(n * avg_cost * 0.8, 2)
    else:
        per_ms = COST_PER_MS_SMALL if n <= 5 else COST_PER_MS_LARGE
        if _trust_but_verify_enabled(config):
            per_ms *= 1.0 + TRUST_BUT_VERIFY_OVERHEAD
        cost_pessimistic = round(n * per_ms, 2)
        cost_optimistic = round(cost_pessimistic * OPTIMISTIC_FACTOR, 2)

    return {
        "milestone_count": n,
        "cost_optimistic": cost_optimistic,
        "cost_pessimistic": cost_pessimistic,
        "duration_optimistic_min": round(n * total_minutes * OPTIMISTIC_FACTOR),
        "duration_pessimistic_min": n * total_minutes,
    }
