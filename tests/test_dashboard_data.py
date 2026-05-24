from __future__ import annotations

import json

from superpower_workflow.dashboard.data import DashboardSnapshot


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
