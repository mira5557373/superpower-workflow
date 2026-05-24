from __future__ import annotations

import http.client
import json
import time

from superpower_workflow.dashboard.data import DashboardData
from superpower_workflow.dashboard.server import DashboardServer
from superpower_workflow.dashboard.watch import render_frame
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneStarted,
    PhaseCompleted,
    RunStarted,
    TelemetryEmitter,
)


def _build_project(tmp_path, milestones=None, state=None, telemetry_events=None):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "model": "opus",
        "milestones": milestones or [{"name": "m1"}, {"name": "m2"}, {"name": "m3"}],
        "telemetry": {"enabled": True, "path": ".claude/telemetry.jsonl"},
        "dashboard": {"host": "localhost", "port": 0, "watch_interval": 2},
    }
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    if state:
        (claude_dir / "workflow-state.json").write_text(json.dumps(state))
    if telemetry_events:
        emitter = TelemetryEmitter(tmp_path / ".claude" / "telemetry.jsonl", "run-1")
        for ev in telemetry_events:
            emitter.emit(ev)
        emitter.close()
    return tmp_path


class TestDashboardIntegration:
    def test_live_update_detected_via_data_provider(self, tmp_path):
        """Write telemetry after initial load -> has_changed() is True."""
        _build_project(tmp_path)
        data = DashboardData(tmp_path)
        snap1 = data.load_snapshot()
        assert snap1.status == "idle"
        assert data.has_changed() is False

        state = {
            "current_milestone_index": 0,
            "current_step": "plan",
            "completed": [],
            "failed": [],
            "skipped": [],
            "total_cost_usd": 0.0,
            "run_id": "run-1",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (tmp_path / ".claude" / "workflow-state.json").write_text(json.dumps(state))
        assert data.has_changed() is True

        snap2 = data.load_snapshot()
        assert snap2.status == "running"
        assert snap2.current_milestone == "m1"

    def test_server_serves_correct_snapshot_json(self, tmp_path):
        """HTTP GET /api/snapshot returns snapshot matching state."""
        events = [
            RunStarted(spec_sha="abc", model="opus", milestone_count=3),
            MilestoneStarted(milestone="m1", index=0),
            PhaseCompleted(milestone="m1", phase="plan", cost_usd=5.0, duration_ms=5000),
            MilestoneCompleted(milestone="m1", cost_usd=10.0, duration_seconds=30.0),
        ]
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 1,
                "current_step": "implement",
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 10.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
            telemetry_events=events,
        )
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/api/snapshot")
            resp = conn.getresponse()
            body = json.loads(resp.read().decode())
            assert body["status"] == "running"
            assert body["milestones_completed"] == 1
            assert body["current_milestone"] == "m2"
            assert body["total_cost_usd"] == 10.0
            assert body["cost_by_milestone"]["m1"] == 10.0
            conn.close()
        finally:
            server.stop()

    def test_server_prometheus_reflects_state(self, tmp_path):
        """GET /metrics returns Prometheus text matching state."""
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 2,
                "current_step": None,
                "completed": ["m1", "m2"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 50.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/metrics")
            resp = conn.getresponse()
            text = resp.read().decode()
            assert "sw_milestones_completed 2" in text
            assert "sw_total_cost_usd 50.0" in text
            conn.close()
        finally:
            server.stop()

    def test_server_html_loads_successfully(self, tmp_path):
        """GET / returns HTML dashboard page."""
        _build_project(tmp_path)
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            assert "<!DOCTYPE html>" in body
            assert "EventSource" in body
            conn.close()
        finally:
            server.stop()

    def test_sse_endpoint_sends_initial_event(self, tmp_path):
        """GET /api/events returns event-stream with initial snapshot."""
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 0,
                "current_step": "plan",
                "completed": [],
                "failed": [],
                "skipped": [],
                "run_id": "run-1",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/api/events")
            resp = conn.getresponse()
            assert resp.status == 200
            assert "text/event-stream" in resp.getheader("Content-Type", "")
            line = resp.readline()
            assert b"data: " in line
            payload = line.decode().split("data: ", 1)[1].strip()
            parsed = json.loads(payload)
            assert parsed["status"] == "running"
            conn.close()
        finally:
            server.stop()

    def test_terminal_watch_renders_live_state(self, tmp_path):
        """TerminalWatch renders frame matching current state."""
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 1,
                "current_step": "implement",
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 15.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        frame = render_frame(snap)
        assert "m1" in frame
        assert "$15.00" in frame
        assert "implement" in frame

    def test_full_pipeline_idle_to_running_to_complete(self, tmp_path):
        """Simulate full lifecycle: idle -> running -> completed."""
        _build_project(tmp_path)
        data = DashboardData(tmp_path)

        # Phase 1: idle
        snap = data.load_snapshot()
        assert snap.status == "idle"

        # Phase 2: running
        state = {
            "current_milestone_index": 0,
            "current_step": "implement",
            "completed": [],
            "failed": [],
            "skipped": [],
            "total_cost_usd": 5.0,
            "run_id": "run-1",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (tmp_path / ".claude" / "workflow-state.json").write_text(json.dumps(state))
        assert data.has_changed() is True
        snap = data.load_snapshot()
        assert snap.status == "running"
        assert snap.current_milestone == "m1"

        # Phase 3: completed
        state["current_milestone_index"] = 3
        state["current_step"] = None
        state["completed"] = ["m1", "m2", "m3"]
        state["total_cost_usd"] = 45.0
        (tmp_path / ".claude" / "workflow-state.json").write_text(json.dumps(state))
        assert data.has_changed() is True
        snap = data.load_snapshot()
        assert snap.status == "completed"
        assert snap.milestones_completed == 3
        assert snap.total_cost_usd == 45.0

    def test_backward_compatible_no_dashboard_config(self, tmp_path):
        """Missing dashboard section in config -> defaults work."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        config = {"schema_version": 1, "milestones": [], "model": "opus"}
        (claude_dir / "workflow.json").write_text(json.dumps(config))
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"
        assert snap.model == "opus"
