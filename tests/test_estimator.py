import json
from pathlib import Path

from superpower_workflow.estimator import estimate


def test_estimate_single_milestone():
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": ["Task 1"],
    }
    result = estimate(config)
    assert result["milestone_count"] == 1
    assert result["cost_pessimistic"] >= result["cost_optimistic"]
    assert result["cost_pessimistic"] > 0
    assert result["duration_pessimistic_min"] >= result["duration_optimistic_min"]


def test_estimate_ten_milestones_realistic():
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": [f"Task {i}" for i in range(1, 11)],
    }
    result = estimate(config)
    assert result["milestone_count"] == 10
    # With realistic averages: 10 * $18 = $180 pessimistic (not $1680)
    assert result["cost_pessimistic"] == 180.0


def test_estimate_zero_milestones():
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": [],
    }
    result = estimate(config)
    assert result["milestone_count"] == 0
    assert result["cost_optimistic"] == 0.0
    assert result["cost_pessimistic"] == 0.0


def test_estimate_uses_historical_data(tmp_path: Path):
    telemetry_path = tmp_path / ".claude" / "telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True)
    events = [
        {"type": "milestone_completed", "cost_usd": 10.0},
        {"type": "milestone_completed", "cost_usd": 20.0},
    ]
    with open(telemetry_path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": ["m1", "m2"],
    }
    result = estimate(config, project_root=tmp_path)
    # Historical avg = $15. Optimistic = 2 * 15 * 0.8 = 24, Pessimistic = 2 * 15 * 1.3 = 39
    assert result["cost_optimistic"] == 24.0
    assert result["cost_pessimistic"] == 39.0


def test_estimate_without_historical_falls_back():
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": ["m1", "m2", "m3"],
    }
    result = estimate(config, project_root=Path("/nonexistent"))
    assert result["cost_pessimistic"] > 0
    assert result["milestone_count"] == 3


def test_calibration_against_real_soak_2026_05_29():
    """Recalibration target from 2026-05-29 soak:
    1 small milestone (todo-cli storage), opus, trust-but-verify enabled,
    actual cost $7.00 (phases $6.17 + spec compliance $0.46 + feature verify $0.37).

    Pre-fix forecast was $1.43-$2.85 (2.5× under). Post-fix the actual must
    land within [optimistic, pessimistic].
    """
    config = {
        "budgets": {"plan": 4, "implement": 10, "review": 4, "push": 1},
        "milestones": ["M1-storage"],
        "validation": {"spec_compliance": True, "feature_verification": True},
    }
    result = estimate(config)
    actual_soak_cost = 7.00
    assert result["cost_optimistic"] <= actual_soak_cost <= result["cost_pessimistic"], (
        f"$7.00 soak result must fall within [optimistic={result['cost_optimistic']}, "
        f"pessimistic={result['cost_pessimistic']}]"
    )


def test_trust_but_verify_adds_overhead():
    """When validation is enabled, estimates must be higher than without."""
    base_config = {
        "budgets": {"plan": 5, "implement": 15, "review": 5, "push": 1},
        "milestones": ["m1", "m2"],
    }
    without = estimate({**base_config, "validation": {}})
    with_tbv = estimate(
        {
            **base_config,
            "validation": {"spec_compliance": True, "feature_verification": True},
        }
    )
    assert with_tbv["cost_pessimistic"] > without["cost_pessimistic"]


def test_optimistic_not_aggressively_underforecast():
    """Soak finding: OPTIMISTIC_FACTOR=0.5 was too aggressive. Optimistic should
    be ≥ 60% of pessimistic, not 50%."""
    config = {
        "budgets": {"plan": 4, "implement": 10, "review": 4, "push": 1},
        "milestones": ["m1"],
    }
    result = estimate(config)
    ratio = result["cost_optimistic"] / max(result["cost_pessimistic"], 0.01)
    assert ratio >= 0.6, f"optimistic/pessimistic ratio {ratio:.2f} too aggressive"
