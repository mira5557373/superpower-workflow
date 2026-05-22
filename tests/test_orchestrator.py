import json
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import WorkflowState, load_state, save_state


def _config(tmp_path, milestones=None):
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
        "milestones": milestones
        if milestones is not None
        else [{"name": "m1", "spec_sections": "1", "description": "First", "depends_on": []}],
    }
    cd = tmp_path / ".claude"
    cd.mkdir()
    (cd / "workflow.json").write_text(json.dumps(config))
    return config


def _ok_result(cost=1.0):
    return ClaudeResult(text="done", cost_usd=cost, session_id="s1", is_error=False)


def _smart_subprocess(*args, **kwargs):
    cmd = args[0] if args else kwargs.get("args", [])
    if isinstance(cmd, list) and len(cmd) >= 2:
        if cmd[1] == "status":
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if cmd[1] == "rev-parse":
            return CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
        if cmd[1] == "log":
            return CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def test_orchestrator_runs_all_four_phases(tmp_path):
    _config(tmp_path)
    calls = []

    def mock_run(*args, **kwargs):
        calls.append(args[0] if args else "")
        return _ok_result()

    with (
        patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    assert len(calls) >= 4


def test_orchestrator_dry_run_does_not_call_claude(tmp_path):
    _config(tmp_path)
    with patch("superpower_workflow.orchestrator.run_claude") as mock:
        orch = Orchestrator(tmp_path)
        orch.run(dry_run=True)
    mock.assert_not_called()


def test_orchestrator_updates_state_after_milestone(tmp_path):
    _config(tmp_path)
    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()
    state = load_state(tmp_path / ".claude")
    assert "m1" in state.completed


def test_orchestrator_stops_on_budget_exceeded(tmp_path):
    _config(tmp_path)
    save_state(tmp_path / ".claude", WorkflowState(total_cost_usd=501.0))
    with (
        patch("superpower_workflow.orchestrator.run_claude") as mock,
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()
    mock.assert_not_called()


def test_orchestrator_writes_completion_json(tmp_path):
    _config(tmp_path)
    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()
    complete = tmp_path / ".claude" / "workflow-complete.json"
    assert complete.exists()
    data = json.loads(complete.read_text())
    assert data["status"] == "complete"
    assert "m1" in data["completed"]


def test_orchestrator_captures_spec_sha(tmp_path):
    _config(tmp_path)
    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()
    state = load_state(tmp_path / ".claude")
    assert state.spec_sha == "abc123"


def test_preflight_rejects_dirty_git(tmp_path):
    _config(tmp_path)

    def dirty_subprocess(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1] == "status":
            return CompletedProcess(args=cmd, returncode=0, stdout="M file.py\n", stderr="")
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=dirty_subprocess):
        orch = Orchestrator(tmp_path)
        result = orch._preflight_checks()
    assert result is False


def test_preflight_rejects_no_milestones(tmp_path):
    _config(tmp_path, milestones=[])

    with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess):
        orch = Orchestrator(tmp_path)
        result = orch._preflight_checks()
    assert result is False
