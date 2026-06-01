"""Tests for v1.3.17 / v1.1.9.1 — BudgetAlert + RunCostProjection wiring.

Pins the orchestrator-level integration:

BudgetAlert (Verdict 1 + 2 from cost-projection workflow):
- Fires inside _accumulate_cost UNDER the existing _state_lock — so
  parallel siblings can't both fire 50%.
- Monotonic via state.last_budget_alert_pct — once 75% fires, cost
  oscillating around it won't re-emit.
- Leap-skip: $0 → $95 emits ONE alert at threshold=75, not three.
- Disabled when max_total_budget_usd is missing/0/inf.
- Survives state reload (last_budget_alert_pct persisted).

RunCostProjection: emitted by _emit_run_cost_projection helper —
verified via direct call (full driver-loop coverage by integration
golden trace).
"""

from __future__ import annotations

from pathlib import Path

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.state import WorkflowState, save_state
from superpower_workflow.telemetry import BudgetAlert, RunCostProjection, TelemetryEmitter


def _mk_orch(tmp_path: Path, *, max_budget: float = 100.0) -> Orchestrator:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    cfg = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "budgets": {"plan": 25, "implement": 25, "review": 10, "push": 3},
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "verify_commands": {},
        "milestones": [{"name": "M1"}],
        "validation": {},
        "telemetry": {"enabled": False},
        "max_total_budget_usd": max_budget,
    }
    (claude_dir / "workflow.json").write_text(__import__("json").dumps(cfg))
    save_state(claude_dir, WorkflowState())
    orch = Orchestrator(project_root=tmp_path)
    orch._telemetry = TelemetryEmitter.disabled()
    return orch


def _captured_events(orch: Orchestrator) -> list:
    """Replace _telemetry.emit with a list-appending mock so we can
    inspect emitted events."""
    captured: list = []
    real_emit = orch._telemetry.emit

    def spy(event):
        captured.append(event)
        real_emit(event)

    orch._telemetry.emit = spy  # type: ignore[method-assign]
    return captured


# ---- BudgetAlert single-fire ----


class TestBudgetAlertSingleFire:
    def test_fires_exactly_once_at_threshold(self, tmp_path):
        orch = _mk_orch(tmp_path, max_budget=100.0)
        events = _captured_events(orch)

        # Cross 50% via 3 small charges: 40 → 60 → 61 → 62
        orch._accumulate_cost(0.0, 40.0)  # 40% — no alert
        orch._accumulate_cost(0.0, 20.0)  # 60% — fires 50
        orch._accumulate_cost(0.0, 1.0)  # 61% — no alert
        orch._accumulate_cost(0.0, 1.0)  # 62% — no alert

        alerts = [e for e in events if isinstance(e, BudgetAlert)]
        assert len(alerts) == 1
        assert alerts[0].threshold == 50
        # Monotonic state field bumped.
        assert orch.state.last_budget_alert_pct == 50


class TestBudgetAlertLeapSkip:
    def test_leap_from_0_to_95_emits_one_alert_at_90(self, tmp_path):
        orch = _mk_orch(tmp_path, max_budget=100.0)
        events = _captured_events(orch)

        orch._accumulate_cost(0.0, 95.0)  # one shot to 95%

        alerts = [e for e in events if isinstance(e, BudgetAlert)]
        assert len(alerts) == 1
        # Highest crossed bucket is 90 (not 50, 75, AND 90).
        assert alerts[0].threshold == 90
        # Raw pct preserved.
        assert alerts[0].percent_of_cap == 95.0
        # State advances past all skipped buckets.
        assert orch.state.last_budget_alert_pct == 90


class TestBudgetAlertProgressive:
    def test_each_threshold_fires_once(self, tmp_path):
        orch = _mk_orch(tmp_path, max_budget=100.0)
        events = _captured_events(orch)

        # 50% → 75% → 90% → 100%
        orch._accumulate_cost(0.0, 50.0)  # fires 50
        orch._accumulate_cost(0.0, 25.0)  # fires 75
        orch._accumulate_cost(0.0, 15.0)  # fires 90
        orch._accumulate_cost(0.0, 10.0)  # fires 100

        alerts = [e for e in events if isinstance(e, BudgetAlert)]
        thresholds = [a.threshold for a in alerts]
        assert thresholds == [50, 75, 90, 100]


# ---- BudgetAlert disabled when no cap ----


