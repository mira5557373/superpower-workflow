"""Tests for orchestrator module."""

import json
from unittest.mock import patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import load_state


def _config(tmp_path):
    """Create a minimal workflow.json config in tmp_path/.claude."""
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "convergence": {"max_iterations": 5},
        "verify_commands": {"test": None, "lint": None, "format": None},
        "git_strategy": "main",
        "notification_webhook": None,
        "milestones": [
            {
                "name": "m1",
                "spec_sections": "1",
                "description": "First",
                "depends_on": [],
                "budget_override": None,
            }
        ],
    }
    cd = tmp_path / ".claude"
    cd.mkdir()
    (cd / "workflow.json").write_text(json.dumps(config))
    return config


def _ok_result(cost=1.0):
    """Create a successful ClaudeResult."""
    return ClaudeResult(text="done", cost_usd=cost, session_id="s1", is_error=False)


class TestOrchestratorRunAllPhases:
    """Test that orchestrator runs all four phases."""

    def test_orchestrator_runs_all_four_phases(self, tmp_path):
        """Orchestrator.run() executes Phase A, B, C, D for each milestone."""
        _config(tmp_path)
        calls = []

        def mock_run(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("prompt", ""))
            return _ok_result()

        def mock_subprocess(*args, **kwargs):
            mock_result = type("obj", (object,), {"stdout": "abc123\n"})()
            return mock_result

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(dry_run=False)

        assert len(calls) >= 4  # Phase A, B, C, D


class TestOrchestratorDryRun:
    """Test dry-run mode."""

    def test_orchestrator_dry_run_does_not_call_claude(self, tmp_path):
        """Orchestrator.run(dry_run=True) does not call run_claude."""
        _config(tmp_path)

        with patch("superpower_workflow.orchestrator.run_claude") as mock_claude:
            orch = Orchestrator(tmp_path)
            orch.run(dry_run=True)

        mock_claude.assert_not_called()


class TestOrchestratorStateUpdate:
    """Test that state is updated after milestone completion."""

    def test_orchestrator_updates_state_after_milestone(self, tmp_path):
        """Orchestrator updates state.completed with milestone name."""
        _config(tmp_path)

        def mock_subprocess(*args, **kwargs):
            mock_result = type("obj", (object,), {"stdout": "abc123\n"})()
            return mock_result

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(dry_run=False)

        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
