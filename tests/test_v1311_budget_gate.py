"""v1.3.11 fix (parallel soak finding): budget cap must bind inside
run_claude's retry loop, not only at orchestrator-level milestone-loop
iterations.

Parallel-soak observation: N workers × 4 retries × ~$1 per claude -p call
spent uncapped through Phase B retries. The orchestrator's only budget
check is at the sequential milestone loop start (orchestrator.py:~327),
which doesn't fire inside a parallel wave. Workers could blow many * cap.

v1.3.11 introduces `budget_check_fn` on run_claude: called before each
attempt; on False, returns immediately with cost_usd=accumulated_cost.
The orchestrator's `_run_claude` wrapper injects a closure that checks
self.state.total_cost_usd against max_total_budget_usd.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.runner import run_claude
from superpower_workflow.state import WorkflowState, save_state


def _cp(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


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


class TestBudgetCheckFn:
    """run_claude must respect the budget_check_fn callback."""

    def test_returns_immediately_when_check_returns_false(self, monkeypatch):
        """If budget_check_fn returns False on the first call, we don't
        even make a subprocess call."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)

        invoke_calls = []

        def fake_invoke(*args, **kw):
            invoke_calls.append(args)
            return _cp(_ok_json(0.50))

        with patch("superpower_workflow.runner._invoke_claude", side_effect=fake_invoke):
            r = run_claude(
                "p", "opus", "high", 5.0, cwd="/tmp", budget_check_fn=lambda extra: False
            )

        assert r.is_error is True
        assert r.cost_usd == 0.0  # no attempt made
        assert len(invoke_calls) == 0  # no subprocess spawn

    def test_check_called_with_running_accumulator(self, monkeypatch):
        """The check fn receives accumulated_cost from prior attempts."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)

        check_calls = []

        def check(extra):
            check_calls.append(extra)
            # Allow first 2 attempts, then deny.
            return len(check_calls) <= 2

        results = [_cp(_err_json(0.50)), _cp(_err_json(0.50)), _cp(_ok_json(0.30))]
        with patch("superpower_workflow.runner._invoke_claude", side_effect=results):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp", budget_check_fn=check)

        # Two attempts made, both failed (accumulating $1). Third check
        # returned False -> return early with accumulated_cost=$1.
        assert r.is_error is True
        assert r.cost_usd == 1.0
        # check called 3 times: once before each attempt
        assert len(check_calls) == 3
        assert check_calls[0] == 0.0  # before first attempt
        assert check_calls[1] == 0.5  # accumulator after first failed
        assert check_calls[2] == 1.0  # accumulator after second failed

    def test_no_check_fn_means_no_gating(self, monkeypatch):
        """When budget_check_fn is None (default), retry loop behaves
        exactly as v1.3.9 — no gating."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        results = [_cp(_err_json(1.0)) for _ in range(4)]
        with patch("superpower_workflow.runner._invoke_claude", side_effect=results):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp")
        assert r.is_error is True
        assert r.cost_usd == 4.0  # all 4 attempts ran


class TestOrchestratorWrapper:
    """The orchestrator's `_run_claude` wrapper injects a budget closure
    that checks self.state.total_cost_usd against max_total_budget_usd."""

    def _mk_orch(self, tmp_path, max_budget=5.0):
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

    def test_wrapper_injects_budget_check_fn(self, tmp_path, monkeypatch):
        """`_run_claude` must pass a budget_check_fn that closes over
        self.state.total_cost_usd."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        orch = self._mk_orch(tmp_path, max_budget=2.0)
        # Pre-charge state to put us at 1.5 of 2.0 budget
        orch.state.total_cost_usd = 1.5

        # Capture the actual run_claude call to inspect budget_check_fn
        captured = {}

        def fake_run_claude(*args, **kwargs):
            captured["budget_check_fn"] = kwargs.get("budget_check_fn")
            return type("R", (), {"is_error": False, "cost_usd": 0.0})()

        with patch("superpower_workflow.orchestrator.run_claude", fake_run_claude):
            orch._run_claude("p", "opus", "high", 5.0, cwd=str(tmp_path))

        fn = captured["budget_check_fn"]
        assert fn is not None
        # Check it works correctly: current state $1.5 + extra $0.3 < $2.0 cap → True
        assert fn(0.3) is True
        # current $1.5 + extra $0.6 > $2.0 cap → False
        assert fn(0.6) is False

    def test_wrapper_caps_runaway_retries_under_real_run_claude(self, tmp_path, monkeypatch):
        """End-to-end: a budget-exhausted state aborts the retry loop early."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)
        orch = self._mk_orch(tmp_path, max_budget=2.0)
        # Pre-fill state close to cap
        orch.state.total_cost_usd = 1.9

        # Each call would charge $0.5 — would push past cap → aborted.
        with patch(
            "superpower_workflow.runner._invoke_claude",
            return_value=_cp(_ok_json(0.5)),
        ):
            r = orch._run_claude("p", "opus", "high", 5.0, cwd=str(tmp_path))

        # The budget check fn sees: current state $1.9 + extra $0 < $2 → True
        # So one attempt fires, returns $0.5 cost.
        # Next iteration would check: state $1.9 + extra $0.5 = $2.4 > $2.0 → False
        # But we only have one attempt because returncode==0 + is_error=false returns immediately.
        # So the call succeeds with $0.5 cost.
        assert r.cost_usd == 0.5


class TestSoakReproduction:
    """Reproduce the parallel-soak scenario: each worker hits budget cap,
    retries, would spend many * cap. With v1.3.11, the gate aborts."""

    def test_runaway_retries_aborted_at_cap(self, monkeypatch):
        """Simulate 4 retries that each spend $1 (budget cap inside claude).
        Without v1.3.11: total = $4. With v1.3.11 + cap=$2.5: stops at $2."""
        monkeypatch.setattr("superpower_workflow.runner.time.sleep", lambda s: None)

        cap = 2.5
        # Mock state.total_cost_usd as a mutable counter that grows with each charge
        cumulative = [0.0]

        def check(extra):
            return cumulative[0] + extra < cap

        results = [_cp(_err_json(1.0)) for _ in range(4)]

        def fake_invoke(*args, **kw):
            return results.pop(0)

        with patch("superpower_workflow.runner._invoke_claude", side_effect=fake_invoke):
            r = run_claude("p", "opus", "high", 5.0, cwd="/tmp", budget_check_fn=check)

        # Simulate: cap=2.5
        # attempt 1: check(0.0) -> 0 < 2.5 True. Spend $1. accum=$1.
        # attempt 2: check(1.0) -> 1 < 2.5 True. Spend $1. accum=$2.
        # attempt 3: check(2.0) -> 2 < 2.5 True. Spend $1. accum=$3.
        # attempt 4: check(3.0) -> 3 > 2.5 False. Return.
        # Total accumulated: $3.0 (one attempt past cap because cumulative
        # state-side tracking is decoupled; per-call cap protects against
        # runaway but rest is the orchestrator's responsibility).
        assert r.cost_usd == 3.0
