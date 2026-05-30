"""Claude Code statusline integration (v1.3.0 skeleton, T3.0.4).

Renders a one-line status string from `.claude/workflow-state.json` for use
in Claude Code's statusline. The exact statusline API is verified empirically
per release; until confirmed, this module exposes:

  1. `render_statusline(claude_dir)` — returns the status string
  2. `write_statusline_file(claude_dir, path=None)` — writes to a known
     location that the user (or Claude Code) can render

This is a SKELETON. Wiring into the actual Claude Code statusline API
requires verification of the API contract; once verified, register at
`.claude/settings.local.json:statusLine`.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_STATUSLINE_PATH = ".claude/statusline.txt"
IDLE = "[sw] idle"


def render_statusline(claude_dir: Path) -> str:
    """Return a one-line status. Format: `[sw] M3/9 $X.XX/$Y phase`.

    Reads workflow-state.json (run_id, completed milestones, current_step).
    Falls back to `[sw] idle` when no run in progress.
    """
    state_path = claude_dir / "workflow-state.json"
    config_path = claude_dir / "workflow.json"
    if not state_path.exists() or not config_path.exists():
        return IDLE
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return IDLE

    if not state.get("run_id"):
        return IDLE

    milestones = config.get("milestones", []) or []
    total = len(milestones)
    completed = len(state.get("completed", []) or [])
    cur_ms = state.get("current_milestone_index", 0)

    phase = state.get("current_step") or "?"
    spent = float(state.get("total_cost_usd", 0.0) or 0.0)
    cap = float(config.get("max_total_budget_usd", 0.0) or 0.0)
    cap_str = f"/${cap:.0f}" if cap else ""
    ms_str = f"M{cur_ms + 1}/{total}" if total else f"M{cur_ms + 1}"

    return f"[sw] {ms_str} ${spent:.2f}{cap_str} {phase} ({completed} done)"


def write_statusline_file(claude_dir: Path, path: Path | None = None) -> Path:
    """Render and write to disk. Returns the path written.

    Caller is responsible for polling cadence; this module doesn't watch.
    """
    target = path or claude_dir / "statusline.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_statusline(claude_dir) + "\n", encoding="utf-8")
    return target
