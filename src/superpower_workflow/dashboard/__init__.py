"""Dashboard: web UI, terminal watch, and Prometheus metrics for sw."""

from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.dashboard.server import (
    DashboardServer,
    format_sse_event,
    format_sse_keepalive,
    render_prometheus,
)
from superpower_workflow.dashboard.watch import TerminalWatch, render_frame

__all__ = [
    "DashboardData",
    "DashboardServer",
    "DashboardSnapshot",
    "TerminalWatch",
    "format_sse_event",
    "format_sse_keepalive",
    "render_frame",
    "render_prometheus",
]
