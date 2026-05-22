"""Subprocess wrapper for claude -p with retry logic, JSON parsing, and session ID capture."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass


@dataclass
class ClaudeResult:
    """Result from running claude -p command."""

    text: str = ""
    cost_usd: float = 0.0
    session_id: str = ""
    duration_ms: int = 0
    is_error: bool = False
    timed_out: bool = False
    raw: dict | None = None


RETRY_DELAYS = [10, 30, 90]
TIMEOUT_SECONDS = 7200


def run_claude(
    prompt: str,
    model: str,
    effort: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    resume_session: str | None = None,
) -> ClaudeResult:
    """Run claude -p command with retry logic, JSON parsing, and timeout handling.

    Args:
        prompt: The prompt to send to claude
        model: Model name (e.g., "opus", "sonnet")
        effort: Effort level (e.g., "medium", "high")
        budget: Maximum budget in USD
        cwd: Working directory for the command
        system_prompt: Optional system prompt to append
        fallback_model: Optional fallback model name
        resume_session: Optional session ID to resume

    Returns:
        ClaudeResult with parsed output, cost, session ID, duration, and error flags
    """
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            cmd = _build_command(
                prompt,
                model,
                effort,
                budget,
                system_prompt,
                fallback_model,
                resume_session,
            )

            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )

            if result.returncode == 0 and result.stdout.strip():
                return _parse_json_output(result.stdout)

            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue

            return ClaudeResult(is_error=True)

        except subprocess.TimeoutExpired:
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            return ClaudeResult(is_error=True, timed_out=True)

    return ClaudeResult(is_error=True)


def _build_command(
    prompt: str,
    model: str,
    effort: str,
    budget: float,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    resume_session: str | None = None,
) -> list[str]:
    """Build the claude -p command with all flags."""
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--effort",
        effort,
        "--output-format",
        "json",
        "--permission-mode",
        "bypassPermissions",
        "--max-budget-usd",
        str(budget),
    ]

    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])

    if fallback_model:
        cmd.extend(["--fallback-model", fallback_model])

    if resume_session:
        cmd.extend(["--resume", resume_session])

    return cmd


def _parse_json_output(stdout: str) -> ClaudeResult:
    """Parse JSON output from claude -p command.

    Expected format:
    {
        "result": "...",
        "total_cost_usd": 0.0,
        "session_id": "...",
        "duration_ms": 1000,
        "is_error": false
    }
    """
    try:
        data = json.loads(stdout)
        return ClaudeResult(
            text=data.get("result", ""),
            cost_usd=data.get("total_cost_usd", 0.0),
            session_id=data.get("session_id", ""),
            duration_ms=data.get("duration_ms", 0),
            is_error=data.get("is_error", False),
            raw=data,
        )
    except (json.JSONDecodeError, ValueError):
        return ClaudeResult(is_error=True)
