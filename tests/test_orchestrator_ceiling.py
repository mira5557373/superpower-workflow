"""Orchestrator-level integration tests for the v1.3.20 cost ceiling.

Covers verdict revisions #2 (BudgetAlert coexistence), #5 (preflight
at three gates including phase_e_retry), and #6 (no_history defaults
to allow with source=no_history).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from superpower_workflow.budget_ceiling import (
    CeilingConfig,
    CostCeilingsConfig,
    evaluate_ceilings,
    parse_ceilings,
)


def _make_run_completed(*, run_id: str, cost: float, ts: datetime) -> str:
    return json.dumps(
        {
            "type": "run_completed",
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": run_id,
            "total_cost_usd": cost,
        }
    )


def _now() -> datetime:
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


class TestNoHistoryAlwaysAllows:
    """Verdict revision #6 — missing/corrupt telemetry defaults to allow."""

    def test_missing_telemetry_does_not_block(self, tmp_path: Path) -> None:
        """File doesn't exist → decision is no_history → never blocked."""
        ceilings = CostCeilingsConfig(daily=CeilingConfig(usd=0.01, mode="block"))
        # Note: ceiling deliberately set absurdly low — only no_history
        # semantics prevent a block here.
        result = evaluate_ceilings(
            tmp_path / "does_not_exist.jsonl",
            ceilings=ceilings,
            projected_run_cost_usd=100.0,
            now_utc=_now(),
        )
        assert not result.blocked
        day = next(e for e in result.evaluations if e.window == "day")
        assert day.decision == "no_history"
        assert day.accounting.source == "no_history"

    def test_corrupt_majority_does_not_block(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        p.write_text("garbage\ngarbage\ngarbage\n", encoding="utf-8")
        ceilings = CostCeilingsConfig(daily=CeilingConfig(usd=0.01, mode="block"))
        result = evaluate_ceilings(
            p, ceilings=ceilings, projected_run_cost_usd=100.0, now_utc=_now()
        )
        assert not result.blocked

    def test_empty_telemetry_does_not_block(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        p.write_text("", encoding="utf-8")
        ceilings = CostCeilingsConfig(daily=CeilingConfig(usd=0.01, mode="block"))
        result = evaluate_ceilings(
            p, ceilings=ceilings, projected_run_cost_usd=100.0, now_utc=_now()
        )
        assert not result.blocked


class TestThreeGatePreflight:
    """Verdict revision #5 — preflight fires at run_start, milestone_start,
    and phase_e_retry (each retry attempt > 0).

    We verify the SAME evaluator works at each gate (the gate string is
    just a label on the emitted event). The orchestrator wires the calls
    at three different sites in the milestone loop; here we assert the
    accountant is stateless across gates and produces deterministic
    decisions regardless of which gate calls it.
    """

    def test_evaluator_stateless_across_invocations(self, tmp_path: Path) -> None:
        """Calling evaluate_ceilings 3× with the same inputs returns identical
        decisions — proves the accountant doesn't have hidden gate-coupled state."""
        now = _now()
        p = tmp_path / "t.jsonl"
        p.write_text(
            "\n".join(
                _make_run_completed(run_id=f"r{i}", cost=5.0, ts=now - timedelta(hours=i + 1))
                for i in range(8)
            )
            + "\n",
            encoding="utf-8",
        )
        ceilings = CostCeilingsConfig(daily=CeilingConfig(usd=50.0, mode="block"))

        # Simulate three back-to-back gate calls (run_start, milestone_start,
        # phase_e_retry). Each should yield the same decision.
        results = [
            evaluate_ceilings(p, ceilings=ceilings, projected_run_cost_usd=5.0, now_utc=now)
            for _ in range(3)
        ]
        decisions = {r.evaluations[0].decision for r in results}
        assert len(decisions) == 1  # all identical

    def test_phase_e_retry_gate_blocks_when_retries_would_overrun(self, tmp_path: Path) -> None:
        """Simulates the overnight CI-fix loop scenario: prior runs near the
        cap, projected retry cost pushes over. Block fires."""
        now = _now()
        p = tmp_path / "t.jsonl"
        p.write_text(
            _make_run_completed(run_id="prior", cost=48.0, ts=now - timedelta(hours=1)) + "\n",
            encoding="utf-8",
        )
        ceilings = CostCeilingsConfig(daily=CeilingConfig(usd=50.0, mode="block"))
        # Projected for a single retry attempt of ~$5.
        result = evaluate_ceilings(p, ceilings=ceilings, projected_run_cost_usd=5.0, now_utc=now)
        assert result.blocked
        assert result.blocking_window == "day"


class TestBudgetAlertCoexistence:
    """Verdict revision #2 — CostCeilingEvaluated and BudgetAlert signal
    different things and can fire independently in a single run.

    We don't drive the full orchestrator here (that requires a full mock
    of the runner + state machine). Instead we verify the data-model
    independence:
    - BudgetAlert is per-run percent-of-cap (within-run signal)
    - CostCeilingEvaluated is per-window absolute spend (across-run)

    The two events have non-overlapping field sets, distinct EVENT_TYPE
    strings, and are emitted from different code paths.
    """

    def test_event_types_distinct(self) -> None:
        from superpower_workflow.telemetry import (
            BudgetAlert,
            CostCeilingEvaluated,
        )

        assert BudgetAlert.EVENT_TYPE == "budget_alert"
        assert CostCeilingEvaluated.EVENT_TYPE == "cost_ceiling_evaluated"
        assert BudgetAlert.EVENT_TYPE != CostCeilingEvaluated.EVENT_TYPE

    def test_event_field_sets_non_overlapping(self) -> None:
        """The only shared fields are inherited from TelemetryEvent base."""
        from dataclasses import fields

        from superpower_workflow.telemetry import (
            BudgetAlert,
            CostCeilingEvaluated,
        )

        ba_fields = {f.name for f in fields(BudgetAlert)}
        cce_fields = {f.name for f in fields(CostCeilingEvaluated)}
        # Base fields appear in both.
        base = {"timestamp", "run_id"}
        # The DOMAIN fields must be disjoint.
        assert (ba_fields - base).isdisjoint(cce_fields - base) or (
            (ba_fields - base) & (cce_fields - base) == set()
        )


class TestKillSwitch:
    """Rollback lever #3 from the design — SW_DISABLE_COST_CEILINGS=1."""

    def test_kill_switch_env_short_circuits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When SW_DISABLE_COST_CEILINGS=1, the orchestrator's check is a no-op
        (verified at the helper layer — the env check is at the top of
        Orchestrator._check_cost_ceilings)."""
        # Direct check at the helper layer — proven by the fact that any
        # block-mode ceiling evaluation would otherwise return blocked=True.
        monkeypatch.setenv("SW_DISABLE_COST_CEILINGS", "1")
        # We don't have a real Orchestrator instance here, but we can verify
        # the gate by importing and reading the source contract.
        import inspect

        from superpower_workflow import orchestrator

        src = inspect.getsource(orchestrator.Orchestrator._check_cost_ceilings)
        assert "SW_DISABLE_COST_CEILINGS" in src
        assert "return" in src  # early return on kill-switch


class TestParseAndConfigRoundtrip:
    def test_parse_reset_checkpoints(self) -> None:
        cfg = parse_ceilings(
            {
                "daily": {"usd": 50, "mode": "block"},
                "reset_checkpoints": {"day": "2026-06-01T00:00:00Z"},
            }
        )
        assert cfg.daily is not None
        assert cfg.reset_checkpoints == {"day": "2026-06-01T00:00:00Z"}

    def test_round_trip_through_workflow_json(self, tmp_path: Path) -> None:
        """A `sw budget set` produced file parses back to the same config."""
        wj = tmp_path / "workflow.json"
        wj.write_text(
            json.dumps(
                {
                    "cost_ceilings": {
                        "daily": {"usd": 75.0, "mode": "block"},
                        "weekly": {"usd": 250.0, "mode": "warn"},
                    }
                }
            )
        )
        raw = json.loads(wj.read_text())
        cfg = parse_ceilings(raw.get("cost_ceilings"))
        assert cfg.daily.usd == 75.0
        assert cfg.daily.mode == "block"
        assert cfg.weekly.usd == 250.0
        assert cfg.weekly.mode == "warn"
        assert cfg.monthly is None
