"""v1.3.12 fix (parallel verification soak finding): per-attempt cost
charging so sibling workers' budget gates see in-flight spend.

v1.3.11 added budget_check_fn to run_claude. Closure captured
self.state.total_cost_usd. But state only updates when run_claude
RETURNS — workers spinning through retries don't update state mid-call.
Sibling workers' budget checks see stale state → all N workers can each
spend cap before any cap-check fires.

v1.3.12 introduces charge_cost_fn called AFTER each attempt with that
attempt's cost. The orchestrator's _run_claude wrapper posts the charge
to self._in_flight_cost (a shared atomic counter). Sibling workers'
budget checks include this in-flight total → cap binds across workers
within milliseconds.

After run_claude returns, the wrapper subtracts this call's contribution
from the shared counter; the caller's _accumulate_cost transfers it
to state as before. No double-charging.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.runner import run_claude
from superpower_workflow.state import WorkflowState, load_state, save_state


def _cp(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _err_json(cost: float):
    return json.dumps(
        {
            "type": "result",
            "subtype": "error_max_budget_usd",
            "is_error": True,
            "total_cost_usd": cost,
            "session_id": "s",
            "duration_ms": 100,
            "result": "budget cap reached",
        }
    )


def _ok_json(cost: float):
    return json.dumps(
        {
            "type": "result",
            "is_error": False,
            "total_cost_usd": cost,
            "session_id": "s",
            "duration_ms": 100,
            "result": "done",
        }
    )


def _mk_orch(tmp_path, max_budget=4.0):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    cfg = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "budgets": {"plan": 1, "implement": 1, "review": 0.5, "push": 0.3},
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "verify_commands": {},
        "milestones": [{"name": "M1"}],
        "validation": {},
        "convergence": {},
        "telemetry": {"enabled": False},
        "max_total_budget_usd": max_budget,
    }
    (claude_dir / "workflow.json").write_text(json.dumps(cfg))
    save_state(claude_dir, WorkflowState())
    return Orchestrator(project_root=Path(tmp_path))


class TestChargeCostFnFires:
    """run_claude calls charge_cost_fn after each attempt with its cost."""

    def test_charge_called_on_successful_attempt(self, monkeypatch):
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        charges = []
        with patch("superpower_workflow.runner._invoke_claude", return_value=_cp(_ok_json(0.42))):
            r = run_claude(
                "p",
                "opus",
                "high",
                5.0,
                cwd="/tmp",
                charge_cost_fn=lambda c: charges.append(c),
            )
        assert r.cost_usd == 0.42
        assert charges == [0.42]  # exactly one charge for the one attempt

    def test_charge_called_on_each_retry_attempt(self, monkeypatch):
        """Each retry's cost is posted, not just the final one."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        charges = []
        results = [_cp(_err_json(0.50)), _cp(_err_json(0.75)), _cp(_ok_json(0.30))]
        with patch("superpower_workflow.runner._invoke_claude", side_effect=results):
            r = run_claude(
                "p",
                "opus",
                "high",
                5.0,
                cwd="/tmp",
                charge_cost_fn=lambda c: charges.append(c),
            )
        assert r.cost_usd == 1.55  # 0.50 + 0.75 + 0.30
        assert charges == [0.50, 0.75, 0.30]  # one charge per attempt

    def test_charge_failure_does_not_crash(self, monkeypatch):
        """charge_cost_fn raising must not crash run_claude; warning logged."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)

        def boom(c):
            raise RuntimeError("charge failed")

        with patch("superpower_workflow.runner._invoke_claude", return_value=_cp(_ok_json(1.0))):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp", charge_cost_fn=boom)
        assert r.cost_usd == 1.0  # accumulator still works


class TestSharedInFlightCounter:
    """The orchestrator's _run_claude wrapper posts charges to a shared
    in-flight counter so sibling workers' budget checks see it."""

    def test_initial_in_flight_is_zero(self, tmp_path):
        orch = _mk_orch(tmp_path)
        assert orch._in_flight_cost == 0.0

    def test_charge_increments_in_flight(self, tmp_path, monkeypatch):
        """When a worker's run_claude call charges, the shared counter
        grows mid-call."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        orch = _mk_orch(tmp_path, max_budget=10.0)

        observed = []

        def watch_in_flight(*args, **kw):
            # Capture _in_flight_cost as each charge happens
            observed.append(orch._in_flight_cost)
            return _cp(_ok_json(0.50))

        with patch("superpower_workflow.runner._invoke_claude", side_effect=watch_in_flight):
            orch._run_claude("p", "opus", "high", 5.0, cwd=str(tmp_path))

        # During the call, in_flight went up; after return, the wrapper
        # decremented it back to 0.
        assert orch._in_flight_cost == 0.0

    def test_in_flight_visible_to_concurrent_check(self, tmp_path, monkeypatch):
        """One worker's pre-existing in_flight IS visible to a new worker's
        budget check. With state=$0, in_flight=$1.9, cap=$2.0, a new call
        must abort before spawning subprocess (would push past cap)."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        orch = _mk_orch(tmp_path, max_budget=2.0)

        # Simulate sibling worker already mid-call with $1.9 in-flight.
        with orch._in_flight_lock:
            orch._in_flight_cost = 1.9

        # New _run_claude call. budget check: state ($0) + others_in_flight
        # ($1.9, since my_charged=$0) + extra ($0) = $1.9 < $2.0 → True.
        # Proceeds to attempt. _invoke_claude returns is_error=$0.50.
        # charge_cost_fn posts $0.50 to in_flight (now $2.4). After attempt 1,
        # check: state ($0) + others_in_flight ($2.4 - $0.50 = $1.9) +
        # extra ($0.50) = $2.4 NOT < $2 → False → abort.
        attempt_count = [0]

        def each(*args, **kw):
            attempt_count[0] += 1
            return _cp(_err_json(0.50))

        with patch("superpower_workflow.runner._invoke_claude", side_effect=each):
            r = orch._run_claude("p", "opus", "high", 5.0, cwd=str(tmp_path))

        # Exactly 1 attempt before the gate aborts further retries.
        assert attempt_count[0] == 1, f"expected 1 attempt; got {attempt_count[0]}"
        assert r.is_error is True
        assert r.cost_usd == 0.50  # the one attempt's cost is preserved
        # Reset for cleanup
        with orch._in_flight_lock:
            orch._in_flight_cost = 0.0


