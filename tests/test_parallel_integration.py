from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.state import load_state

# v1.3.8: parallel mode ungated by Edit A. The SW_ALLOW_BROKEN_PARALLEL
# env-var workaround from v1.3.7 is no longer needed.


def _ok_result(cost: float = 1.0):
    from superpower_workflow.runner import ClaudeResult

    return ClaudeResult(
        text="ok",
        cost_usd=cost,
        session_id="s1",
        duration_ms=100,
        is_error=False,
    )


def _config(tmp_path: Path, milestones: list | None = None, parallel: dict | None = None):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "budgets": {"plan": 5, "implement": 10, "review": 5, "push": 1},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "verify_commands": {},
        "milestones": milestones or [],
    }
    if parallel:
        config["parallel"] = parallel
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    (tmp_path / "spec.md").write_text("# Spec")
    return config


def _smart_subprocess(cmd, **kwargs):
    if isinstance(cmd, list):
        cmd_str = " ".join(cmd)
        if "status" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "rev-parse" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="abc123", stderr="")
        if "tag" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "log" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "worktree" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "merge" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "branch" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    if isinstance(cmd, str):
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


_PARALLEL_CFG = {
    "enabled": True,
    "max_workers": 1,
    "best_of_n": 1,
    "agent_teams_count": 0,
    "remote": None,
    "worktree_dir": ".worktrees",
}


class TestParallelEndToEnd:
    def test_independent_milestones_planned_as_single_wave(self, tmp_path):
        from superpower_workflow.parallel.planner import ParallelPlanner

        milestones = [{"name": "m1"}, {"name": "m2"}, {"name": "m3"}]
        planner = ParallelPlanner(milestones)
        waves = planner.plan_waves()
        assert len(waves) == 1
        assert set(waves[0].milestones) == {"m1", "m2", "m3"}

    def test_dependent_milestones_sequential_waves(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1"},
                {"name": "m2", "depends_on": ["m1"]},
            ],
            parallel=_PARALLEL_CFG,
        )
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
        assert "m2" in state.completed

    def test_model_routing_in_parallel_mode(self, tmp_path):
        config = _config(
            tmp_path,
            milestones=[
                {"name": "m1", "description": "fix typo"},
                {"name": "m2", "description": "refactor authentication architecture"},
            ],
        )
        config["model_routing"] = {
            "enabled": True,
            "default_model": "opus",
            "rules": [
                {"threshold": 0.5, "model": "opus"},
                {"threshold": 0.0, "model": "haiku"},
            ],
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        models_used = []

        def mock_run_claude(prompt, model, **kwargs):
            models_used.append(model)
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert "haiku" in models_used
        assert "opus" in models_used

    def test_budget_shared_across_parallel_workers(self, tmp_path):
        _config(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}, {"name": "m3"}],
            parallel=_PARALLEL_CFG,
        )

        def mock_run_claude(prompt, **kwargs):
            return _ok_result(cost=50.0)

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert state.total_cost_usd > 0

    def test_sequential_fallback_when_single_milestone(self, tmp_path):
        _config(
            tmp_path,
            milestones=[{"name": "m1"}],
            parallel=_PARALLEL_CFG,
        )
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_failed_milestone_in_wave_skips_dependents(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1"},
                {"name": "m2", "depends_on": ["m1"]},
            ],
            parallel=_PARALLEL_CFG,
        )

        def mock_run_claude(prompt, **kwargs):
            from superpower_workflow.runner import ClaudeResult

            return ClaudeResult(text="", cost_usd=1.0, is_error=True)

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.failed
        assert "m2" in state.skipped or "m2" not in state.completed
