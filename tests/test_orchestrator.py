import json
import subprocess as subprocess_mod
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.logger import WorkflowLogger
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
            result = orch._check_coverage(logger)
            logger.close()
        assert result is True

    def test_skipped_when_not_configured(self, tmp_path):
        _config(tmp_path)
        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=_smart_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            result = orch._check_coverage(logger)
            logger.close()
        assert result is True

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
            result = orch._check_coverage(logger)
            logger.close()
        assert result is False

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
            result = orch._check_coverage(logger)
            logger.close()
        assert result is False


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