class TestBudgetAlertNoCap:
    def test_no_alert_when_max_budget_zero(self, tmp_path):
        orch = _mk_orch(tmp_path, max_budget=0.0)
        events = _captured_events(orch)
        orch._accumulate_cost(0.0, 1000.0)
        assert not any(isinstance(e, BudgetAlert) for e in events)
        assert orch.state.last_budget_alert_pct == 0

    def test_no_alert_when_max_budget_inf(self, tmp_path):
        """max_total_budget_usd=inf means no cap configured."""
        orch = _mk_orch(tmp_path, max_budget=float("inf"))
        events = _captured_events(orch)
        orch._accumulate_cost(0.0, 1000.0)
        assert not any(isinstance(e, BudgetAlert) for e in events)


# ---- BudgetAlert cost-down idempotency ----


class TestBudgetAlertMonotonic:
    def test_refund_does_not_refire(self, tmp_path):
        """Cost goes up to 80%, then last_budget_alert_pct=75. We can't
        actually refund via _accumulate_cost (no negative deltas exposed
        in the public API), but we can test state directly: if cost
        oscillates and we re-add positive delta, the threshold is not
        re-fired."""
        orch = _mk_orch(tmp_path, max_budget=100.0)
        events = _captured_events(orch)

        orch._accumulate_cost(0.0, 80.0)  # fires 75
        first_count = len([e for e in events if isinstance(e, BudgetAlert)])
        assert first_count == 1

        # Manually simulate "refund" by lowering state then adding back.
        orch.state.total_cost_usd = 70.0
        orch._accumulate_cost(0.0, 5.0)  # 75% again — should NOT refire

        alerts_after = [e for e in events if isinstance(e, BudgetAlert)]
        # Still just one alert; last_budget_alert_pct is sticky.
        assert len(alerts_after) == 1


# ---- BudgetAlert state persistence ----


class TestBudgetAlertSurvivesResume:
    def test_last_alert_pct_persisted_to_disk(self, tmp_path):
        from superpower_workflow.state import load_state

        orch = _mk_orch(tmp_path, max_budget=100.0)
        orch._accumulate_cost(0.0, 80.0)  # fires 75

        # Re-read state from disk in a fresh process simulation.
        reloaded = load_state(orch.claude_dir)
        assert reloaded.last_budget_alert_pct == 75


# ---- RunCostProjection emission ----


class TestRunCostProjectionEmission:
    def test_emit_run_cost_projection_fires_event(self, tmp_path):
        from superpower_workflow.phases import PhaseContext

        orch = _mk_orch(tmp_path)
        events = _captured_events(orch)
        orch._current_milestone_name = "M1"
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={"name": "M1"},
            spec="spec.md",
            sections="",
            model="opus",
            budgets={},
        )
        orch._emit_run_cost_projection(
            ctx,
            phase_just_completed="plan",
            remaining_in_milestone=["implement", "review", "push"],
            completed_in_milestone=["plan"],
        )
        projections = [e for e in events if isinstance(e, RunCostProjection)]
        assert len(projections) == 1
        p = projections[0]
        assert p.milestone == "M1"
        assert p.milestones_total == 1
        assert p.source in ("cold_start", "partial_history", "full_history")

    def test_emit_run_cost_projection_never_raises(self, tmp_path):
        """Best-effort contract — projection failures (e.g. corrupt
        telemetry, missing config) must NEVER break the milestone loop."""
        from superpower_workflow.phases import PhaseContext

        orch = _mk_orch(tmp_path)
        # Corrupt the telemetry file.
        (orch.claude_dir / "sw-telemetry.jsonl").write_text("{ broken }")
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={"name": "M1"},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        # Should not raise.
        orch._emit_run_cost_projection(
            ctx,
            phase_just_completed="plan",
            remaining_in_milestone=["implement"],
            completed_in_milestone=["plan"],
        )

    def test_emit_when_telemetry_none(self, tmp_path):
        """If _telemetry is None (pre-Orchestrator.run() init), emit
        silently no-ops."""
        from superpower_workflow.phases import PhaseContext

        orch = _mk_orch(tmp_path)
        orch._telemetry = None
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={"name": "M1"},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        # Should not raise.
        orch._emit_run_cost_projection(
            ctx,
            phase_just_completed="plan",
            remaining_in_milestone=["implement"],
            completed_in_milestone=["plan"],
        )
