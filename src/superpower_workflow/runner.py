"""Subprocess wrapper for claude -p with retry logic, JSON parsing, and session ID capture."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """v1.3.7 #2: send SIGTERM to the entire process group so claude -p
    sub-agents are killed too. Falls back to plain terminate() if the
    OS-specific call fails.
    """
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        elif os.name == "nt":
            # CREATE_NEW_PROCESS_GROUP allows CTRL_BREAK_EVENT
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        # Process already exited — nothing to do.
        return
    except Exception:
        # Fall back to plain terminate so we never leak the child
        import contextlib

        with contextlib.suppress(Exception):
            proc.terminate()


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


def extract_token_usage(raw: dict | None) -> dict[str, int | float]:
    """Pull token counts from a claude -p result envelope.

    Real claude responses put tokens under `usage.input_tokens` /
    `usage.output_tokens` / `usage.cache_creation_input_tokens` /
    `usage.cache_read_input_tokens`. The defensive fallback also reads
    top-level fields so legacy mocked dicts (which set them at the root)
    still work.

    Returns a dict with the 4 token counters plus a derived `cache_hit_rate`
    = cache_read / (cache_read + cache_creation + input_tokens), 0.0 when
    denominator is zero.
    """
    if not raw:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_hit_rate": 0.0,
        }
    usage = raw.get("usage") or {}

    def _pick(key: str) -> int:
        v = usage.get(key)
        if v is None:
            v = raw.get(key, 0)
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = _pick("input_tokens")
    output_tokens = _pick("output_tokens")
    cache_creation = _pick("cache_creation_input_tokens")
    cache_read = _pick("cache_read_input_tokens")
    denom = input_tokens + cache_creation + cache_read
    cache_hit_rate = round(cache_read / denom, 4) if denom > 0 else 0.0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "cache_hit_rate": cache_hit_rate,
    }


RETRY_DELAYS = [30, 120, 300]
TIMEOUT_SECONDS = 7200


def _invoke_claude(cmd: list[str], cwd: str, timeout: int) -> subprocess.CompletedProcess:
    """v1.3.7 #2: subprocess invocation isolated as a single mockable function.

    Pre-fix `subprocess.run` was called inline; tests mocked it directly,
    which couples test code to an implementation detail. Now both tests
    and runtime call `_invoke_claude` — switching to Popen + process-group
    signal forwarding is internal.

    Uses `Popen` + platform-specific new-process-group flags so SIGINT
    and SIGTERM in the parent propagate to the claude -p child (and its
    grandchildren). On `KeyboardInterrupt` or `subprocess.TimeoutExpired`,
    sends SIGTERM to the entire child process group before re-raising.
    """
    popen_kwargs: dict = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "posix":
        popen_kwargs["preexec_fn"] = os.setsid
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    child = subprocess.Popen(cmd, **popen_kwargs)
    try:
        stdout, stderr = child.communicate(timeout=timeout)
        returncode = child.returncode
    except subprocess.TimeoutExpired:
        _terminate_process_group(child)
        child.wait(timeout=5)
        raise
    except KeyboardInterrupt:
        _terminate_process_group(child)
        child.wait(timeout=10)
        raise
    return subprocess.CompletedProcess(
        args=cmd, returncode=returncode, stdout=stdout, stderr=stderr
    )


def run_claude(
    prompt: str,
    model: str,
    effort: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    resume_session: str | None = None,
    num_agents: int | None = None,
    budget_check_fn=None,
    charge_cost_fn=None,
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
    # v1.3.11 fix (parallel soak finding): orchestrator-level budget cap
    # was only checked at sequential milestone-loop iterations, not before
    # each run_claude attempt. In parallel mode, N workers × 4 retries × ~$1
    # per claude -p call could spend many * max_total_budget_usd before the
    # orchestrator noticed. Now: callers pass `budget_check_fn` (a closure
    # capturing self.state.total_cost_usd and max_total_budget_usd). It's
    # called before each attempt; on False, run_claude returns immediately
    # with `is_error=True, cost_usd=accumulated_cost` and the orchestrator's
    # _accumulate_cost charges whatever was spent prior to the abort.
    #
    # v1.3.9 fix (soak finding): accumulate cost across retries.
    # Pre-fix, when claude -p hit `--max-budget-usd` and returned
    # is_error=true with a non-zero cost (the cost up to the cap), the
    # outer retry loop simply discarded `parsed` and tried again. A
    # successful retry's cost overwrote the failed attempt's accounting,
    # so `state.total_cost_usd` only reflected the LAST attempt — and a
    # 4-retry chain of failures could spend many * budget while showing
    # ~0 in state. Real-world soak observed $1.5 lost on one retry alone.
    #
    # Now: track `accumulated_cost` across all attempts. Every return
    # path that has a parsed cost adds it to the accumulator and returns
    # that total. Synthetic error returns (no parsed result) keep the
    # accumulator unchanged.
    accumulated_cost = 0.0

    for attempt in range(len(RETRY_DELAYS) + 1):
        # v1.3.11: budget gate. Check before EACH attempt (including the
        # first) so a totally-busted-budget orchestrator never even starts
        # a new claude -p call.
        if budget_check_fn is not None and not budget_check_fn(accumulated_cost):
            logger.warning(
                "claude -p aborted before attempt %d/%d: orchestrator budget cap "
                "exceeded (accumulated_cost_this_call=$%.4f).",
                attempt + 1,
                len(RETRY_DELAYS) + 1,
                accumulated_cost,
            )
            return ClaudeResult(is_error=True, cost_usd=accumulated_cost)
        try:
            cmd = _build_command(
                prompt,
                model,
                effort,
                budget,
                system_prompt,
                fallback_model,
                resume_session,
                num_agents,
            )

            # v1.3.7 #2 fix: route through `_invoke_claude` which uses Popen
            # + new-process-group flags so SIGINT/SIGTERM in the parent
            # propagates to the claude -p child and its grandchildren.
            # Centralizing the call site here lets tests mock `_invoke_claude`
            # as one stable function instead of subprocess internals.
            result = _invoke_claude(cmd, cwd, TIMEOUT_SECONDS)

            if result.returncode == 0 and result.stdout.strip():
                parsed = _parse_json_output(result.stdout)
                # v1.3.9: always credit this attempt's cost to the running
                # total, even when is_error=true (cost was real spend).
                accumulated_cost += parsed.cost_usd
                # v1.3.12 fix (parallel soak finding): charge this attempt's
                # cost to the orchestrator's shared state IMMEDIATELY, not
                # at run_claude return. v1.3.11's budget gate only saw
                # state.total_cost_usd which wasn't updated mid-retry, so
                # workers' in-flight spend was invisible to the cap check.
                # Now each attempt's charge is visible to sibling workers'
                # budget gates within milliseconds.
                if charge_cost_fn is not None and parsed.cost_usd > 0:
                    try:
                        charge_cost_fn(parsed.cost_usd)
                    except Exception:
                        # Charge failure must not crash the run; the orchestrator
                        # has its own _accumulate_cost retry path. Log and continue.
                        logger.warning(
                            "charge_cost_fn raised on attempt %d/%d cost $%.4f",
                            attempt + 1,
                            len(RETRY_DELAYS) + 1,
                            parsed.cost_usd,
                        )
                if parsed.is_error:
                    upstream = ""
                    if parsed.raw:
                        upstream = parsed.raw.get("result") or parsed.raw.get("error") or ""
                    logger.warning(
                        "claude -p returned is_error=true (attempt %d/%d). "
                        "model=%s cost_this_attempt=$%.4f accumulated=$%.4f upstream=%r",
                        attempt + 1,
                        len(RETRY_DELAYS) + 1,
                        model,
                        parsed.cost_usd,
                        accumulated_cost,
                        upstream[:300],
                    )
                    if attempt < len(RETRY_DELAYS):
                        time.sleep(RETRY_DELAYS[attempt])
                        continue
                # Successful (or final error) return: include accumulated cost.
                parsed.cost_usd = accumulated_cost
                return parsed

            stderr_msg = (result.stderr or "")[:300]
            stdout_msg = (result.stdout or "")[:300]
            logger.warning(
                "claude -p subprocess failed (attempt %d/%d). returncode=%d "
                "accumulated_cost=$%.4f stderr=%r stdout=%r",
                attempt + 1,
                len(RETRY_DELAYS) + 1,
                result.returncode,
                accumulated_cost,
                stderr_msg,
                stdout_msg,
            )
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue

            return ClaudeResult(is_error=True, cost_usd=accumulated_cost)

        except subprocess.TimeoutExpired:
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            return ClaudeResult(is_error=True, timed_out=True, cost_usd=accumulated_cost)

    return ClaudeResult(is_error=True, cost_usd=accumulated_cost)


def _build_command(
    prompt: str,
    model: str,
    effort: str,
    budget: float,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    resume_session: str | None = None,
    num_agents: int | None = None,
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

    if num_agents and num_agents > 0:
        cmd.extend(["--num-agents", str(num_agents)])

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
