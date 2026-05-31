"""Claude Code statusline integration — EXPERIMENTAL (v1.3.0 skeleton, T3.0.4).

⚠️  EXPERIMENTAL — wiring into the live Claude Code statusline API is DEFERRED
to v1.3.2 pending ODQ-5 verification of the statusline API contract.

What this module currently does:
  1. `render_statusline(claude_dir)` — returns a one-line status string from
     `.claude/workflow-state.json` (pure function; no Claude Code integration)
  2. `write_statusline_file(claude_dir, path=None)` — writes that string to
     a file the user can `cat` or wire into their own shell/tmux statusline

What it does NOT do (yet):
  - Register itself as `.claude/settings.local.json:statusLine` automatically
  - Push live updates to a Claude Code session (no observed API for this)
  - Survive Claude Code statusline schema changes — none verified

Consumers SHOULD treat this as a preview. The render contract may break in
v1.3.2 once the Claude Code statusline API is empirically confirmed.
"""

from __future__ import annotations

import json
from pathlib import Path

# v1.3.1 HIGH #10 marker — auto-discovery tools (e.g. `sw plugin list`) and
# the doctor check use this flag to surface "experimental" status to users.
__experimental__ = True

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
