from __future__ import annotations

import json

from superpower_workflow.dashboard.data import DashboardSnapshot

_GAUGE_METRICS = [
    ("sw_milestones_total", "Total milestones in workflow", "milestones_total"),
    ("sw_milestones_completed", "Completed milestones", "milestones_completed"),
    ("sw_milestones_failed", "Failed milestones", "milestones_failed"),
    ("sw_milestones_skipped", "Skipped milestones", "milestones_skipped"),
    ("sw_total_cost_usd", "Total cost in USD", "total_cost_usd"),
    ("sw_cost_per_task", "Cost per successful task in USD", "cost_per_task"),
    ("sw_elapsed_seconds", "Elapsed wall-clock seconds", "elapsed_seconds"),
    ("sw_total_duration_seconds", "Total run duration in seconds", "total_duration_seconds"),
    ("sw_rework_rate", "Rework rate (retries per milestone)", "rework_rate"),
    ("sw_defect_density", "Quality gate failure rate", "defect_density"),
]


def render_prometheus(snapshot: DashboardSnapshot) -> str:
    lines: list[str] = []
    d = snapshot.to_dict()

    for name, help_text, field_name in _GAUGE_METRICS:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {d[field_name]}")
        lines.append("")

    def _escape_label(v: str) -> str:
        return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    if snapshot.cost_by_milestone:
        lines.append("# HELP sw_milestone_cost_usd Cost per milestone in USD")
        lines.append("# TYPE sw_milestone_cost_usd gauge")
        for ms_name, cost in snapshot.cost_by_milestone.items():
            lines.append(f'sw_milestone_cost_usd{{milestone="{_escape_label(ms_name)}"}} {cost}')
        lines.append("")

    if snapshot.duration_by_milestone:
        lines.append("# HELP sw_milestone_duration_seconds Duration per milestone")
        lines.append("# TYPE sw_milestone_duration_seconds gauge")
        for ms_name, dur in snapshot.duration_by_milestone.items():
            safe = _escape_label(ms_name)
            lines.append(f'sw_milestone_duration_seconds{{milestone="{safe}"}} {dur}')
        lines.append("")

    return "\n".join(lines) + "\n"


def format_sse_event(snapshot: DashboardSnapshot) -> str:
    payload = json.dumps(snapshot.to_dict(), separators=(",", ":"))
    return f"data: {payload}\n\n"


def format_sse_keepalive() -> str:
    return ": keepalive\n\n"
