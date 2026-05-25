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