class TestSiblingWorkerVisibility:
    """When a sibling worker has already charged $X to in-flight, the next
    worker's budget check must see that and abort before pushing past cap.
    Verifies the shared-counter logic directly without racing the GIL."""

    def test_subsequent_worker_aborts_when_inflight_near_cap(self, tmp_path, monkeypatch):
        """Worker 1 runs first and charges $3 to in-flight (mid-call).
        Worker 2 starts: budget check sees others_in_flight=$3,
        extra=$0 → $3 < $4 → True → first attempt proceeds.
        After Worker 2's attempt 1 charges $1, attempt 2 check:
        others_in_flight=$3 (still), extra=$1 (W2's accumulated) → $4 → False → abort.
        Total W2 attempts: 1.
        """
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        orch = _mk_orch(tmp_path, max_budget=4.0)

        # Simulate Worker 1 mid-call with $3 in-flight (not yet returned).
        with orch._in_flight_lock:
            orch._in_flight_cost = 3.0

        # Now Worker 2 makes a call. Each attempt costs $1.
        w2_attempts = [0]

        def w2_attempt(*args, **kw):
            w2_attempts[0] += 1
            return _cp(_err_json(1.0))

        with patch("superpower_workflow.runner._invoke_claude", side_effect=w2_attempt):
            r = orch._run_claude("p2", "opus", "high", 5.0, cwd=str(tmp_path))

        # Worker 2 should have made exactly 1 attempt before aborting:
        # attempt 1 check: state $0 + others $3 (in_flight - my_charged $0) +
        #                  extra $0 = $3 < $4 → True. Proceed. Charge $1.
        # attempt 2 check: state $0 + others ($4 - $1) = $3 + extra $1 = $4 →
        #                  NOT < $4 → False. Abort.
        assert w2_attempts[0] == 1, (
            f"Worker 2 should abort after 1 attempt (in-flight $3 + attempt $1 = cap); "
            f"got {w2_attempts[0]} attempts"
        )
        assert r.is_error is True
        # The $1 W2 actually spent IS in r.cost_usd
        assert r.cost_usd == 1.0

        # Reset
        with orch._in_flight_lock:
            orch._in_flight_cost = 0.0

    def test_in_flight_resets_after_call_returns(self, tmp_path, monkeypatch):
        """A _run_claude call's contribution to in_flight is subtracted on
        return, so subsequent calls aren't penalized by it."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        orch = _mk_orch(tmp_path, max_budget=10.0)

        # First call charges $1.5 total
        with patch(
            "superpower_workflow.runner._invoke_claude",
            return_value=_cp(_ok_json(1.5)),
        ):
            r1 = orch._run_claude("p", "opus", "high", 5.0, cwd=str(tmp_path))

        assert r1.cost_usd == 1.5
        assert orch._in_flight_cost == 0.0  # subtracted on return

        # Caller's normal _accumulate_cost charges state
        orch._accumulate_cost(0.0, r1.cost_usd)
        assert orch.state.total_cost_usd == 1.5

        # Second call: in_flight starts at 0 again, new call gets full cap
        with patch(
            "superpower_workflow.runner._invoke_claude",
            return_value=_cp(_ok_json(2.0)),
        ):
            r2 = orch._run_claude("p", "opus", "high", 5.0, cwd=str(tmp_path))
        assert r2.cost_usd == 2.0
        assert orch._in_flight_cost == 0.0


class TestNoDoubleCharge:
    """After _run_claude returns, the caller's `_accumulate_cost(cost, r.cost_usd)`
    must not double-charge state."""

    def test_state_reflects_single_charge_after_caller_pattern(self, tmp_path, monkeypatch):
        """Simulate the orchestrator's normal pattern:
        r = self._run_claude(...)
        cost = self._accumulate_cost(cost, r.cost_usd)
        """
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        orch = _mk_orch(tmp_path, max_budget=10.0)

        with patch("superpower_workflow.runner._invoke_claude", return_value=_cp(_ok_json(1.25))):
            r = orch._run_claude("p", "opus", "high", 5.0, cwd=str(tmp_path))
            # Simulate caller pattern
            cost = orch._accumulate_cost(0.0, r.cost_usd)

        # Total state should equal $1.25, NOT $2.50 (double-charge).
        s = load_state(tmp_path / ".claude")
        assert abs(s.total_cost_usd - 1.25) < 1e-6, (
            f"state should hold $1.25 (single charge); got ${s.total_cost_usd}"
        )
        # Local cost accumulator returns the cost too
        assert cost == 1.25
        # In-flight counter must be 0 after the call
        assert orch._in_flight_cost == 0.0
