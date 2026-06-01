from __future__ import annotations

import os
import sys
import threading
from typing import IO

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot

_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_BAR_WIDTH = 40


def _format_time(seconds: float) -> str:
    if seconds <= 0:
        return "-"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def _progress_bar(completed: int, total: int) -> str:
    if total == 0:
        return f"{_DIM}{'━' * _BAR_WIDTH}{_RESET}"
    pct = completed / total
    filled = int(_BAR_WIDTH * pct)
    empty = _BAR_WIDTH - filled
    return f"{_GREEN}{'█' * filled}{_DIM}{'━' * empty}{_RESET}"


def render_frame(snapshot: DashboardSnapshot) -> str:
    s = snapshot
    lines: list[str] = []

    lines.append(f"{_BOLD}  sw watch{_RESET}  Status: {s.status}")
    lines.append("")

    bar = _progress_bar(s.milestones_completed, s.milestones_total)
    lines.append(f"  {bar} {s.milestones_completed}/{s.milestones_total}")
    lines.append("")

    cost_str = f"${s.total_cost_usd:.2f}"
    elapsed_str = _format_time(s.elapsed_seconds)
    lines.append(f"  Cost: {cost_str}  |  Elapsed: {elapsed_str}")
    lines.append("")

    done = set(s.completed)
    fail = set(s.failed)
    skip = set(s.skipped)
    for name in s.milestone_names:
        cost = s.cost_by_milestone.get(name)
        cost_part = f"  ${cost:.2f}" if cost is not None else ""
        if name in done:
            lines.append(f"  {_GREEN}+{_RESET} {name}{cost_part}")
        elif name == s.current_milestone:
            lines.append(f"  {_YELLOW}>{_RESET} {name}  {_DIM}{s.current_phase}{_RESET}")
        elif name in fail:
            lines.append(f"  {_RED}x{_RESET} {name}")
        elif name in skip:
            lines.append(f"  {_DIM}- {name}{_RESET}")
        else:
            lines.append(f"  {_DIM}. {name}{_RESET}")

    lines.append("")
    rr = f"{s.rework_rate * 100:.1f}%"
    dd = f"{s.defect_density * 100:.1f}%"
    lines.append(f"  Rework: {rr}  |  Defects: {dd}")
    lines.append("")

    return "\n".join(lines)


_CLEAR_SCREEN = "\033[2J\033[H"


class TerminalWatch:
    """Legacy ANSI text-mode watch. Used when rich is unavailable or
    when SW_WATCH_NO_RICH=1 is set."""

    def __init__(
        self,
        data: DashboardData,
        interval: float = 2.0,
        output: IO[str] | None = None,
    ) -> None:
        self._data = data
        self._interval = interval
        self._output = output or sys.stdout
        self._stop_event = threading.Event()

    def start(self) -> None:
        try:
            while not self._stop_event.is_set():
                snapshot = self._data.load_snapshot()
                frame = render_frame(snapshot)
                self._output.write(_CLEAR_SCREEN + frame)
                self._output.flush()
                self._stop_event.wait(timeout=self._interval)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        self._stop_event.set()


# ---- rich-based watch (v1.3.17 / v1.1.9.1 Task 209) ----


