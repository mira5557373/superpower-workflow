import json
from pathlib import Path

import pytest


@pytest.fixture
def claude_dir(tmp_path: Path) -> Path:
    cd = tmp_path / ".claude"
    cd.mkdir()
    return cd


@pytest.fixture
def sample_config() -> dict:
    return {
        "schema_version": 1,
        "spec": "docs/superpowers/specs/spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "convergence": {
            "max_iterations": 5,
            "min_gaps_for_substantial": 20,
            "persistent_gap_downgrade_after": 3,
        },
        "verify_commands": {"test": "python -m pytest -q", "lint": None, "format": None},
        "git_strategy": "main",
        "notification_webhook": None,
        "milestones": [],
    }


@pytest.fixture
def config_file(claude_dir: Path, sample_config: dict) -> Path:
    path = claude_dir / "workflow.json"
    path.write_text(json.dumps(sample_config))
    return path
