from __future__ import annotations

import json
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.integrations.ci_fix import get_failure_logs, wait_for_ci


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
