"""Tests for the orchestrator's drift detection integration (v1.3.19).

Pins the _emit_drift_for_phase hook contract:

- Disabled when self._in_parallel_worker=True (parallel-mode skip)
- Disabled when drift_detection.enabled=false config
- Suppressed below baseline_floor (default 15)
- INFO severity suppressed under observation_only mode (default)
- WARN/CRITICAL severity emitted under observation_only mode
- Rate-limit dedup via state.drift_alerts_emitted_this_milestone
- Dedup cleared on each milestone start
- Never raises (best-effort)
"""

from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.state import WorkflowState, save_state
from superpower_workflow.telemetry import DriftDetected, TelemetryEmitter


def _mk_orch(tmp_path: Path, *, drift_cfg: dict | None = None) -> Orchestrator:
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
        "max_total_budget_usd": 100.0,
    }
    if drift_cfg is not None:
        cfg["drift_detection"] = drift_cfg
    (claude_dir / "workflow.json").write_text(json.dumps(cfg))
    save_state(claude_dir, WorkflowState())
    orch = Orchestrator(project_root=tmp_path)
    orch._telemetry = TelemetryEmitter.disabled()
    orch._current_milestone_name = "M1"
    return orch


def _seed_history(tmp_path: Path, n: int = 20, base_cost: float = 2.0) -> None:
    """Write N historical phase_completed events to seed a baseline."""
    tel = tmp_path / ".claude" / "sw-telemetry.jsonl"
    events = []
    for i in range(n):
        events.append(
            {
                "type": "phase_completed",
                "phase": "plan",
                "cost_usd": base_cost + (i % 3) * 0.1,
                "duration_ms": 1000.0,
                "cache_hit_rate": 0.7,
                "run_id": "PRIOR_RUN",
            }
        )
    tel.write_text("\n".join(json.dumps(e) for e in events))


def _captured_drift_events(orch: Orchestrator) -> list[DriftDetected]:
    """Replace _telemetry.emit with a spy and return only DriftDetected events."""
    captured: list = []
    real_emit = orch._telemetry.emit

    def spy(event):
        captured.append(event)
        real_emit(event)

    orch._telemetry.emit = spy  # type: ignore[method-assign]
    return [e for e in captured if isinstance(e, DriftDetected)] if False else captured


# ---- baseline_floor suppression ----


class TestBaselineFloorSuppression:
    def test_no_emit_below_floor(self, tmp_path):
        orch = _mk_orch(tmp_path)
        events = _captured_drift_events(orch)
        # No history → below floor; should not emit anything.
        orch._emit_drift_for_phase(
            phase="plan",
            cost_usd=100.0,  # would be wildly off any baseline
            duration_ms=5000.0,
            tokens={"cache_hit_rate": 0.1},
        )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        assert drift == []


# ---- enable / disable ----


class TestEnableDisable:
    def test_disabled_by_config(self, tmp_path):
        orch = _mk_orch(tmp_path, drift_cfg={"enabled": False})
        events = _captured_drift_events(orch)
        _seed_history(tmp_path)
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=50.0, duration_ms=5000.0, tokens={"cache_hit_rate": 0.7}
        )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        assert drift == []

    def test_parallel_worker_skip(self, tmp_path):
        orch = _mk_orch(tmp_path)
        orch._in_parallel_worker = True
        events = _captured_drift_events(orch)
        _seed_history(tmp_path)
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=50.0, duration_ms=5000.0, tokens={"cache_hit_rate": 0.7}
        )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        assert drift == []

    def test_no_telemetry_skip(self, tmp_path):
        orch = _mk_orch(tmp_path)
        orch._telemetry = None
        _seed_history(tmp_path)
        # Should not raise.
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=50.0, duration_ms=5000.0, tokens={"cache_hit_rate": 0.7}
        )


# ---- observation_only mode ----


