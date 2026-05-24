from __future__ import annotations

import json
import time

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneStarted,
    PhaseCompleted,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
)


def _setup_project(tmp_path, milestones=None, state=None, telemetry_events=None):
    """Create a minimal project directory with config, state, and telemetry."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "schema_version": 1,
        "model": "opus",
        "milestones": milestones or [],
        "telemetry": {"enabled": True, "path": ".claude/telemetry.jsonl"},
    }
    (claude_dir / "workflow.json").write_text(json.dumps(config))

    if state:
        (claude_dir / "workflow-state.json").write_text(json.dumps(state))

    if telemetry_events:
        tpath = tmp_path / ".claude" / "telemetry.jsonl"
        emitter = TelemetryEmitter(tpath, run_id="run-1")
        for event in telemetry_events:
            emitter.emit(event)
        emitter.close()

    return tmp_path


class TestDashboardSnapshot:
    def test_default_snapshot_is_idle(self):
        snap = DashboardSnapshot()
        assert snap.status == "idle"
        assert snap.milestones_total == 0
        assert snap.milestones_completed == 0
        assert snap.total_cost_usd == 0.0

    def test_snapshot_to_dict_roundtrip(self):
        snap = DashboardSnapshot(
            run_id="run-1",
            status="running",
            milestones_total=5,
            milestones_completed=2,
            total_cost_usd=42.50,
            current_milestone="m3",
            current_phase="implement",
            completed=["m1", "m2"],
        )
        d = snap.to_dict()
        assert d["run_id"] == "run-1"
        assert d["status"] == "running"
        assert d["milestones_total"] == 5
        assert d["milestones_completed"] == 2
        assert d["total_cost_usd"] == 42.50
        assert d["current_milestone"] == "m3"
        assert d["completed"] == ["m1", "m2"]

    def test_snapshot_to_dict_is_json_serializable(self):
        snap = DashboardSnapshot(
            run_id="r1",
            cost_by_milestone={"m1": 5.0},
            quality_trend=[{"gaps": 3}],
        )
        raw = json.dumps(snap.to_dict())
        parsed = json.loads(raw)
        assert parsed["cost_by_milestone"] == {"m1": 5.0}
        assert parsed["quality_trend"] == [{"gaps": 3}]

    def test_snapshot_timestamp_auto_set(self):
        snap = DashboardSnapshot()
        assert snap.timestamp != ""
        assert "T" in snap.timestamp

    def test_snapshot_explicit_timestamp_preserved(self):
        snap = DashboardSnapshot(timestamp="2026-01-01T00:00:00Z")
        assert snap.timestamp == "2026-01-01T00:00:00Z"


class TestDashboardDataLoadSnapshot:
    def test_load_snapshot_idle_no_state(self, tmp_path):
        """No state file -> idle snapshot with zero values."""
        _setup_project(tmp_path, milestones=[{"name": "m1"}, {"name": "m2"}])
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"
        assert snap.milestones_total == 2
        assert snap.milestones_completed == 0
        assert snap.total_cost_usd == 0.0

    def test_load_snapshot_running(self, tmp_path):
        """Active state with current_step -> running status."""
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}],
            state={
                "current_milestone_index": 0,
                "current_step": "implement",
                "completed": [],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 10.0,
                "run_id": "run-1",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "running"
        assert snap.current_milestone == "m1"
        assert snap.current_phase == "implement"
        assert snap.total_cost_usd == 10.0

    def test_load_snapshot_completed(self, tmp_path):
        """All milestones completed -> completed status."""
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}],
            state={
                "current_milestone_index": 1,
                "current_step": None,
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 25.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "completed"
        assert snap.milestones_completed == 1
        assert snap.completed == ["m1"]

    def test_load_snapshot_with_failures(self, tmp_path):
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}],
            state={
                "current_milestone_index": 2,
                "current_step": None,
                "completed": ["m1"],
                "failed": ["m2"],
                "skipped": [],
                "total_cost_usd": 30.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "failed"
        assert snap.milestones_failed == 1

    def test_load_snapshot_with_telemetry_metrics(self, tmp_path):
        """Telemetry data populates cost/duration breakdowns."""
        events = [
            RunStarted(spec_sha="abc", model="opus", milestone_count=2, max_budget_usd=500),
            MilestoneStarted(milestone="m1", index=0),
            PhaseCompleted(milestone="m1", phase="plan", cost_usd=5.0, duration_ms=10000),
            MilestoneCompleted(milestone="m1", cost_usd=15.0, duration_seconds=60.0),
            RunCompleted(
                status="complete",
                completed_count=1,
                total_cost_usd=15.0,
                duration_seconds=60.0,
            ),
        ]
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}],
            state={
                "current_milestone_index": 1,
                "current_step": None,
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 15.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
            telemetry_events=events,
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.cost_by_milestone == {"m1": 15.0}
        assert "plan" in snap.cost_by_phase
        assert snap.duration_by_milestone == {"m1": 60.0}
        assert snap.total_duration_seconds == 60.0

    def test_load_snapshot_missing_config(self, tmp_path):
        """No workflow.json -> empty snapshot, no crash."""
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"
        assert snap.milestones_total == 0

    def test_load_snapshot_missing_telemetry(self, tmp_path):
        """No telemetry.jsonl -> snapshot from state only."""
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}],
            state={
                "current_milestone_index": 0,
                "current_step": "plan",
                "completed": [],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 0.0,
                "run_id": "run-1",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "running"
        assert snap.cost_by_milestone == {}

    def test_load_snapshot_malformed_state(self, tmp_path):
        """Corrupt state file -> graceful fallback to idle."""
        _setup_project(tmp_path, milestones=[{"name": "m1"}])
        (tmp_path / ".claude" / "workflow-state.json").write_text("{bad json")
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"

    def test_load_snapshot_model_from_config(self, tmp_path):
        _setup_project(tmp_path, milestones=[])
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.model == "opus"
