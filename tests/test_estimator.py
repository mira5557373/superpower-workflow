from superpower_workflow.estimator import estimate


def test_estimate_single_milestone():
    """Test that estimate populates all 5 fields and pessimistic >= optimistic."""
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": ["Task 1"],
    }
    result = estimate(config)

    # Verify all 5 fields are present
    assert "milestone_count" in result
    assert "cost_optimistic" in result
    assert "cost_pessimistic" in result
    assert "duration_optimistic_min" in result
    assert "duration_pessimistic_min" in result

    # Verify pessimistic >= optimistic
    assert result["cost_pessimistic"] >= result["cost_optimistic"]
    assert result["duration_pessimistic_min"] >= result["duration_optimistic_min"]

    # Verify milestone count
    assert result["milestone_count"] == 1


def test_estimate_ten_milestones():
    """Test that estimate with 10 milestones gives cost_pessimistic == 1680."""
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": [f"Task {i}" for i in range(1, 11)],
    }
    result = estimate(config)

    # Verify cost_pessimistic == 1680
    assert result["cost_pessimistic"] == 1680.0
    assert result["milestone_count"] == 10


def test_estimate_zero_milestones():
    """Test that estimate with 0 milestones gives all values == 0."""
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": [],
    }
    result = estimate(config)

    # Verify all values are 0
    assert result["milestone_count"] == 0
    assert result["cost_optimistic"] == 0.0
    assert result["cost_pessimistic"] == 0.0
    assert result["duration_optimistic_min"] == 0
    assert result["duration_pessimistic_min"] == 0
