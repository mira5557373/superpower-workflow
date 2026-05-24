from __future__ import annotations

import json
import threading
import time
from io import StringIO

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.dashboard.watch import TerminalWatch, render_frame


def _setup_watch_project(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "workflow.json").write_text(
        json.dumps({"schema_version": 1, "model": "opus", "milestones": [{"name": "m1"}]})
    )
    return DashboardData(tmp_path)


class TestRenderFrame:
    def test_contains_status(self):
        snap = DashboardSnapshot(status="running")
        frame = render_frame(snap)
        assert "running" in frame.lower()

    def test_contains_progress(self):
        snap = DashboardSnapshot(milestones_completed=3, milestones_total=5)
        frame = render_frame(snap)
        assert "3/5" in frame

    def test_contains_cost(self):
        snap = DashboardSnapshot(total_cost_usd=42.50)
        frame = render_frame(snap)
        assert "$42.50" in frame

    def test_contains_completed_milestones(self):
        snap = DashboardSnapshot(
            completed=["m1", "m2"],
            milestone_names=["m1", "m2", "m3"],
        )
        frame = render_frame(snap)
        assert "m1" in frame
        assert "m2" in frame

    def test_contains_current_milestone(self):
        snap = DashboardSnapshot(
            current_milestone="m3",
            current_phase="implement",
            milestone_names=["m1", "m2", "m3"],
        )
        frame = render_frame(snap)
        assert "m3" in frame
        assert "implement" in frame

    def test_contains_failed_milestones(self):
        snap = DashboardSnapshot(failed=["m2"], milestone_names=["m1", "m2"])
        frame = render_frame(snap)
        assert "m2" in frame

    def test_contains_elapsed_time(self):
        snap = DashboardSnapshot(elapsed_seconds=150.0)
        frame = render_frame(snap)
        assert "2m" in frame

    def test_contains_quality_metrics(self):
        snap = DashboardSnapshot(rework_rate=0.15, defect_density=0.05)
        frame = render_frame(snap)
        assert "15.0%" in frame
        assert "5.0%" in frame

    def test_empty_snapshot_no_crash(self):
        snap = DashboardSnapshot()
        frame = render_frame(snap)
        assert "idle" in frame.lower()

    def test_progress_bar_present(self):
        snap = DashboardSnapshot(milestones_completed=2, milestones_total=4)
        frame = render_frame(snap)
        assert any(c in frame for c in ("█", "━", "=", "#"))

    def test_cost_by_milestone_shown(self):
        snap = DashboardSnapshot(
            completed=["m1"],
            cost_by_milestone={"m1": 8.50},
            milestone_names=["m1", "m2"],
        )
        frame = render_frame(snap)
        assert "$8.50" in frame

    def test_pending_milestones_shown(self):
        snap = DashboardSnapshot(
            completed=["m1"],
            current_milestone="m2",
            milestone_names=["m1", "m2", "m3", "m4"],
        )
        frame = render_frame(snap)
        assert "m3" in frame
        assert "m4" in frame


class TestTerminalWatch:
    def test_renders_initial_frame(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)

        def stop_soon():
            time.sleep(0.5)
            watch.stop()

        t = threading.Thread(target=stop_soon, daemon=True)
        t.start()
        watch.start()
        t.join(timeout=3)
        assert "sw watch" in output.getvalue()

    def test_stop_event_exits_loop(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)
        watch.stop()
        watch.start()  # Should exit immediately since stop is already set

    def test_detects_changes_and_rerenders(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)

        def update_and_stop():
            time.sleep(0.4)
            state_path = tmp_path / ".claude" / "workflow-state.json"
            state_path.write_text(
                json.dumps(
                    {"current_step": "implement", "completed": [], "failed": [], "skipped": []}
                )
            )
            time.sleep(0.5)
            watch.stop()

        t = threading.Thread(target=update_and_stop, daemon=True)
        t.start()
        watch.start()
        t.join(timeout=5)
        content = output.getvalue()
        assert content.count("sw watch") >= 2

    def test_custom_interval(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)

        def stop_soon():
            time.sleep(0.6)
            watch.stop()

        t = threading.Thread(target=stop_soon, daemon=True)
        t.start()
        watch.start()
        t.join(timeout=3)
        frames = output.getvalue().count("sw watch")
        assert frames >= 3
