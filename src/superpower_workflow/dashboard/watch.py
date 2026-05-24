from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardSnapshot

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
