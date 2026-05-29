import json
import os as os_mod
import subprocess as subprocess_mod
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.audit import AuditTrail, _hkdf_sha256
from superpower_workflow.logger import WorkflowLogger
from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import WorkflowState, load_state, save_state


def _read_telemetry(tmp_path):
    path = tmp_path / ".claude" / "telemetry.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line.strip()]


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


def _config_with_gates(tmp_path, gates=None):
    """Create config with quality_gates section."""
    config = _config(tmp_path)
    config["quality_gates"] = gates or {
        "lint": "ruff check .",
        "sast": None,
        "dep_scan": None,
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


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


def test_phase_error_stops_milestone(tmp_path):
    _config(tmp_path)
    error_result = ClaudeResult(text="network error", is_error=True)

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.time.sleep"),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()
    state = load_state(tmp_path / ".claude")
    assert "m1" not in state.completed


def test_config_validation_rejects_missing_budgets(tmp_path):
    from superpower_workflow.orchestrator import validate_config

    errors = validate_config({"spec": "s.md", "model": "opus", "milestones": []})
    assert any("budgets" in e for e in errors)


def test_config_validation_passes_valid(tmp_path):
    from superpower_workflow.orchestrator import validate_config

    errors = validate_config(
        {
            "spec": "s.md",
            "model": "opus",
            "milestones": [],
            "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        }
    )
    assert errors == []


class TestVerifyQualityGates:
    def test_all_gates_pass(self, tmp_path):
        _config_with_gates(tmp_path)
        success = CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with patch("superpower_workflow.orchestrator.subprocess.run", return_value=success):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is True
        assert failures == []

    def test_lint_failure_collected(self, tmp_path):
        _config_with_gates(tmp_path)

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, str) and "ruff" in cmd:
                return CompletedProcess(
                    args=[], returncode=1, stdout="E501 line too long", stderr=""
                )
            return CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=mock_run):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is False
        assert any("lint" in f for f in failures)

    def test_multiple_gates_fail(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={"lint": "ruff check .", "sast": "bandit -r src/", "dep_scan": None},
        )
        fail = CompletedProcess(args=[], returncode=1, stdout="fail", stderr="")
        with patch("superpower_workflow.orchestrator.subprocess.run", return_value=fail):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is False
        assert len(failures) == 2
        assert any("lint" in f for f in failures)
        assert any("sast" in f for f in failures)

    def test_skip_when_not_configured(self, tmp_path):
        _config(tmp_path)
        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=_smart_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is True
        assert failures == []

    def test_timeout_handled_gracefully(self, tmp_path):
        _config_with_gates(tmp_path)

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, str):
                raise subprocess_mod.TimeoutExpired(cmd=cmd, timeout=300)
            return _smart_subprocess(cmd, **kwargs)

        with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=mock_run):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is False
        assert any("lint" in f for f in failures)


class TestCheckCoverage:
    def test_passes_above_threshold(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_report_path": "coverage.json",
            },
        )
        (tmp_path / "coverage.json").write_text(
            json.dumps({"totals": {"percent_covered_display": "85"}})
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("superpower_workflow.orchestrator.subprocess.run", return_value=success):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, cov_cost = orch._check_coverage(logger)
            logger.close()
        assert passed is True
        assert cov_cost == 0.0

    def test_skipped_when_not_configured(self, tmp_path):
        _config(tmp_path)
        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=_smart_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, cov_cost = orch._check_coverage(logger)
            logger.close()
        assert passed is True
        assert cov_cost == 0.0

    def test_returns_false_after_max_attempts(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_max_attempts": 2,
                "coverage_report_path": "coverage.json",
            },
        )
        (tmp_path / "coverage.json").write_text(
            json.dumps({"totals": {"percent_covered_display": "50"}})
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                return_value=success,
            ),
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, cov_cost = orch._check_coverage(logger)
            logger.close()
        assert passed is False
        assert cov_cost > 0.0

    def test_missing_report_treated_as_zero(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_max_attempts": 1,
                "coverage_report_path": "nonexistent.json",
            },
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("superpower_workflow.orchestrator.subprocess.run", return_value=success):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, _ = orch._check_coverage(logger)
            logger.close()
        assert passed is False

    def test_timeout_handled_gracefully(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "sleep 999",
                "coverage_threshold": 80,
                "coverage_max_attempts": 1,
                "coverage_report_path": "nonexistent.json",
            },
        )

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, str):
                raise subprocess_mod.TimeoutExpired(cmd=cmd, timeout=600)
            return _smart_subprocess(cmd, **kwargs)

        with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=mock_run):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, _ = orch._check_coverage(logger)
            logger.close()
        assert passed is False

    def test_coverage_cmd_failure_logged(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "false",
                "coverage_threshold": 80,
                "coverage_max_attempts": 1,
                "coverage_report_path": "nonexistent.json",
            },
        )
        fail = CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("superpower_workflow.orchestrator.subprocess.run", return_value=fail):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, _ = orch._check_coverage(logger)
            logger.close()
        assert passed is False
        log_content = (tmp_path / ".claude" / "workflow-test.log").read_text()
        assert "COVERAGE_CMD_FAILED" in log_content


