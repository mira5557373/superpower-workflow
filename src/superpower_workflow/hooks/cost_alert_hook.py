"""Cost-alert hook — warns when sw run total cost approaches the budget cap.

A Claude Code Stop-style hook. Reads .claude/.workflow-state.json to get
the live `total_cost_usd` and .claude/workflow.json to get the configured
`max_total_budget_usd`. If the live cost has reached the warn threshold
(default 75% of cap), writes a single-line warning to stdout. The user
sees the warning in their session output.

Exit codes:
- 0: always (this hook is INFORMATIONAL — it never blocks)
- 1: only on internal error (corrupt state file etc.) — also non-blocking
     from Claude Code's POV but logged

Configuration:
- Threshold defaults to 0.75 (75% of cap). Override via env var
  SW_COST_ALERT_THRESHOLD (float between 0 and 1).
- Project dir defaults to CLAUDE_PROJECT_DIR or cwd.

Wire-up (.claude/settings.local.json or .claude/hooks.json):

    {
      "Stop": [
        {
          "matcher": ".*",
          "command": "python -m superpower_workflow.hooks.cost_alert_hook"
        }
      ]
    }

The hook is intentionally non-blocking so it can't break a Claude Code
session if state files are missing or malformed. A noisy false positive
is much worse here than a missed warning — the user gets repeat
warnings on every Stop event as cost continues to grow.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 0.75


def _resolve_project_dir() -> Path:
    """CLAUDE_PROJECT_DIR (passed by Claude Code) > cwd."""
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        try:
            p = Path(env_dir).resolve()
            if p.is_dir():
                return p
        except (OSError, ValueError):
            pass
    return Path.cwd().resolve()


def _read_threshold() -> float:
    raw = os.environ.get("SW_COST_ALERT_THRESHOLD", "")
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_THRESHOLD
    if v <= 0 or v > 1:
        return DEFAULT_THRESHOLD
    return v


def _read_state_and_cap(project: Path) -> tuple[float, float] | None:
    """Read (total_cost_usd, max_total_budget_usd) or None if unavailable."""
    claude_dir = project / ".claude"
    state_path = claude_dir / "workflow-state.json"
    cfg_path = claude_dir / "workflow.json"
    if not state_path.exists() or not cfg_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    cost = float(state.get("total_cost_usd", 0.0))
    cap = float(cfg.get("max_total_budget_usd", 0.0))
    if cap <= 0:
        return None
    return cost, cap


def main() -> int:
    """Non-throwing entry point. Catches every exception and returns 0.

    Stop hooks must never break a Claude Code session, so even unexpected
    errors degrade gracefully to a silent no-op (with stderr breadcrumb
    for the operator).
    """
    try:
        project = _resolve_project_dir()
        pair = _read_state_and_cap(project)
        if pair is None:
            return 0

        cost, cap = pair
        threshold = _read_threshold()
        if cost < threshold * cap:
            return 0

        pct = (cost / cap) * 100 if cap > 0 else 0
        bar = "⚠️" if cost >= cap else "⚡"
        print(
            f"{bar} sw cost-alert: ${cost:.2f} of ${cap:.2f} max_total_budget "
            f"({pct:.0f}%). Threshold: {threshold * 100:.0f}%. "
            f"Use `sw status` to inspect, or raise max_total_budget_usd in "
            f"{project / '.claude' / 'workflow.json'}.",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"cost_alert_hook: internal error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # Non-blocking: log to stderr but don't break the Claude Code stop.
        print(f"cost_alert_hook: internal error: {exc}", file=sys.stderr)
        sys.exit(0)
