from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class CIResult:
    status: str  # "passed", "failed", "timeout"
    run_id: str = ""
    conclusion: str = ""


def wait_for_ci(
    cwd: str,
    timeout_seconds: int = 600,
    poll_interval_seconds: int = 30,
) -> CIResult:
    deadline = time.monotonic() + timeout_seconds
    consecutive_errors = 0
    while True:
        try:
            result = subprocess.run(
                ["gh", "run", "list", "--limit", "1", "--json", "status,conclusion,databaseId"],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30,
            )
        except FileNotFoundError:
            return CIResult(status="timeout", conclusion="gh CLI not found")
        if result.returncode == 0 and result.stdout.strip():
            try:
                runs = json.loads(result.stdout)
            except json.JSONDecodeError:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    return CIResult(status="timeout", conclusion="invalid response from gh CLI")
                if time.monotonic() >= deadline:
                    return CIResult(status="timeout")
                time.sleep(poll_interval_seconds)
                continue
            consecutive_errors = 0
            if runs:
                run = runs[0]
                run_id = str(run.get("databaseId", ""))
                status = run.get("status", "")
                conclusion = run.get("conclusion", "")
                if status == "completed":
                    if conclusion == "success":
                        return CIResult(status="passed", run_id=run_id, conclusion=conclusion)
                    return CIResult(status="failed", run_id=run_id, conclusion=conclusion)
        elif result.returncode != 0:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                return CIResult(status="timeout", conclusion="gh CLI errors")
        if time.monotonic() >= deadline:
            return CIResult(status="timeout")
        time.sleep(poll_interval_seconds)


def get_failure_logs(run_id: str, cwd: str, max_lines: int = 200) -> str:
    try:
        result = subprocess.run(
            ["gh", "run", "view", run_id, "--log-failed"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=60,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    lines = result.stdout.strip().split("\n")
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)


def ci_fix_loop(
    cwd: str,
    ci_config: dict[str, Any],
    run_claude_fn: Callable,
    model: str = "opus",
    system_prompt: str = "",
    fallback_model: str | None = None,
    on_attempt: Callable[[int, int, str], None] | None = None,
) -> tuple[bool, float, dict[str, int | float]]:
    """Run the CI-fix loop. Returns (success, total_cost, aggregated_token_usage).

    aggregated_token_usage sums input_tokens / output_tokens / cache_* across
    every claude -p call this loop made; cache_hit_rate is recomputed from the
    aggregated counters. Returns zeros when no claude calls were made.
    """
    from superpower_workflow.runner import extract_token_usage

    timeout = ci_config.get("wait_timeout_seconds", 600)
    poll = ci_config.get("poll_interval_seconds", 30)
    max_attempts = ci_config.get("max_fix_attempts", 3)
    fix_model = ci_config.get("model", model)
    total_cost = 0.0
    agg = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_hit_rate": 0.0,
    }

    def _accumulate(raw: dict | None) -> None:
        u = extract_token_usage(raw)
        for k in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            agg[k] += int(u[k])

    def _finalize_rate() -> None:
        denom = (
            agg["input_tokens"]
            + agg["cache_creation_input_tokens"]
            + agg["cache_read_input_tokens"]
        )
        agg["cache_hit_rate"] = (
            round(agg["cache_read_input_tokens"] / denom, 4) if denom > 0 else 0.0
        )

    result = wait_for_ci(cwd, timeout_seconds=timeout, poll_interval_seconds=poll)
    if result.status == "passed":
        _finalize_rate()
        return True, 0.0, agg
    if result.status == "timeout":
        _finalize_rate()
        return False, 0.0, agg

    for attempt in range(max_attempts):
        if on_attempt:
            on_attempt(attempt + 1, max_attempts, "retrying")
        logs = get_failure_logs(result.run_id, cwd)
        prompt = f"CI failed. Logs:\n{logs}\nFix the issue. Commit the fix."
        r = run_claude_fn(
            prompt,
            model=fix_model,
            effort="high",
            budget=10.0,
            cwd=cwd,
            system_prompt=system_prompt,
            fallback_model=fallback_model,
        )
        total_cost += r.cost_usd
        _accumulate(r.raw)
        push = subprocess.run(["git", "push"], capture_output=True, cwd=cwd, timeout=60)
        if push.returncode != 0:
            if on_attempt:
                on_attempt(attempt + 1, max_attempts, "push_failed")
            continue

        result = wait_for_ci(cwd, timeout_seconds=timeout, poll_interval_seconds=poll)
        if result.status == "passed":
            if on_attempt:
                on_attempt(attempt + 1, max_attempts, "passed")
            _finalize_rate()
            return True, total_cost, agg

    _finalize_rate()
    return False, total_cost, agg
