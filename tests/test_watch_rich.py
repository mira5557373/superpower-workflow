"""Tests for the rich-based sw watch TUI (v1.3.17 / v1.1.9.1 Task 209).

Pins the auto-detect + fallback contract:

- `make_watch()` returns RichWatch when rich is importable
- Returns TerminalWatch when rich missing OR when SW_WATCH_NO_RICH=1
- _rich_available() correctly reflects both conditions
- _render_rich_layout produces a renderable for any snapshot shape
  (cold-start, in-flight, completed, budget-alerted)

Transport-layer behavior (rich.Live actually updating a TTY) is
covered by manual testing — the unit tests verify the renderable
shape and the dispatch contract.
"""

from __future__ import annotations

import sys

from superpower_workflow.dashboard.data import DashboardSnapshot
from superpower_workflow.dashboard.watch import (
    RichWatch,
    TerminalWatch,
    _render_rich_layout,
    _rich_available,
    make_watch,
)

# ---- auto-detect ----


class TestRichAvailability:
    def test_returns_true_when_rich_importable(self, monkeypatch):
        monkeypatch.delenv("SW_WATCH_NO_RICH", raising=False)
        # rich is installed in dev deps, so this should be True.
        assert _rich_available() is True

    def test_returns_false_when_env_var_set(self, monkeypatch):
        monkeypatch.setenv("SW_WATCH_NO_RICH", "1")
        assert _rich_available() is False

    def test_returns_false_when_rich_missing(self, monkeypatch):
        """Simulate rich-not-installed by hiding the module."""
        monkeypatch.delenv("SW_WATCH_NO_RICH", raising=False)
        original = sys.modules.get("rich")
        sys.modules["rich"] = None
        try:
            assert _rich_available() is False
        finally:
            if original is not None:
                sys.modules["rich"] = original
            else:
                sys.modules.pop("rich", None)


# ---- make_watch dispatch ----


class _StubDashboardData:
    """Stub for DashboardData — load_snapshot returns a fixed snapshot."""

    def __init__(self, snapshot: DashboardSnapshot):
        self._snapshot = snapshot

    def load_snapshot(self) -> DashboardSnapshot:
        return self._snapshot


def _stub_data(**overrides) -> _StubDashboardData:
    base = dict(
        status="running",
        run_id="01TESTRICH",
        milestones_total=3,
        milestones_completed=1,
        milestone_names=["M1", "M2", "M3"],
        completed=["M1"],
        current_milestone="M2",
        current_phase="implement",
        total_cost_usd=5.20,
        cost_by_milestone={"M1": 5.20},
        max_budget_usd=50.0,
        projected_total_usd=18.40,
        projection_low_p10_usd=14.0,
        projection_high_p90_usd=22.0,
        projection_confidence=0.6,
        projection_source="partial_history",
    )
    base.update(overrides)
    snap = DashboardSnapshot(**base)
    return _StubDashboardData(snap)


class TestMakeWatch:
    def test_returns_rich_watch_when_available(self, monkeypatch):
        monkeypatch.delenv("SW_WATCH_NO_RICH", raising=False)
        watch = make_watch(_stub_data())
        assert isinstance(watch, RichWatch)

    def test_falls_back_to_terminal_when_no_rich_env_set(self, monkeypatch):
        monkeypatch.setenv("SW_WATCH_NO_RICH", "1")
        watch = make_watch(_stub_data())
        assert isinstance(watch, TerminalWatch)

    def test_prefer_rich_false_uses_terminal(self, monkeypatch):
        monkeypatch.delenv("SW_WATCH_NO_RICH", raising=False)
        watch = make_watch(_stub_data(), prefer_rich=False)
        assert isinstance(watch, TerminalWatch)


# ---- _render_rich_layout shape ----


class TestRichLayout:
    def test_renders_running_snapshot_without_error(self):
        layout = _render_rich_layout(_stub_data()._snapshot)
        # Layout is a rich.panel.Panel.
        from rich.panel import Panel

        assert isinstance(layout, Panel)

    def test_renders_with_budget_alert(self):
        data = _stub_data(last_budget_alert_threshold=75)
        layout = _render_rich_layout(data._snapshot)
        # Render to string and assert key fields appear.
        from rich.console import Console

        console = Console(record=True, width=80, file=None)
        with console.capture() as cap:
            console.print(layout)
        output = cap.get()
        assert "Budget alert: 75%" in output

    def test_renders_cold_start_without_projection(self):
        """When projection_total is 0, projection lines are omitted."""
        data = _stub_data(
            projected_total_usd=0.0,
            projection_low_p10_usd=0.0,
            projection_high_p90_usd=0.0,
            projection_source="",
        )
        layout = _render_rich_layout(data._snapshot)
        from rich.console import Console

        console = Console(record=True, width=80, file=None)
        with console.capture() as cap:
            console.print(layout)
        output = cap.get()
        # No "Projected:" line when total is 0.
        assert "Projected" not in output

    def test_renders_completed_snapshot(self):
        data = _stub_data(
            status="completed",
            milestones_completed=3,
            completed=["M1", "M2", "M3"],
            current_milestone="",
            current_phase="",
        )
        layout = _render_rich_layout(data._snapshot)
        from rich.console import Console

        console = Console(record=True, width=80, file=None)
        with console.capture() as cap:
            console.print(layout)
        output = cap.get()
        assert "completed" in output.lower()
        # All three milestones show as done with ✓.
        assert "M1" in output
        assert "M3" in output

    def test_renders_with_failed_milestone(self):
        data = _stub_data(
            status="failed",
            milestones_completed=1,
            milestones_failed=1,
            failed=["M2"],
            current_milestone="",
            current_phase="",
        )
        layout = _render_rich_layout(data._snapshot)
        from rich.console import Console

        console = Console(record=True, width=80, file=None)
        with console.capture() as cap:
            console.print(layout)
        output = cap.get()
        assert "failed" in output.lower()

    def test_projection_confidence_pips_render(self):
        """Confidence is displayed as 5 pips (●●●○○ pattern)."""
        # 0.6 confidence → 3 full pips + 2 hollow.
        data = _stub_data(projection_confidence=0.6)
        layout = _render_rich_layout(data._snapshot)
        from rich.console import Console

        console = Console(record=True, width=80, file=None)
        with console.capture() as cap:
            console.print(layout)
        output = cap.get()
        # ●●●○○ — three filled, two hollow.
        assert "●●●○○" in output


# ---- DashboardSnapshot extensions ----


class TestSnapshotProjectionFields:
    def test_defaults_zero(self):
        snap = DashboardSnapshot()
        assert snap.projected_total_usd == 0.0
        assert snap.projection_confidence == 0.0
        assert snap.projection_source == ""
        assert snap.last_budget_alert_threshold == 0
        assert snap.max_budget_usd == 0.0

    def test_to_dict_includes_new_fields(self):
        snap = DashboardSnapshot(
            projected_total_usd=10.0,
            projection_source="partial_history",
            last_budget_alert_threshold=50,
            max_budget_usd=100.0,
        )
        d = snap.to_dict()
        assert d["projected_total_usd"] == 10.0
        assert d["projection_source"] == "partial_history"
        assert d["last_budget_alert_threshold"] == 50
        assert d["max_budget_usd"] == 100.0


# ---- stop semantics ----


class TestRichWatchStop:
    def test_stop_sets_event(self, monkeypatch):
        monkeypatch.delenv("SW_WATCH_NO_RICH", raising=False)
        w = RichWatch(_stub_data(), interval=10.0)
        assert not w._stop_event.is_set()
        w.stop()
        assert w._stop_event.is_set()
