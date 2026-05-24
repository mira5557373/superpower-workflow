from __future__ import annotations

from superpower_workflow.dashboard.static import DASHBOARD_HTML


class TestDashboardHTML:
    def test_is_valid_html_string(self):
        assert isinstance(DASHBOARD_HTML, str)
        assert "<!DOCTYPE html>" in DASHBOARD_HTML
        assert "</html>" in DASHBOARD_HTML

    def test_contains_event_source(self):
        assert "EventSource" in DASHBOARD_HTML

    def test_contains_sse_endpoint(self):
        assert "/api/events" in DASHBOARD_HTML

    def test_contains_snapshot_endpoint(self):
        assert "/api/snapshot" in DASHBOARD_HTML

    def test_contains_progress_elements(self):
        assert "progress" in DASHBOARD_HTML.lower()
        assert "cost" in DASHBOARD_HTML.lower()
        assert "milestone" in DASHBOARD_HTML.lower()

    def test_contains_status_indicator(self):
        assert "status" in DASHBOARD_HTML.lower()

    def test_no_external_dependencies(self):
        assert "cdn" not in DASHBOARD_HTML.lower()
        assert "unpkg" not in DASHBOARD_HTML.lower()
        assert "jsdelivr" not in DASHBOARD_HTML.lower()
