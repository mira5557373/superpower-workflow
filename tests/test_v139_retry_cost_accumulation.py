"""v1.3.9 fix (soak finding): run_claude must accumulate cost across retries.

Real soak observation: claude -p with `--max-budget-usd 1.5` returned
is_error=true after spending $1.5278. run_claude retried; the next
attempt succeeded at $0.895. State recorded only $0.895 — the failed
attempt's $1.5278 was discarded. Real spend understated by 63%.

Pre-v1.3.9, `run_claude` retried failures by `continue` without
preserving `parsed.cost_usd`. v1.3.9 introduces an `accumulated_cost`
counter that survives the retry loop.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from superpower_workflow.runner import run_claude


def _cp(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _err_json(cost: float, session: str = "s") -> str:
    """Emit an is_error=true result with a real cost (like budget-cap exhaustion)."""
    import json

    return json.dumps(
        {
            "type": "result",
            "subtype": "error_max_budget_usd",
            "is_error": True,
            "total_cost_usd": cost,
            "session_id": session,
            "duration_ms": 100,
            "result": "budget cap reached",
        }
    )


def _ok_json(cost: float, session: str = "s") -> str:
    import json

    return json.dumps(
        {
            "type": "result",
            "is_error": False,
            "total_cost_usd": cost,
            "session_id": session,
            "duration_ms": 100,
            "result": "done",
        }
    )


class TestRetryCostAccumulation:
    """The critical regression test for the soak finding."""

    def test_failed_then_successful_attempt_sums_costs(self, monkeypatch):
        """Attempt 1 fails at $1.5278 (budget cap); attempt 2 succeeds at $0.895.
        Returned cost must be $1.5278 + $0.895 = $2.4228, NOT $0.895."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        results = [_cp(_err_json(1.5278)), _cp(_ok_json(0.895))]

        with patch("superpower_workflow.runner._invoke_claude", side_effect=results):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp")

        assert r.is_error is False
        assert abs(r.cost_usd - (1.5278 + 0.895)) < 1e-6, (
            f"expected accumulated $2.4228; got ${r.cost_usd}"
        )

    def test_three_failed_attempts_then_success_accumulates_all(self, monkeypatch):
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        results = [
            _cp(_err_json(0.50)),
            _cp(_err_json(0.75)),
            _cp(_err_json(1.20)),
            _cp(_ok_json(0.30)),
        ]
        with patch("superpower_workflow.runner._invoke_claude", side_effect=results):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp")
        assert r.is_error is False
        assert abs(r.cost_usd - (0.50 + 0.75 + 1.20 + 0.30)) < 1e-6

    def test_all_retries_fail_returns_accumulated_cost(self, monkeypatch):
        """Even when all retries are exhausted, the cost spent so far is
        returned — orchestrator's _accumulate_cost charges it to state."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        results = [_cp(_err_json(0.50)) for _ in range(4)]  # all 4 attempts fail
        with patch("superpower_workflow.runner._invoke_claude", side_effect=results):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp")
        assert r.is_error is True
        assert abs(r.cost_usd - 4 * 0.50) < 1e-6, (
            f"expected $2.00 accumulated across 4 failed attempts; got ${r.cost_usd}"
        )

    def test_single_success_returns_only_its_cost(self, monkeypatch):
        """Sanity check: with no retries, cost is just the single attempt's."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        with patch("superpower_workflow.runner._invoke_claude", return_value=_cp(_ok_json(0.42))):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp")
        assert r.is_error is False
        assert r.cost_usd == 0.42

    def test_subprocess_failure_then_success_does_not_accumulate(self, monkeypatch):
        """When the subprocess itself fails (non-zero returncode, no parseable
        cost), there's no cost to credit. The successful retry returns its
        own cost only — no synthetic accumulation."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        results = [
            _cp("", returncode=1),  # subprocess failure, no parseable output
            _cp(_ok_json(0.50)),
        ]
        with patch("superpower_workflow.runner._invoke_claude", side_effect=results):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp")
        assert r.is_error is False
        assert r.cost_usd == 0.50  # only the successful attempt's cost

    def test_timeout_exhausted_returns_accumulated_cost_for_earlier_attempts(self, monkeypatch):
        """If earlier attempts had parsed cost (error_max_budget_usd) and
        the final attempt times out, the accumulated earlier costs are
        still returned so the orchestrator can charge them."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)

        def side_effect(*args, **kw):
            # Simulate: attempt 1 returns is_error with cost; remaining time out.
            if side_effect.calls == 0:
                side_effect.calls += 1
                return _cp(_err_json(1.0))
            side_effect.calls += 1
            raise subprocess.TimeoutExpired(cmd=args[0] if args else [], timeout=1)

        side_effect.calls = 0
        with patch("superpower_workflow.runner._invoke_claude", side_effect=side_effect):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp")
        assert r.is_error is True
        assert r.timed_out is True
        # Cost from the first attempt is preserved.
        assert r.cost_usd == 1.0, (
            f"earlier attempt's cost should survive a later timeout; got ${r.cost_usd}"
        )


class TestSoakReproduction:
    """Reproduce the exact dollar amounts observed in the v1.3.8 soak."""

    def test_exact_soak_pattern_returns_correct_total(self, monkeypatch):
        """Soak observation: attempt 1 hit budget cap at $1.5278;
        attempt 2 succeeded at $0.895 with no error. Curator separately
        spent $0.19. The MILESTONE total (Phase A + curator) should be
        $1.5278 + $0.895 + $0.19 = $2.6128.

        Pre-fix: state showed only $0.895 + $0.19 = $1.085 (the $1.53
        from the budget-cap failure was lost). Post-fix: state shows
        $2.4228 + $0.19 = $2.6128.
        """
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        # Phase A: attempt 1 budget-cap, attempt 2 success.
        phase_a_results = [_cp(_err_json(1.5278)), _cp(_ok_json(0.895))]
        with patch("superpower_workflow.runner._invoke_claude", side_effect=phase_a_results):
            r_phase_a = run_claude("plan-prompt", "opus", "high", 1.5, cwd="/tmp")
        # Phase A's effective cost (what orchestrator charges via _accumulate_cost):
        assert abs(r_phase_a.cost_usd - 2.4228) < 1e-6
        assert r_phase_a.is_error is False

        # If we add the curator's $0.19, the milestone-level total matches what
        # the real soak SHOULD have recorded:
        expected_milestone_total = r_phase_a.cost_usd + 0.19
        assert abs(expected_milestone_total - 2.6128) < 1e-3