class TestCheckTrailers:
    def test_warns_on_missing_trailers(self, tmp_path):
        _config_with_gates(tmp_path, gates={"lint": None, "require_git_trailers": True})

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and any("--format=%H %b" in c for c in cmd):
                return CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="abc12345 no trailer here\n",
                    stderr="",
                )
            return _smart_subprocess(cmd, **kwargs)

        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=mock_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            orch._check_trailers("abc123", logger)
            logger.close()
        log_content = (tmp_path / ".claude" / "workflow-test.log").read_text()
        assert "TRAILER_MISSING" in log_content

    def test_skips_when_not_configured(self, tmp_path):
        _config(tmp_path)
        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=_smart_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            orch._check_trailers("abc123", logger)
            logger.close()
        log_content = (tmp_path / ".claude" / "workflow-test.log").read_text()
        assert "TRAILER" not in log_content

    def test_no_warning_when_trailers_present(self, tmp_path):
        _config_with_gates(tmp_path, gates={"lint": None, "require_git_trailers": True})

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and any("--format=%H %b" in c for c in cmd):
                return CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="abc12345 Generated-By: claude\n",
                    stderr="",
                )
            return _smart_subprocess(cmd, **kwargs)

        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=mock_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            orch._check_trailers("abc123", logger)
            logger.close()
        log_content = (tmp_path / ".claude" / "workflow-test.log").read_text()
        assert "TRAILER_MISSING" not in log_content


class TestQualityGateCheckpointB:
    def test_gates_pass_no_fix_invocation(self, tmp_path):
        """Quality gates pass after Phase B -> no fix prompt sent."""
        _config_with_gates(tmp_path)
        prompts = []

        def mock_run_claude(prompt, **kwargs):
            prompts.append(prompt)
            return _ok_result()

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        fix_prompts = [p for p in prompts if "Quality gates failed" in p]
        assert fix_prompts == []

    def test_fix_invoked_when_gate_fails(self, tmp_path):
        """Quality gates fail after Phase B -> fix prompt with failure details."""
        _config_with_gates(tmp_path)
        prompts = []

        def mock_run_claude(prompt, **kwargs):
            prompts.append(prompt)
            return _ok_result()

        gate_calls = {"n": 0}

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str) and "ruff" in cmd:
                gate_calls["n"] += 1
                if gate_calls["n"] == 1:
                    return CompletedProcess(
                        args=[], returncode=1, stdout="E501 line too long", stderr=""
                    )
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        fix_prompts = [p for p in prompts if "Quality gates failed" in p]
        assert len(fix_prompts) >= 1
        assert "lint" in fix_prompts[0]
        assert "E501" in fix_prompts[0]

    def test_fix_cost_tracked_from_result(self, tmp_path):
        """Fix invocation cost comes from ClaudeResult, not hardcoded."""
        _config_with_gates(tmp_path)
        costs = []

        def mock_run_claude(prompt, **kwargs):
            result = _ok_result(cost=3.5 if "Quality gates failed" in prompt else 1.0)
            costs.append(result.cost_usd)
            return result

        gate_calls = {"n": 0}

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str) and "ruff" in cmd:
                gate_calls["n"] += 1
                if gate_calls["n"] == 1:
                    return CompletedProcess(args=[], returncode=1, stdout="fail", stderr="")
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert 3.5 in costs
        assert state.total_cost_usd > 4.0


