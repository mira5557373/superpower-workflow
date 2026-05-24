from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.dashboard.server import (
    format_sse_event,
    format_sse_keepalive,
    make_handler,
    render_prometheus,
)


class TestRenderPrometheus:
    def test_contains_help_and_type_lines(self):
        snap = DashboardSnapshot(milestones_total=5, milestones_completed=3)
        text = render_prometheus(snap)
        assert "# HELP sw_milestones_total" in text
        assert "# TYPE sw_milestones_total gauge" in text
        assert "sw_milestones_total 5" in text

    def test_cost_metric(self):
        snap = DashboardSnapshot(total_cost_usd=42.5)
        text = render_prometheus(snap)
        assert "sw_total_cost_usd 42.5" in text

    def test_milestone_cost_labels(self):
        snap = DashboardSnapshot(cost_by_milestone={"m1": 10.0, "m2": 20.0})
        text = render_prometheus(snap)
        assert 'sw_milestone_cost_usd{milestone="m1"} 10.0' in text
        assert 'sw_milestone_cost_usd{milestone="m2"} 20.0' in text

    def test_quality_metrics(self):
        snap = DashboardSnapshot(rework_rate=0.15, defect_density=0.05)
        text = render_prometheus(snap)
        assert "sw_rework_rate 0.15" in text
        assert "sw_defect_density 0.05" in text

    def test_progress_metrics(self):
        snap = DashboardSnapshot(milestones_completed=2, milestones_failed=1, milestones_skipped=1)
        text = render_prometheus(snap)
        assert "sw_milestones_completed 2" in text
        assert "sw_milestones_failed 1" in text
        assert "sw_milestones_skipped 1" in text

    def test_elapsed_and_duration(self):
        snap = DashboardSnapshot(elapsed_seconds=300.0, total_duration_seconds=250.0)
        text = render_prometheus(snap)
        assert "sw_elapsed_seconds 300.0" in text
        assert "sw_total_duration_seconds 250.0" in text

    def test_empty_snapshot(self):
        snap = DashboardSnapshot()
        text = render_prometheus(snap)
        assert "sw_milestones_total 0" in text
        assert "sw_total_cost_usd 0.0" in text

    def test_ends_with_newline(self):
        snap = DashboardSnapshot()
        text = render_prometheus(snap)
        assert text.endswith("\n")


class TestFormatSSE:
    def test_sse_event_has_data_prefix(self):
        snap = DashboardSnapshot(run_id="r1", status="running")
        raw = format_sse_event(snap)
        assert raw.startswith("data: ")

    def test_sse_event_ends_with_double_newline(self):
        snap = DashboardSnapshot()
        raw = format_sse_event(snap)
        assert raw.endswith("\n\n")

    def test_sse_event_payload_is_valid_json(self):
        snap = DashboardSnapshot(
            run_id="r1",
            milestones_total=5,
            total_cost_usd=42.5,
        )
        raw = format_sse_event(snap)
        payload = raw.removeprefix("data: ").strip()
        parsed = json.loads(payload)
        assert parsed["run_id"] == "r1"
        assert parsed["milestones_total"] == 5
        assert parsed["total_cost_usd"] == 42.5

    def test_sse_keepalive_format(self):
        raw = format_sse_keepalive()
        assert raw == ": keepalive\n\n"

    def test_sse_event_single_line_data(self):
        snap = DashboardSnapshot()
        raw = format_sse_event(snap)
        lines = raw.strip().split("\n")
        assert len(lines) == 1
        assert lines[0].startswith("data: ")


def _make_test_server(tmp_path):
    """Create a test server on a random port."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "workflow.json").write_text(
        json.dumps({"schema_version": 1, "model": "opus", "milestones": []})
    )
    data = DashboardData(tmp_path)
    handler_cls = make_handler(data)
    server = ThreadingHTTPServer(("localhost", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class TestDashboardHandler:
    def test_root_returns_html(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            assert "text/html" in resp.getheader("Content-Type", "")
            assert "<!DOCTYPE html>" in body
            conn.close()
        finally:
            server.shutdown()

    def test_api_snapshot_returns_json(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/api/snapshot")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            assert "application/json" in resp.getheader("Content-Type", "")
            parsed = json.loads(body)
            assert "status" in parsed
            assert "milestones_total" in parsed
            conn.close()
        finally:
            server.shutdown()

    def test_metrics_returns_prometheus_text(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/metrics")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            content_type = resp.getheader("Content-Type", "")
            assert "text/plain" in content_type
            assert "sw_milestones_total" in body
            conn.close()
        finally:
            server.shutdown()

    def test_api_events_returns_event_stream(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/api/events")
            resp = conn.getresponse()
            assert resp.status == 200
            assert "text/event-stream" in resp.getheader("Content-Type", "")
            line = resp.readline()
            assert b"data: " in line
            conn.close()
        finally:
            server.shutdown()

    def test_unknown_path_returns_404(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/nonexistent")
            resp = conn.getresponse()
            assert resp.status == 404
            conn.close()
        finally:
            server.shutdown()
