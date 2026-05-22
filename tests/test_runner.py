"""Tests for the claude -p runner module."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

from superpower_workflow.runner import (
    RETRY_DELAYS,
    TIMEOUT_SECONDS,
    run_claude,
)


class TestRunClaudeReturnsParseResult:
    """Test that run_claude returns parsed ClaudeResult."""

    def test_run_claude_returns_parsed_result(self):
        """run_claude parses JSON output correctly."""
        mock_output = json.dumps(
            {
                "result": "Task completed successfully",
                "total_cost_usd": 0.15,
                "session_id": "sess-123abc",
                "duration_ms": 2500,
                "is_error": False,
            }
        )

        with patch("superpower_workflow.runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

            result = run_claude(
                prompt="test prompt",
                model="opus",
                effort="medium",
                budget=1.0,
                cwd="/tmp",
            )

            assert result.text == "Task completed successfully"
            assert result.cost_usd == 0.15
            assert result.session_id == "sess-123abc"
            assert result.duration_ms == 2500
            assert result.is_error is False
            assert result.timed_out is False
            assert result.raw is not None


class TestRunClaudeBuildsCommand:
    """Test that run_claude builds the correct command."""

    def test_run_claude_builds_correct_command(self):
        """Command includes all expected flags."""
        with patch("superpower_workflow.runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps({"result": "ok", "total_cost_usd": 0.0}),
                stderr="",
            )

            run_claude(
                prompt="test prompt",
                model="opus",
                effort="high",
                budget=5.0,
                cwd="/tmp",
                system_prompt="Be helpful",
                fallback_model="sonnet",
                resume_session="sess-999",
            )

            # Get the command that was passed to subprocess.run
            call_args = mock_run.call_args
            cmd = call_args[0][0]

            assert "claude" in cmd
            assert "-p" in cmd
            assert "test prompt" in cmd
            assert "--model" in cmd
            assert "opus" in cmd
            assert "--effort" in cmd
            assert "high" in cmd
            assert "--output-format" in cmd
            assert "json" in cmd
            assert "--permission-mode" in cmd
            assert "bypassPermissions" in cmd
            assert "--max-budget-usd" in cmd
            assert "5.0" in cmd
            assert "--append-system-prompt" in cmd
            assert "Be helpful" in cmd
            assert "--fallback-model" in cmd
            assert "sonnet" in cmd
            assert "--resume" in cmd
            assert "sess-999" in cmd


class TestRunClaudeRetriesOnNetworkError:
    """Test that run_claude retries on network errors."""

    def test_run_claude_retries_on_network_error(self):
        """run_claude retries and succeeds on third attempt."""
        success_output = json.dumps(
            {
                "result": "success",
                "total_cost_usd": 0.1,
                "session_id": "sess-ok",
                "duration_ms": 1000,
                "is_error": False,
            }
        )

        with (
            patch("superpower_workflow.runner.subprocess.run") as mock_run,
            patch("superpower_workflow.runner.time.sleep") as mock_sleep,
        ):
            # Fail twice, succeed third time
            mock_run.side_effect = [
                MagicMock(returncode=1, stdout="", stderr="error"),
                MagicMock(returncode=1, stdout="", stderr="error"),
                MagicMock(returncode=0, stdout=success_output, stderr=""),
            ]

            result = run_claude(
                prompt="test",
                model="opus",
                effort="medium",
                budget=1.0,
                cwd="/tmp",
            )

            assert result.is_error is False
            assert result.text == "success"
            assert result.session_id == "sess-ok"
            # Should have called sleep twice (after 1st and 2nd failures)
            assert mock_sleep.call_count == 2
            assert mock_sleep.call_args_list[0][0][0] == RETRY_DELAYS[0]
            assert mock_sleep.call_args_list[1][0][0] == RETRY_DELAYS[1]


class TestRunClaudeFailsAfterMaxRetries:
    """Test that run_claude fails after max retries."""

    def test_run_claude_fails_after_max_retries(self):
        """run_claude returns is_error=True after all retries exhausted."""
        with (
            patch("superpower_workflow.runner.subprocess.run") as mock_run,
            patch("superpower_workflow.runner.time.sleep") as mock_sleep,
        ):
            # Always fail
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="persistent error")

            result = run_claude(
                prompt="test",
                model="opus",
                effort="medium",
                budget=1.0,
                cwd="/tmp",
            )

            assert result.is_error is True
            assert result.timed_out is False
            # Should retry len(RETRY_DELAYS) times, so len(RETRY_DELAYS) sleeps
            assert mock_sleep.call_count == len(RETRY_DELAYS)


class TestRunClaudeHandlesTimeout:
    """Test that run_claude handles subprocess timeout."""

    def test_run_claude_handles_timeout(self):
        """run_claude returns timed_out=True on TimeoutExpired."""
        with patch("superpower_workflow.runner.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("claude", TIMEOUT_SECONDS)

            result = run_claude(
                prompt="test",
                model="opus",
                effort="medium",
                budget=1.0,
                cwd="/tmp",
            )

            assert result.is_error is True
            assert result.timed_out is True
