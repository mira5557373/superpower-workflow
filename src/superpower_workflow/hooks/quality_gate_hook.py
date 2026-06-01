"""Quality-gate hook — surfaces actionable next-steps after a sw run.

A Claude Code Stop-style hook that reads .claude/.quality-gate-results.json
(written by `_verify_quality_gates` during Phase B and Phase C checkpoints)
and prints a structured "what failed and how to fix it" summary to stdout.

This is INFORMATIONAL — the gate-failure handling (fix-loop, retry) is
done by the orchestrator itself. This hook just makes the failure
visible at session boundaries so the user knows there's work to look at.

Exit codes:
- 0: always (non-blocking)

Wire-up (.claude/settings.local.json or .claude/hooks.json):

    {
      "Stop": [
        {
          "matcher": ".*",
          "command": "python -m superpower_workflow.hooks.quality_gate_hook"
        }
      ]
    }

Compose with cost_alert_hook by listing both Stop hooks — they run
sequentially, both non-blocking, both safe on missing state files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Remediation hints by gate name — keeps the output compact + actionable.
_REMEDIATION: dict[str, str] = {
    "lint": "Run the configured lint command locally and fix the reported issues.",
    "sast": "Investigate the SAST finding in the QG output and patch or annotate.",
    "secret_scan": "A potential secret was detected — review and rotate if real.",
    "dep_scan": "An advisory or vulnerable dependency was flagged. Update or pin.",
}


def _resolve_project_dir() -> Path:
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        try:
            p = Path(env_dir).resolve()
            if p.is_dir():
                return p
        except (OSError, ValueError):
            pass
    return Path.cwd().resolve()


def _read_results(project: Path) -> dict | None:
    """Return the parsed gate-results dict, or None if unavailable."""
    results_path = project / ".claude" / ".quality-gate-results.json"
    if not results_path.exists():
        return None
    try:
        return json.loads(results_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _format_failures(results: dict) -> str | None:
    """Return a multi-line warning string for any failed gates, or None
    if everything passed."""
    if not isinstance(results, dict):
        return None
    failed: list[tuple[str, str]] = []
    for gate_name, entry in results.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("passed", True):
            continue
        detail = str(entry.get("detail", "")).strip()
        # Truncate gate output for the Stop hook display.
        if len(detail) > 280:
            detail = detail[:280] + "…"
        failed.append((gate_name, detail))
    if not failed:
        return None

    lines = [f"❌ sw quality-gate: {len(failed)} gate(s) failed."]
    for name, detail in failed:
        remediation = _REMEDIATION.get(name, "")
        lines.append(f"  - {name}: {detail[:160]}")
        if remediation:
            lines.append(f"      → {remediation}")
    lines.append(
        "Inspect .claude/.quality-gate-results.json for full output. "
        "Re-run `sw run` after fixing — the QG fix-loop will re-check."
    )
    return "\n".join(lines)


def main() -> int:
    """Non-throwing entry point. Catches every exception and returns 0.

    Stop hooks must never break a Claude Code session.
    """
    try:
        project = _resolve_project_dir()
        results = _read_results(project)
        if results is None:
            return 0
        summary = _format_failures(results)
        if summary is None:
            return 0
        print(summary, flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"quality_gate_hook: internal error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"quality_gate_hook: internal error: {exc}", file=sys.stderr)
        sys.exit(0)