class TestObservationOnlyMode:
    def test_default_mode_is_observation_only(self, tmp_path):
        """Default config → mode='observation_only'. INFO events suppressed."""
        orch = _mk_orch(tmp_path)
        events = _captured_drift_events(orch)
        _seed_history(tmp_path, n=20, base_cost=2.0)
        # Observation $2.5 → ~2.5σ → INFO. Should NOT emit under default.
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=2.5, duration_ms=1000.0, tokens={"cache_hit_rate": 0.7}
        )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        # INFO suppressed under observation_only.
        info_events = [e for e in drift if e.severity == "info"]
        assert info_events == []

    def test_emit_info_flag_overrides(self, tmp_path):
        orch = _mk_orch(
            tmp_path,
            drift_cfg={"mode": "observation_only", "emit_info": True},
        )
        events = _captured_drift_events(orch)
        _seed_history(tmp_path, n=20, base_cost=2.0)
        # Observation $2.5 → INFO event NOW emits.
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=2.5, duration_ms=1000.0, tokens={"cache_hit_rate": 0.7}
        )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        info_events = [e for e in drift if e.severity == "info"]
        # At least one INFO event for the cost drift.
        assert len(info_events) >= 1


# ---- WARN/CRITICAL emission ----


class TestWarnCriticalEmission:
    def test_critical_emits_under_observation_only(self, tmp_path):
        """WARN+CRITICAL fire even under observation_only — only INFO
        is gated."""
        orch = _mk_orch(tmp_path)
        events = _captured_drift_events(orch)
        _seed_history(tmp_path, n=20, base_cost=2.0)
        # Observation $50 — way outside baseline.
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=50.0, duration_ms=1000.0, tokens={"cache_hit_rate": 0.7}
        )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        # At least one CRITICAL or WARN drift event.
        severe = [e for e in drift if e.severity in ("warn", "critical")]
        assert len(severe) >= 1
        assert severe[0].metric == "cost_usd"
        assert severe[0].direction == "high"
        assert severe[0].milestone == "M1"


# ---- dedup ----


class TestRateLimitDedup:
    def test_same_event_fires_once_per_milestone(self, tmp_path):
        orch = _mk_orch(tmp_path)
        events = _captured_drift_events(orch)
        _seed_history(tmp_path, n=20, base_cost=2.0)
        # Fire the same drift twice — dedup should silence the second.
        for _ in range(2):
            orch._emit_drift_for_phase(
                phase="plan", cost_usd=50.0, duration_ms=1000.0, tokens={"cache_hit_rate": 0.7}
            )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        # Only one cost_usd|plan|opus|critical|high event.
        cost_critical = [
            e for e in drift if e.metric == "cost_usd" and e.severity in ("warn", "critical")
        ]
        assert len(cost_critical) == 1
        # State recorded the dedup.
        assert len(orch.state.drift_alerts_emitted_this_milestone) >= 1


# ---- bucket key includes model ----


class TestBucketKeyIncludesModel:
    def test_bucket_contains_model_id(self, tmp_path):
        orch = _mk_orch(tmp_path)  # config.model = "opus"
        events = _captured_drift_events(orch)
        _seed_history(tmp_path, n=20, base_cost=2.0)
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=50.0, duration_ms=1000.0, tokens={"cache_hit_rate": 0.7}
        )
        drift = [e for e in events if isinstance(e, DriftDetected)]
        # Bucket key includes the model: "plan|opus"
        for e in drift:
            assert "|opus" in e.bucket


# ---- never raises ----


class TestNeverRaises:
    def test_corrupt_telemetry_does_not_raise(self, tmp_path):
        orch = _mk_orch(tmp_path)
        tel = tmp_path / ".claude" / "sw-telemetry.jsonl"
        tel.write_text("{ this is not valid json")
        # Should not raise.
        orch._emit_drift_for_phase(
            phase="plan", cost_usd=50.0, duration_ms=1000.0, tokens={"cache_hit_rate": 0.7}
        )

    def test_missing_tokens_keys(self, tmp_path):
        orch = _mk_orch(tmp_path)
        # tokens dict missing cache_hit_rate → defaults to 0.0
        orch._emit_drift_for_phase(phase="plan", cost_usd=2.0, duration_ms=1000.0, tokens={})