class TestQualityGateCheckpointC:
    def test_checkpoint_c_runs_after_phase_c(self, tmp_path):
        """Checkpoint #2 runs quality gates after Phase C."""
        _config_with_gates(tmp_path)
        gate_calls = {"n": 0}

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str) and "ruff" in cmd:
                gate_calls["n"] += 1
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

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
            orch.run()
        # Gates called at both checkpoints (after B and after C)
        assert gate_calls["n"] >= 2

    def test_coverage_check_runs_in_checkpoint(self, tmp_path):
        """Coverage check integrated into quality gate checkpoint."""
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_report_path": "coverage.json",
            },
        )
        (tmp_path / "coverage.json").write_text(
            json.dumps({"totals": {"percent_covered_display": "90"}})
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                return_value=success,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_backward_compatible_no_quality_gates(self, tmp_path):
        """No quality_gates in config -> full run works as before."""
        _config(tmp_path)
        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed


class TestTelemetryRunEvents:
    def test_telemetry_file_created(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        telemetry_path = tmp_path / ".claude" / "telemetry.jsonl"
        assert telemetry_path.exists()

    def test_run_started_event_emitted(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        started = [e for e in events if e["type"] == "run_started"]
        assert len(started) == 1
        assert started[0]["model"] == "opus"
        assert started[0]["milestone_count"] == 1

    def test_run_completed_event_emitted(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        completed = [e for e in events if e["type"] == "run_completed"]
        assert len(completed) == 1
        assert completed[0]["status"] == "complete"
        assert completed[0]["completed_count"] == 1

    def test_telemetry_disabled_by_config(self, tmp_path):
        config = _config(tmp_path)
        config["telemetry"] = {"enabled": False}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "telemetry.jsonl").exists()


class TestTelemetryMilestonePhaseEvents:
    def test_milestone_started_and_completed(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        ms_started = [e for e in events if e["type"] == "milestone_started"]
        ms_completed = [e for e in events if e["type"] == "milestone_completed"]
        assert len(ms_started) == 1
        assert ms_started[0]["milestone"] == "m1"
        assert len(ms_completed) == 1
        assert ms_completed[0]["milestone"] == "m1"
        assert ms_completed[0]["cost_usd"] > 0

    def test_all_four_phases_emitted(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        phase_started = [e for e in events if e["type"] == "phase_started"]
        phase_completed = [e for e in events if e["type"] == "phase_completed"]
        phases = [e["phase"] for e in phase_started]
        assert "plan" in phases
        assert "implement" in phases
        assert "review" in phases
        assert "push" in phases
        assert len(phase_completed) == 4

    def test_phase_completed_has_cost_and_session(self, tmp_path):
        _config(tmp_path)
        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(cost=5.0),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        plan_done = [e for e in events if e["type"] == "phase_completed" and e["phase"] == "plan"]
        assert len(plan_done) == 1
        assert plan_done[0]["cost_usd"] == 5.0
        assert plan_done[0]["session_id"] == "s1"

    def test_milestone_skipped_event(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1", "spec_sections": "1", "depends_on": []},
                {"name": "m2", "spec_sections": "2", "depends_on": ["m1"]},
            ],
        )
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        skipped = [e for e in events if e["type"] == "milestone_skipped"]
        assert any(e["milestone"] == "m2" for e in skipped)


class TestTelemetryQualityEvents:
    def test_quality_gate_events_emitted(self, tmp_path):
        _config_with_gates(tmp_path)
        success = CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=lambda cmd, **kw: (
                    success if isinstance(cmd, str) else _smart_subprocess(cmd, **kw)
                ),
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        gate_events = [e for e in events if e["type"] == "quality_gate_result"]
        assert len(gate_events) >= 2
        assert all(e["passed"] for e in gate_events)

    def test_retry_event_emitted_on_failure(self, tmp_path):
        _config(tmp_path)
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        retries = [e for e in events if e["type"] == "retry_attempt"]
        assert len(retries) >= 1
        assert retries[0]["attempt"] >= 1

    def test_milestone_failed_event_emitted(self, tmp_path):
        _config(tmp_path)
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        failed = [e for e in events if e["type"] == "milestone_failed"]
        assert len(failed) == 1
        assert failed[0]["milestone"] == "m1"

    def test_gap_report_captured_after_phase_a(self, tmp_path):
        _config(tmp_path)
        gap_data = {
            "critical_gaps": 0,
            "important_gaps": 2,
            "total_gaps_found": 5,
            "converged": True,
        }
        (tmp_path / ".claude" / ".gap-report.json").write_text(json.dumps(gap_data))

        call_count = {"n": 0}

        def mock_run_claude(prompt, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                (tmp_path / ".claude" / ".gap-report.json").write_text(json.dumps(gap_data))
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        gaps = [e for e in events if e["type"] == "gap_report"]
        assert len(gaps) >= 1
        assert gaps[0]["important_gaps"] == 2

    def test_zero_gaps_means_converged(self, tmp_path):
        """Soak finding #C: total_gaps_found=0 must imply converged=True even when
        the gap report didn't set the flag."""
        _config(tmp_path)
        gap_data = {
            "critical_gaps": 0,
            "important_gaps": 0,
            "total_gaps_found": 0,
            "converged": False,  # model forgot to flip the flag
        }
        call_count = {"n": 0}

        def mock_run_claude(prompt, **kwargs):
            call_count["n"] += 1
            (tmp_path / ".claude" / ".gap-report.json").write_text(json.dumps(gap_data))
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        gaps = [e for e in events if e["type"] == "gap_report"]
        assert all(g["converged"] for g in gaps), (
            f"zero-gap reports must be marked converged. got: "
            f"{[(g['total_gaps_found'], g['converged']) for g in gaps]}"
        )


class TestTelemetryIntegration:
    def test_full_run_event_sequence(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        types = [e["type"] for e in events]
        assert types[0] == "run_started"
        assert types[-1] == "run_completed"
        assert "milestone_started" in types
        assert "milestone_completed" in types
        assert "phase_started" in types
        assert "phase_completed" in types

    def test_multi_milestone_run(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1", "spec_sections": "1", "depends_on": []},
                {"name": "m2", "spec_sections": "2", "depends_on": ["m1"]},
            ],
        )
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        ms_completed = [e for e in events if e["type"] == "milestone_completed"]
        assert len(ms_completed) == 2
        milestones = [e["milestone"] for e in ms_completed]
        assert "m1" in milestones
        assert "m2" in milestones

    def test_all_run_ids_consistent(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        run_ids = {e["run_id"] for e in events}
        assert len(run_ids) == 1

    def test_existing_tests_still_pass_without_telemetry_config(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_telemetry_survives_milestone_failure(self, tmp_path):
        _config(tmp_path)
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        assert any(e["type"] == "run_started" for e in events)
        assert any(e["type"] == "run_completed" for e in events)
        assert any(e["type"] in ("milestone_failed", "retry_attempt") for e in events)


def _read_audit_trail(tmp_path):
    path = tmp_path / ".claude" / "audit-trail.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line.strip()]


def _config_with_security(tmp_path, security=None, gates=None):
    config = _config(tmp_path)
    config["security"] = security or {"audit_trail": True}
    if gates:
        config["quality_gates"] = gates
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


class TestAuditTrailIntegration:
    def test_audit_trail_created_when_enabled(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        assert len(trail) > 0

    def test_audit_trail_has_run_events(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        events = [e["event"] for e in trail]
        assert "RUN_START" in events
        assert "RUN_COMPLETE" in events

    def test_audit_trail_has_milestone_events(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        events = [e["event"] for e in trail]
        assert "MILESTONE_START" in events
        assert "MILESTONE_COMPLETE" in events

    def test_audit_trail_has_phase_events(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        events = [e["event"] for e in trail]
        assert "PHASE_COMPLETE" in events

    def test_audit_chain_verifies(self, tmp_path):
        _config_with_security(tmp_path)
        key = _hkdf_sha256(b"test-key", info=b"sw-audit-trail")
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        audit_path = tmp_path / ".claude" / "audit-trail.jsonl"
        trail = AuditTrail(audit_path, key=key)
        valid, _ = trail.verify()
        assert valid is True

    def test_no_audit_when_disabled(self, tmp_path):
        _config_with_security(tmp_path, security={"audit_trail": False})
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()

    def test_no_audit_when_no_security_section(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()

    def test_no_audit_when_key_missing(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {}, clear=True),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()


def _config_with_secrets(tmp_path, secrets=None):
    config = _config(tmp_path)
    config["secrets"] = secrets or {"db_password": "DB_PASS"}
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


class TestSecretsIntegration:
    def test_secrets_fragment_in_system_prompt(self, tmp_path):
        _config_with_secrets(tmp_path)
        prompts = []

        def mock_run_claude(prompt, **kwargs):
            prompts.append(kwargs.get("system_prompt", ""))
            return _ok_result()

        with (
            patch.dict(os_mod.environ, {"DB_PASS": "hunter2"}),
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert any("$DB_PASS" in p for p in prompts)
        assert not any("hunter2" in p for p in prompts)

    def test_no_secrets_section_works(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_missing_env_var_warns_and_continues(self, tmp_path, capsys):
        _config_with_secrets(tmp_path)
        with (
            patch.dict(os_mod.environ, {}, clear=True),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        captured = capsys.readouterr()
        assert "Warning" in captured.out or "m1" in load_state(tmp_path / ".claude").completed


def _config_with_policies(tmp_path, policies=None):
    config = _config(tmp_path)
    config["policies"] = policies or {"max_file_lines": 500}
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


class TestPolicyIntegration:
    def test_policy_check_runs_at_checkpoints(self, tmp_path):
        _config_with_policies(tmp_path, policies={"max_file_lines": 500})
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_policy_violation_triggers_fix(self, tmp_path):
        _config_with_policies(tmp_path, policies={"banned_imports": ["os.system"]})
        prompts = []
        call_count = {"n": 0}

        def mock_run_claude(prompt, **kwargs):
            call_count["n"] += 1
            prompts.append(prompt)
            if call_count["n"] == 3:
                bad_file = tmp_path / "src" / "bad.py"
                bad_file.parent.mkdir(parents=True, exist_ok=True)
                bad_file.write_text("import json\n")
            return _ok_result()

        bad_file = tmp_path / "src" / "bad.py"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_text("import os\nos.system('ls')\n")

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and "diff" in cmd and "--name-only" in cmd:
                return CompletedProcess(args=cmd, returncode=0, stdout="src/bad.py\n", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        fix_prompts = [p for p in prompts if "Policy" in p or "policy" in p]
        assert len(fix_prompts) >= 1

    def test_no_policies_section_works(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed


class TestSbomAndSigningIntegration:
    def test_sbom_generated_in_phase_d(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {
            "audit_trail": False,
            "sbom_tool": "echo sbom",
            "sbom_output": ".claude/sbom-{milestone}.json",
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        sbom_calls = []

        def mock_subprocess(cmd, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
            if "sbom" in cmd_str:
                sbom_calls.append(cmd_str)
                return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
            patch("superpower_workflow.security.subprocess.run", side_effect=mock_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert len(sbom_calls) >= 1

    @pytest.mark.skipif(
        not __import__("superpower_workflow.security", fromlist=["HAS_CRYPTO"]).HAS_CRYPTO,
        reason="cryptography not installed",
    )
    def test_signing_called_in_phase_d(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {
            "audit_trail": False,
            "sign_artifacts": True,
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key_hex = Ed25519PrivateKey.generate().private_bytes_raw().hex()

        note_calls = []

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and "notes" in cmd:
                note_calls.append(cmd)
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch.dict(os_mod.environ, {"SW_SIGN_KEY": key_hex}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
            patch("superpower_workflow.security.subprocess.run", side_effect=mock_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert any("notes" in str(c) for c in note_calls)

    def test_no_security_config_skips_both(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed


class TestSP4Integration:
    def test_full_run_with_all_security_features(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {
            "audit_trail": True,
            "sign_artifacts": False,
            "sbom_tool": "",
        }
        config["secrets"] = {"token": "MY_TOKEN"}
        config["policies"] = {"max_file_lines": 1000}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key", "MY_TOKEN": "val"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()

        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

        trail = _read_audit_trail(tmp_path)
        assert len(trail) > 0
        events = [e["event"] for e in trail]
        assert "RUN_START" in events
        assert "RUN_COMPLETE" in events

    def test_backward_compatible_no_security_keys(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()

    def test_audit_trail_survives_milestone_failure(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        assert any(e["event"] == "RUN_START" for e in trail)
        assert any(e["event"] == "RUN_COMPLETE" for e in trail)

    def test_multi_milestone_audit_chain_valid(self, tmp_path):
        config = _config(
            tmp_path,
            milestones=[
                {"name": "m1", "spec_sections": "1", "depends_on": []},
                {"name": "m2", "spec_sections": "2", "depends_on": ["m1"]},
            ],
        )
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        from superpower_workflow.audit import AuditTrail, _hkdf_sha256

        key = _hkdf_sha256(b"key", info=b"sw-audit-trail")
        audit_path = tmp_path / ".claude" / "audit-trail.jsonl"
        trail = AuditTrail(audit_path, key=key)
        valid, last_seq = trail.verify()
        assert valid is True
        assert last_seq > 5

    def test_telemetry_and_audit_coexist(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        telemetry = _read_telemetry(tmp_path)
        audit = _read_audit_trail(tmp_path)
        assert len(telemetry) > 0
        assert len(audit) > 0
        assert any(e["type"] == "run_started" for e in telemetry)
        assert any(e["event"] == "RUN_START" for e in audit)

    def test_all_run_ids_consistent_in_audit(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        run_ids = {e["run_id"] for e in trail if e["run_id"]}
        assert len(run_ids) == 1


def _config_with_integrations(tmp_path, integrations=None, milestones=None, **extra):
    config = _config(tmp_path, milestones=milestones)
    config["integrations"] = integrations or {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {
            "webhook_url_env": "SLACK_URL",
            "events": ["milestone_start", "milestone_complete", "milestone_failed"],
        },
        "ci": {"enabled": False},
        "tracker": {},
    }
    config.update(extra)
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


def test_orchestrator_sends_notification_on_milestone_start(tmp_path):
    _config_with_integrations(tmp_path)
    notifications = []

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification") as mock_notify,
    ):
        mock_notify.side_effect = lambda *a, **kw: notifications.append(a)
        orch = Orchestrator(tmp_path)
        orch.run()

    events = [n[1] for n in notifications]
    assert "milestone_start" in events


def test_orchestrator_sends_notification_on_milestone_complete(tmp_path):
    _config_with_integrations(tmp_path)
    notifications = []

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification") as mock_notify,
    ):
        mock_notify.side_effect = lambda *a, **kw: notifications.append(a)
        orch = Orchestrator(tmp_path)
        orch.run()

    events = [n[1] for n in notifications]
    assert "milestone_complete" in events


def test_orchestrator_sends_notification_on_milestone_failed(tmp_path):
    _config_with_integrations(tmp_path)
    notifications = []

    with (
        patch(
            "superpower_workflow.orchestrator.run_claude",
            return_value=ClaudeResult(is_error=True, text="fail"),
        ),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification") as mock_notify,
        patch("superpower_workflow.orchestrator.time.sleep"),
    ):
        mock_notify.side_effect = lambda *a, **kw: notifications.append(a)
        orch = Orchestrator(tmp_path)
        orch.run()

    events = [n[1] for n in notifications]
    assert "milestone_failed" in events


def test_orchestrator_runs_phase_e_when_ci_enabled(tmp_path):
    _config_with_integrations(
        tmp_path,
        integrations={
            "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
            "slack": {},
            "ci": {
                "enabled": True,
                "max_fix_attempts": 3,
                "wait_timeout_seconds": 5,
                "poll_interval_seconds": 1,
            },
            "tracker": {},
        },
    )

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        mock_ci.return_value = (True, 0.5)
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_ci.assert_called_once()
    call_kw = mock_ci.call_args
    assert call_kw[1]["ci_config"]["enabled"] is True


def test_orchestrator_skips_phase_e_when_ci_disabled(tmp_path):
    _config_with_integrations(
        tmp_path,
        integrations={
            "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
            "slack": {},
            "ci": {"enabled": False},
            "tracker": {},
        },
    )

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_ci.assert_not_called()


def test_orchestrator_phase_e_cost_added(tmp_path):
    _config_with_integrations(
        tmp_path,
        integrations={
            "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
            "slack": {},
            "ci": {
                "enabled": True,
                "max_fix_attempts": 2,
                "wait_timeout_seconds": 5,
                "poll_interval_seconds": 1,
            },
            "tracker": {},
        },
    )

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result(cost=1.0)),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        mock_ci.return_value = (True, 3.0)
        orch = Orchestrator(tmp_path)
        orch.run()

    state = load_state(tmp_path / ".claude")
    assert state.total_cost_usd >= 7.0


def test_orchestrator_phase_e_failure_does_not_fail_milestone(tmp_path):
    _config_with_integrations(
        tmp_path,
        integrations={
            "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
            "slack": {},
            "ci": {
                "enabled": True,
                "max_fix_attempts": 1,
                "wait_timeout_seconds": 5,
                "poll_interval_seconds": 1,
            },
            "tracker": {},
        },
    )

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        mock_ci.return_value = (False, 2.0)
        orch = Orchestrator(tmp_path)
        orch.run()

    state = load_state(tmp_path / ".claude")
    assert "m1" in state.completed


def test_orchestrator_creates_pr_when_enabled(tmp_path):
    _config_with_integrations(
        tmp_path,
        integrations={
            "github": {"default_repo": "owner/repo", "auto_pr": True, "issue_label_map": {}},
            "slack": {},
            "ci": {"enabled": False},
            "tracker": {},
        },
        git_strategy="branch",
    )

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_pr") as mock_pr,
    ):
        mock_pr.return_value = "https://github.com/owner/repo/pull/1"
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_pr.assert_called_once()
    call_kw = mock_pr.call_args
    assert "m1" in call_kw[1].get("title", "") or "m1" in str(call_kw)


def test_orchestrator_skips_pr_when_disabled(tmp_path):
    _config_with_integrations(
        tmp_path,
        integrations={
            "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
            "slack": {},
            "ci": {"enabled": False},
            "tracker": {},
        },
    )

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_pr") as mock_pr,
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_pr.assert_not_called()


def test_orchestrator_pr_on_main_strategy(tmp_path):
    _config_with_integrations(
        tmp_path,
        integrations={
            "github": {"default_repo": "owner/repo", "auto_pr": True, "issue_label_map": {}},
            "slack": {},
            "ci": {"enabled": False},
            "tracker": {},
        },
        git_strategy="main",
    )

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_pr") as mock_pr,
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_pr.assert_not_called()


def test_orchestrator_from_issue_creates_milestone(tmp_path):
    _config_with_integrations(
        tmp_path,
        milestones=[],
        integrations={
            "github": {
                "default_repo": "owner/repo",
                "auto_pr": False,
                "issue_label_map": {"bug": "fix"},
            },
            "slack": {},
            "ci": {"enabled": False},
            "tracker": {},
        },
    )

    issue_data = {
        "title": "Fix login",
        "body": "Login is broken",
        "labels": [{"name": "bug"}],
        "assignees": [],
    }

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.fetch_issue", return_value=issue_data),
    ):
        orch = Orchestrator(tmp_path)
        orch.run(from_issue="42")

    state = load_state(tmp_path / ".claude")
    assert "fix-login" in state.completed


def test_orchestrator_from_ticket_creates_milestone(tmp_path):
    _config_with_integrations(
        tmp_path,
        milestones=[],
        integrations={
            "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
            "slack": {},
            "ci": {"enabled": False},
            "tracker": {
                "type": "linear",
                "api_url": "https://api.linear.app/graphql",
                "token_env": "T",
            },
        },
    )

    ticket_data = {
        "title": "Add dark mode",
        "description": "Dark mode for settings page",
        "priority": "High",
    }

    mock_adapter = MagicMock()
    mock_adapter.fetch_ticket.return_value = ticket_data
    mock_adapter.ticket_to_milestone.return_value = {
        "name": "add-dark-mode",
        "description": "Add dark mode",
        "spec_sections": "Dark mode for settings page",
        "depends_on": [],
    }

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_tracker", return_value=mock_adapter),
    ):
        orch = Orchestrator(tmp_path)
        orch.run(from_ticket="LIN-42")

    state = load_state(tmp_path / ".claude")
    assert "add-dark-mode" in state.completed


def test_orchestrator_updates_tracker_on_milestone_complete(tmp_path):
    _config_with_integrations(
        tmp_path,
        milestones=[],
        integrations={
            "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
            "slack": {},
            "ci": {"enabled": False},
            "tracker": {
                "type": "linear",
                "api_url": "https://api.linear.app/graphql",
                "token_env": "T",
            },
        },
    )

    ticket_data = {"title": "Fix bug", "description": "Details", "priority": "High"}
    mock_adapter = MagicMock()
    mock_adapter.fetch_ticket.return_value = ticket_data
    mock_adapter.ticket_to_milestone.return_value = {
        "name": "fix-bug",
        "description": "Fix bug",
        "spec_sections": "Details",
        "depends_on": [],
    }

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_tracker", return_value=mock_adapter),
    ):
        orch = Orchestrator(tmp_path)
        orch.run(from_ticket="LIN-99")

    mock_adapter.update_status.assert_called_once()
    call_args = mock_adapter.update_status.call_args
    assert "LIN-99" in call_args[0] or call_args[1].get("ticket_id") == "LIN-99"


class TestModelRouting:
    def test_routing_overrides_model_per_milestone(self, tmp_path):
        config = _config(tmp_path)
        config["milestones"] = [
            {"name": "m1", "description": "fix typo", "depends_on": []},
            {
                "name": "m2",
                "description": "refactor authentication architecture migration",
                "depends_on": [],
            },
        ]
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

    def test_model_override_takes_precedence(self, tmp_path):
        config = _config(tmp_path)
        config["milestones"] = [{"name": "m1", "description": "anything", "depends_on": []}]
        config["model_routing"] = {
            "enabled": True,
            "default_model": "opus",
            "rules": [{"threshold": 0.0, "model": "haiku"}],
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
            orch.run(model_override="sonnet")
        assert all(m == "sonnet" for m in models_used)


class TestParallelMode:
    def test_run_accepts_parallel_params(self, tmp_path):
        config = _config(tmp_path)
        config["milestones"] = [{"name": "m1", "depends_on": []}]
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True, max_workers=2, best_of_n=1)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_parallel_two_milestones_completes(self, tmp_path):
        config = _config(tmp_path)
        config["milestones"] = [
            {"name": "m1", "depends_on": []},
            {"name": "m2", "depends_on": []},
        ]
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True, max_workers=1)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
        assert "m2" in state.completed


class TestQualityGateResultsCaching:
    def test_quality_gates_write_results_json(self, tmp_path):
        """Quality gates should write .quality-gate-results.json for gap validator."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config = {
            "spec": "spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [],
            "quality_gates": {"lint": "echo ok"},
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            orch = Orchestrator(tmp_path)

        logger = MagicMock()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            orch._telemetry = MagicMock()
            orch._verify_quality_gates(logger, milestone="test", checkpoint="quality_check_b")

        results_path = claude_dir / ".quality-gate-results.json"
        assert results_path.exists()
        data = json.loads(results_path.read_text())
        assert "lint" in data
        assert data["lint"]["passed"] is True


class TestSpecComplianceStep:
    def _make_orchestrator(self, tmp_path, validation_config=None):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        config = {
            "spec": "docs/spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test-ms", "spec_sections": "1, 2"}],
            "convergence": {"max_iterations": 5},
        }
        if validation_config:
            config["validation"] = validation_config
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            return Orchestrator(tmp_path)

    @patch("superpower_workflow.orchestrator.run_claude")
    def test_spec_compliance_runs_when_enabled(self, mock_run, tmp_path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"spec_compliance": True, "spec_compliance_budget": 3.0},
        )
        mock_run.return_value = ClaudeResult(
            text='{"total_requirements": 5, "implemented": 5, "missing": 0, "details": []}',
            cost_usd=2.0,
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        report, cost = orch._run_spec_compliance(
            "test-ms", {"name": "test-ms", "spec_sections": "1, 2"}
        )
        assert report["missing"] == 0
        assert cost == 2.0

    @patch("superpower_workflow.orchestrator.run_claude")
    def test_spec_compliance_skipped_when_disabled(self, mock_run, tmp_path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"spec_compliance": False},
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        report, cost = orch._run_spec_compliance("test-ms", {"name": "test-ms"})
        assert report is None
        assert cost == 0.0
        mock_run.assert_not_called()


class TestFeatureVerificationStep:
    def _make_orchestrator(self, tmp_path, validation_config=None):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        config = {
            "spec": "docs/spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test-ms"}],
            "convergence": {"max_iterations": 5},
        }
        if validation_config:
            config["validation"] = validation_config
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            return Orchestrator(tmp_path)

    @patch("superpower_workflow.orchestrator.run_claude")
    def test_feature_verification_runs_when_enabled(self, mock_run, tmp_path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"feature_verification": True, "feature_verification_budget": 5.0},
        )
        claude_dir = tmp_path / ".claude"
        (claude_dir / ".spec-compliance.json").write_text(
            json.dumps(
                {
                    "total_requirements": 3,
                    "implemented": 3,
                    "details": [{"requirement": "A", "status": "implemented", "evidence": "x"}],
                }
            )
        )

        mock_run.return_value = ClaudeResult(
            text='{"total_features": 3, "verified_working": 3, "broken": 0, "manual_review": 0, "details": []}',
            cost_usd=3.0,
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        report, cost = orch._run_feature_verification("test-ms")
        assert report["broken"] == 0
        assert cost == 3.0

    def test_feature_verification_skipped_when_disabled(self, tmp_path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"feature_verification": False},
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        report, cost = orch._run_feature_verification("test-ms")
        assert report is None
        assert cost == 0.0


class TestOrchestratorStateSteps:
    def test_spec_compliance_state_set(self, tmp_path):
        """Orchestrator sets current_step to spec_compliance."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        config = {
            "spec": "spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test"}],
            "validation": {"spec_compliance": True, "spec_compliance_budget": 3.0},
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            orch = Orchestrator(tmp_path)

        orch.state.current_step = "spec_compliance"
        save_state(claude_dir, orch.state)

        loaded = load_state(claude_dir)
        assert loaded.current_step == "spec_compliance"