def _rich_available() -> bool:
    """Return True iff the `rich` SDK is importable.

    Respects SW_WATCH_NO_RICH=1 for forcing text-mode fallback (useful
    in CI / non-TTY environments where rich's live display misbehaves).
    """
    if os.environ.get("SW_WATCH_NO_RICH") == "1":
        return False
    try:
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def _render_rich_layout(snapshot: DashboardSnapshot):
    """Build a rich.console renderable for one snapshot frame.

    Layout:
      ┌─ sw watch ────────────────────────────┐
      │ Status: running   Run: <run_id>      │
      ├───────────────────────────────────────┤
      │ Milestones [████████░░░░] 3/5         │
      │ M1 ✓ $1.50  M2 ✓ $2.00  M3 ▶ plan     │
      │ M4 .        M5 .                      │
      ├───────────────────────────────────────┤
      │ Cost: $5.20  Budget: $50.00 (10%)     │
      │ Projection: $18.40 [p10 $14, p90 $22] │
      │ Confidence: ●●●○○ (partial_history)   │
      ├───────────────────────────────────────┤
      │ Alerts: none  |  Rework: 2.5%         │
      └───────────────────────────────────────┘
    """
    from rich.console import Group
    from rich.panel import Panel
    from rich.progress_bar import ProgressBar
    from rich.table import Table
    from rich.text import Text

    s = snapshot

    # ── Header ───────────────────────────────────────────────────────
    status_color = {
        "running": "yellow",
        "completed": "green",
        "failed": "red",
        "idle": "dim",
    }.get(s.status, "white")
    header = Text()
    header.append("sw watch", style="bold cyan")
    header.append("   Status: ", style="dim")
    header.append(s.status, style=status_color)
    if s.run_id:
        header.append(f"   Run: {s.run_id[:12]}", style="dim")

    # ── Milestone progress ───────────────────────────────────────────
    progress_pct = s.milestones_completed / s.milestones_total if s.milestones_total > 0 else 0.0
    progress = ProgressBar(
        total=max(s.milestones_total, 1),
        completed=s.milestones_completed,
        width=40,
    )
    progress_label = Text()
    progress_label.append(f"  {s.milestones_completed}/{s.milestones_total} ")
    progress_label.append(f"({progress_pct * 100:.0f}%)", style="dim")

    # Per-milestone status table.
    ms_table = Table.grid(padding=(0, 2))
    done = set(s.completed)
    fail = set(s.failed)
    skip = set(s.skipped)
    row: list[Text] = []
    for name in s.milestone_names:
        cell = Text()
        cost = s.cost_by_milestone.get(name)
        cost_suffix = f" ${cost:.2f}" if cost else ""
        if name in done:
            cell.append("✓ ", style="green")
            cell.append(name)
            cell.append(cost_suffix, style="dim")
        elif name == s.current_milestone:
            cell.append("▶ ", style="yellow bold")
            cell.append(name, style="yellow")
            if s.current_phase:
                cell.append(f" ({s.current_phase})", style="dim")
        elif name in fail:
            cell.append("✗ ", style="red")
            cell.append(name, style="red")
        elif name in skip:
            cell.append("- ", style="dim")
            cell.append(name, style="dim")
        else:
            cell.append(". ", style="dim")
            cell.append(name, style="dim")
        row.append(cell)
        if len(row) == 3:  # 3 per line
            ms_table.add_row(*row)
            row = []
    if row:
        ms_table.add_row(*row)

    # ── Cost + budget gauge ──────────────────────────────────────────
    cost_lines: list[Text] = []
    cost_line = Text()
    cost_line.append(f"  Cost: ${s.total_cost_usd:.2f}", style="bold")
    if s.max_budget_usd > 0:
        pct = (s.total_cost_usd / s.max_budget_usd) * 100
        cap_color = (
            "red" if pct >= 90 else "yellow" if pct >= 75 else "green" if pct >= 50 else "dim"
        )
        cost_line.append(f"   Budget: ${s.max_budget_usd:.2f} ")
        cost_line.append(f"({pct:.1f}%)", style=cap_color)
    cost_lines.append(cost_line)

    # ── Projection band ──────────────────────────────────────────────
    if s.projected_total_usd > 0:
        proj_line = Text()
        proj_line.append(f"  Projected: ${s.projected_total_usd:.2f}", style="bold magenta")
        proj_line.append(
            f"   [p10 ${s.projection_low_p10_usd:.2f}, p90 ${s.projection_high_p90_usd:.2f}]",
            style="dim",
        )
        cost_lines.append(proj_line)

        # Confidence indicator.
        conf_line = Text()
        conf = s.projection_confidence
        full_pips = int(conf * 5)
        pips = "●" * full_pips + "○" * (5 - full_pips)
        conf_line.append(f"  Confidence: {pips} ", style="cyan")
        conf_line.append(
            f"({s.projection_source})" if s.projection_source else "",
            style="dim",
        )
        cost_lines.append(conf_line)

    # ── Alerts ───────────────────────────────────────────────────────
    alert_line = Text()
    alert_line.append("  ")
    if s.last_budget_alert_threshold > 0:
        alert_color = (
            "red"
            if s.last_budget_alert_threshold >= 90
            else "yellow"
            if s.last_budget_alert_threshold >= 75
            else "white"
        )
        alert_line.append(
            f"⚠ Budget alert: {s.last_budget_alert_threshold}% crossed",
            style=alert_color,
        )
    else:
        alert_line.append("Alerts: none", style="dim")
    alert_line.append("   |   ")
    alert_line.append(
        f"Rework: {s.rework_rate * 100:.1f}%  Defects: {s.defect_density * 100:.1f}%",
        style="dim",
    )

    body = Group(
        Text(""),
        progress,
        progress_label,
        Text(""),
        ms_table,
        Text(""),
        *cost_lines,
        Text(""),
        alert_line,
        Text(""),
    )

    return Panel(body, title=header, border_style="cyan", padding=(0, 1))


class RichWatch:
    """Rich-based live TUI for `sw watch`.

    Requires the `rich` library (install via `pip install
    superpower-workflow[tui]`). Surfaces RunCostProjection +
    BudgetAlert events that v1.3.17 added to the telemetry stream.

    Auto-selected by `make_watch()` when rich is importable; falls
    back to TerminalWatch (text-mode ANSI) otherwise. Force text-mode
    via SW_WATCH_NO_RICH=1.
    """

    def __init__(
        self,
        data: DashboardData,
        interval: float = 2.0,
        output: IO[str] | None = None,
    ) -> None:
        self._data = data
        self._interval = interval
        self._output = output  # rich.Live uses its own Console by default
        self._stop_event = threading.Event()

    def start(self) -> None:
        from rich.console import Console
        from rich.live import Live

        console = Console(file=self._output) if self._output else Console()
        try:
            with Live(
                _render_rich_layout(self._data.load_snapshot()),
                console=console,
                refresh_per_second=max(1.0 / max(self._interval, 0.1), 0.5),
                screen=False,
            ) as live:
                while not self._stop_event.is_set():
                    self._stop_event.wait(timeout=self._interval)
                    if self._stop_event.is_set():
                        break
                    snapshot = self._data.load_snapshot()
                    live.update(_render_rich_layout(snapshot))
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        self._stop_event.set()


def make_watch(
    data: DashboardData,
    interval: float = 2.0,
    output: IO[str] | None = None,
    *,
    prefer_rich: bool = True,
) -> TerminalWatch | RichWatch:
    """Construct the appropriate watch — rich-based when available,
    text-mode otherwise.

    Args:
        data: snapshot data source.
        interval: refresh interval in seconds.
        output: optional output stream (for testing).
        prefer_rich: if False, always use TerminalWatch.

    The auto-selection respects SW_WATCH_NO_RICH=1 to force text mode
    (useful for CI/non-TTY environments).
    """
    if prefer_rich and _rich_available():
        return RichWatch(data, interval=interval, output=output)
    return TerminalWatch(data, interval=interval, output=output)
