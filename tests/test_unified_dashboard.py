from __future__ import annotations


class TestUnifiedDashboardHtml:
    def test_html_is_string(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert isinstance(UNIFIED_DASHBOARD_HTML, str)

    def test_contains_doctype(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "<!DOCTYPE html>" in UNIFIED_DASHBOARD_HTML

    def test_contains_hash_routing(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "hashchange" in UNIFIED_DASHBOARD_HTML or "location.hash" in UNIFIED_DASHBOARD_HTML

    def test_contains_api_fetch(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "/api/v1/" in UNIFIED_DASHBOARD_HTML

    def test_contains_websocket(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "WebSocket" in UNIFIED_DASHBOARD_HTML or "ws://" in UNIFIED_DASHBOARD_HTML

    def test_dark_theme(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "dark" in UNIFIED_DASHBOARD_HTML.lower() or "#1a1a2e" in UNIFIED_DASHBOARD_HTML

    def test_monospace_font(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "monospace" in UNIFIED_DASHBOARD_HTML

    def test_navigation_links(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "#/" in UNIFIED_DASHBOARD_HTML
        assert "#/search" in UNIFIED_DASHBOARD_HTML or "#/analytics" in UNIFIED_DASHBOARD_HTML

    def test_project_cards_section(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "project" in UNIFIED_DASHBOARD_HTML.lower()

    def test_svg_chart_support(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        assert "<svg" in UNIFIED_DASHBOARD_HTML or "svg" in UNIFIED_DASHBOARD_HTML.lower()
