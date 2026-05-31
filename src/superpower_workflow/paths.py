"""Shared path-resolution helpers — v1.3.2 #3 centralization.

The v1.3.1 HIGH #1 fix added a path-traversal guard for `telemetry.path` but
only wired it into `sw clean` and `_emit_spec_lint_event`. The orchestrator,
`sw metrics`, `sw server sync`, and the dashboard each duplicated the unsafe
pattern (`project_root / config["telemetry"]["path"]`) — letting an attacker
who controls `workflow.json` direct telemetry writes/reads outside the
project root.

v1.3.2 routes every consumer through `resolve_telemetry_path()` so the
docstring-promised central guard is actually central. Each caller passes
the project_root and the parsed config dict; the helper returns either a
Path inside the project root or None.
"""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_TELEMETRY_REL = ".claude/telemetry.jsonl"


def resolve_telemetry_path(
    project_root: Path,
    config: dict | None = None,
    *,
    quiet: bool = False,
) -> Path | None:
    """Resolve `telemetry.path` from config under project_root, refusing escapes.

    Args:
        project_root: directory the path must stay inside.
        config: parsed workflow.json dict (or None — falls back to default).
        quiet: when True, swallow the stderr warning on traversal — useful
            for read-only callers (dashboard polling) that shouldn't spam
            the user's terminal.

    Returns:
        A resolved Path that is guaranteed to be inside `project_root`, or
        None when the configured path escapes the root.
    """
    rel = DEFAULT_TELEMETRY_REL
    if config is not None:
        cfg_path = config.get("telemetry", {}).get("path")
        if isinstance(cfg_path, str) and cfg_path:
            rel = cfg_path
    candidate = (project_root / rel).resolve()
    root_resolved = project_root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        if not quiet:
            print(
                f"  WARNING: telemetry.path '{rel}' escapes project root; refusing to use it.",
                file=sys.stderr,
            )
        return None
    return candidate


def telemetry_enabled(config: dict | None) -> bool:
    """Truthy check on `telemetry.enabled` (default True).

    v1.3.2 #19 hardening: previously some sites used `is False` strict identity,
    which would mishandle JSON-loaded `0`/`null`/`"false"`. The helper makes
    every consumer agree.
    """
    if config is None:
        return True
    return bool(config.get("telemetry", {}).get("enabled", True))
