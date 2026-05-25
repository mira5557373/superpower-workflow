from __future__ import annotations

import json
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.integrations.ci_fix import (
    CIResult,
    ci_fix_loop,
    get_failure_logs,
    wait_for_ci,
)
from superpower_workflow.runner import ClaudeResult


class TestWaitForCi:
    def test_returns_passed_on_success(self):
        run_data = [{"status": "completed", "conclusion": "success", "databaseId": 100}]
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(run_data), stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=5, poll_interval_seconds=1)
        assert result.status == "passed"

    def test_returns_failed_on_failure(self):
        run_data = [{"status": "completed", "conclusion": "failure", "databaseId": 101}]
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(run_data), stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=5, poll_interval_seconds=1)
        assert result.status == "failed"
        assert result.run_id == "101"

    def test_polls_until_completed(self):
        pending = [{"status": "in_progress", "conclusion": None, "databaseId": 102}]
        done = [{"status": "completed", "conclusion": "success", "databaseId": 102}]
        responses = [
            CompletedProcess(args=[], returncode=0, stdout=json.dumps(pending), stderr=""),
            CompletedProcess(args=[], returncode=0, stdout=json.dumps(done), stderr=""),
        ]
        with (
            patch(
                "superpower_workflow.integrations.ci_fix.subprocess.run",
                side_effect=responses,
            ),
            patch("superpower_workflow.integrations.ci_fix.time.sleep"),
        ):
            result = wait_for_ci(".", timeout_seconds=120, poll_interval_seconds=1)
        assert result.status == "passed"

    def test_returns_timeout_when_exceeded(self):
        pending = [{"status": "in_progress", "conclusion": None, "databaseId": 103}]
        with (
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run,
            patch("superpower_workflow.integrations.ci_fix.time.sleep"),
            patch(
                "superpower_workflow.integrations.ci_fix.time.monotonic",
                side_effect=[0, 0, 700],
            ),
        ):
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(pending), stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=600, poll_interval_seconds=30)
        assert result.status == "timeout"

    def test_handles_empty_run_list(self):
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
            result = wait_for_ci(".", timeout_seconds=5, poll_interval_seconds=1)
        assert result.status == "timeout"

    def test_handles_invalid_json_response(self):
        with (
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run,
            patch("superpower_workflow.integrations.ci_fix.time.sleep"),
            patch(
                "superpower_workflow.integrations.ci_fix.time.monotonic",
                side_effect=[0, 0, 0, 0, 0, 0, 700],
            ),
        ):
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout="not json", stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=600, poll_interval_seconds=1)
        assert result.status == "timeout"
        assert "invalid" in result.conclusion.lower()


class TestGetFailureLogs:
    def test_returns_log_lines(self):
        logs = "step 1: OK\nstep 2: FAIL\nError: module not found\n" * 10
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(args=[], returncode=0, stdout=logs, stderr="")
            result = get_failure_logs("101", ".")
        assert "FAIL" in result
        assert "Error" in result

    def test_truncates_to_max_lines(self):
        logs = "\n".join(f"line {i}" for i in range(500))
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(args=[], returncode=0, stdout=logs, stderr="")
            result = get_failure_logs("101", ".", max_lines=200)
        assert result.count("\n") <= 200

    def test_returns_empty_on_failure(self):
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not found"
            )
            result = get_failure_logs("999", ".")
        assert result == ""

    def test_returns_empty_when_gh_not_found(self):
        with patch(
            "superpower_workflow.integrations.ci_fix.subprocess.run",
            side_effect=FileNotFoundError("gh not found"),
        ):
            result = get_failure_logs("101", ".")
        assert result == ""


class TestCiFixLoop:
    def _ci_config(self, **overrides):
        cfg = {
            "enabled": True,
            "max_fix_attempts": 3,
            "wait_timeout_seconds": 600,
            "poll_interval_seconds": 1,
        }
        cfg.update(overrides)
        return cfg

    def test_returns_true_when_ci_passes_first_try(self):
        def mock_wait(cwd, **kw):
            return CIResult(status="passed", run_id="100")

        with patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait):
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(),
                run_claude_fn=lambda *a, **kw: ClaudeResult(),
                model="opus",
                system_prompt="",
            )
        assert success is True
        assert cost == 0.0

    def test_fixes_then_passes(self):
        wait_results = [
            CIResult(status="failed", run_id="101"),
            CIResult(status="passed", run_id="102"),
        ]
        call_count = [0]

        def mock_wait(cwd, **kw):
            idx = min(call_count[0], len(wait_results) - 1)
            call_count[0] += 1
            return wait_results[idx]

        def mock_claude(*a, **kw):
            return ClaudeResult(cost_usd=2.0)

        with (
            patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait),
            patch(
                "superpower_workflow.integrations.ci_fix.get_failure_logs", return_value="error log"
            ),
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_sub,
        ):
            mock_sub.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(),
                run_claude_fn=mock_claude,
                model="opus",
                system_prompt="",
            )
        assert success is True
        assert cost == 2.0

    def test_all_attempts_fail(self):
        def mock_wait(cwd, **kw):
            return CIResult(status="failed", run_id="200")

        def mock_claude(*a, **kw):
            return ClaudeResult(cost_usd=1.0)

        with (
            patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait),
            patch("superpower_workflow.integrations.ci_fix.get_failure_logs", return_value="err"),
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_sub,
        ):
            mock_sub.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(max_fix_attempts=2),
                run_claude_fn=mock_claude,
                model="opus",
                system_prompt="",
            )
        assert success is False
        assert cost == 2.0

    def test_timeout_on_initial_wait(self):
        def mock_wait(cwd, **kw):
            return CIResult(status="timeout")

        with patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait):
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(),
                run_claude_fn=lambda *a, **kw: ClaudeResult(),
                model="opus",
                system_prompt="",
            )
        assert success is False
        assert cost == 0.0

    def test_on_attempt_callback_called(self):
        wait_results = [
            CIResult(status="failed", run_id="300"),
            CIResult(status="passed", run_id="301"),
        ]
        call_count = [0]

        def mock_wait(cwd, **kw):
            idx = min(call_count[0], len(wait_results) - 1)
            call_count[0] += 1
            return wait_results[idx]

        attempts = []

        def on_attempt(attempt, max_attempts, status):
            attempts.append((attempt, max_attempts, status))

        with (
            patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait),
            patch("superpower_workflow.integrations.ci_fix.get_failure_logs", return_value="err"),
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_sub,
        ):
            mock_sub.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(),
                run_claude_fn=lambda *a, **kw: ClaudeResult(cost_usd=1.0),
                model="opus",
                system_prompt="",
                on_attempt=on_attempt,
            )
        assert len(attempts) >= 1
        assert attempts[0][0] == 1

    def test_uses_model_override_from_config(self):
        def mock_wait(cwd, **kw):
            return CIResult(status="failed", run_id="400")

        models_used = []

        def mock_claude(*a, **kw):
            models_used.append(kw.get("model", ""))
            return ClaudeResult(cost_usd=1.0)

        with (
            patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait),
            patch("superpower_workflow.integrations.ci_fix.get_failure_logs", return_value="err"),
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_sub,
        ):
            mock_sub.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(max_fix_attempts=1, model="sonnet"),
                run_claude_fn=mock_claude,
                model="opus",
                system_prompt="",
            )
        assert models_used[0] == "sonnet"
