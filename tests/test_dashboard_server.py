from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardSnapshot
from superpower_workflow.dashboard.server import render_prometheus


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
