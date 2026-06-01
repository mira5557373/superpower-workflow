"""MCP server — exposes sw operations to Claude Code sessions over stdio.

Launched by Claude Code as a child process via `sw mcp-server`. Tools are
local file-system reads against the current project's `.claude/` directory
(scoped by CLAUDE_PROJECT_DIR env var or the optional `project_dir`
argument on every tool).

v1 ships 7 read-only tools. The side-effecting `sw_run_milestone` tool
is deferred to a follow-up cycle pending the safety gates the
adversarial review flagged (`dry_run` default-true, `confirm_token`,
`max_cost_usd`, model_override gating, lock-held semantics, error
translation layer).

Trust model: stdio is private to the spawning Claude Code session; the
process runs as the invoking user, so authorization derives entirely
from filesystem permissions. No network listener, no token. Path
traversal is rejected by `_resolve_project_dir()` which clamps every
operation under the resolved project root.

The `mcp` SDK is an optional dependency — `sw mcp-server` raises a
helpful error pointing at `pip install superpower-workflow[mcp]` if
it's not available.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)


# ----- project resolution -----


def _resolve_project_dir(args: dict[str, Any] | None) -> Path:
    """Resolve the target project directory.

    Precedence: explicit `project_dir` arg > CLAUDE_PROJECT_DIR env > cwd.
    Path traversal is rejected — the resolved path must be an absolute
    directory that contains a .claude/ subdir (or .claude/workflow.json).
    """
    arg_dir = (args or {}).get("project_dir")
    candidates: list[str] = []
    if arg_dir:
        candidates.append(arg_dir)
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        candidates.append(env_dir)
    candidates.append(os.getcwd())

    for raw in candidates:
        try:
            p = Path(raw).resolve()
        except (OSError, ValueError):
            continue
        if p.is_dir():
            return p
    raise ValueError(f"Could not resolve a valid project directory from candidates: {candidates}")


# ----- tool definitions -----


def _tool_definitions() -> list[Tool]:
    """Return the v1 tool catalog (7 read-only tools).

    Side-effecting tools (sw_run_milestone) are intentionally absent
    until the safety gates from the adversarial review land.
    """
    from mcp.types import Tool

    project_dir_prop = {
        "type": "string",
        "description": "Absolute project root; defaults to CLAUDE_PROJECT_DIR or cwd.",
    }
    return [
        Tool(
            name="sw_status",
            description=(
                "Get current workflow status: which milestone/step is running, completion "
                "counts, cost so far, and run_id. Reads .claude/workflow-state.json "
                "directly (sub-ms)."
            ),
            inputSchema={
                "type": "object",
                "properties": {"project_dir": project_dir_prop},
                "required": [],
            },
        ),
        Tool(
            name="sw_recent_runs",
            description=(
                "List recent workflow runs with cost, duration, status, and milestone "
                "counts. Reads telemetry JSONL (or DB if SW_DATABASE_URL is set)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": project_dir_prop,
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="sw_milestone_detail",
            description=(
                "Get detailed status for a specific milestone: per-phase status, cost, "
                "duration, model, and latest gap report counts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "milestone": {
                        "type": "string",
                        "description": "Milestone name (e.g. M3, P4.M1).",
                    },
                    "project_dir": project_dir_prop,
                },
                "required": ["milestone"],
            },
        ),
        Tool(
            name="sw_metrics",
            description=(
                "Aggregate quality and cost metrics: total cost, cost-per-task, rework "
                "rate, defect density, quality trend. Read-only telemetry rollup."
            ),
            inputSchema={
                "type": "object",
                "properties": {"project_dir": project_dir_prop},
                "required": [],
            },
        ),
        Tool(
            name="sw_estimate",
            description=(
                "Estimate cost and duration for planned milestones (no LLM, pure "
                "analysis). Use BEFORE running to preview spend."
            ),
            inputSchema={
                "type": "object",
                "properties": {"project_dir": project_dir_prop},
                "required": [],
            },
        ),
        Tool(
            name="sw_gap_report",
            description=(
                "Fetch the latest gap report for a milestone+phase, including counts of "
                "critical/architectural/important/minor/deferred gaps and convergence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "milestone": {"type": "string"},
                    "phase": {
                        "type": "string",
                        "description": "Phase name: plan, implement, review, push.",
                    },
                    "include_raw": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include full raw findings list (can be large).",
                    },
                    "project_dir": project_dir_prop,
                },
                "required": ["milestone", "phase"],
            },
        ),
        Tool(
            name="sw_doctor",
            description=(
                "Run pre-flight health checks (git config, claude CLI presence, "
                "workflow.json validity, lockfile state). Returns structured findings."
            ),
            inputSchema={
                "type": "object",
                "properties": {"project_dir": project_dir_prop},
                "required": [],
            },
        ),
    ]


# ----- tool handlers -----


def _handle_sw_status(args: dict[str, Any]) -> dict[str, Any]:
    """Read .claude/workflow-state.json + workflow.json and return the
    canonical status snapshot."""
    from superpower_workflow.state import load_state

    project = _resolve_project_dir(args)
    claude_dir = project / ".claude"

    cfg_path = claude_dir / "workflow.json"
    milestones_total = 0
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            milestones_total = len(cfg.get("milestones", []))
        except (json.JSONDecodeError, OSError):
            pass

    try:
        state = load_state(claude_dir)
    except (FileNotFoundError, OSError):
        return {
            "status": "uninitialized",
            "project_dir": str(project),
            "milestones_total": milestones_total,
        }

    return {
        "status": "running" if state.current_step else "idle",
        "project_dir": str(project),
        "run_id": state.run_id,
        "current_milestone_index": state.current_milestone_index,
        "current_step": state.current_step,
        "total_cost_usd": round(state.total_cost_usd, 4),
        "completed": list(state.completed),
        "failed": list(state.failed),
        "skipped": list(state.skipped),
        "milestones_total": milestones_total,
        "started_at": state.started_at,
        "plan_commit_sha": state.plan_commit_sha,
    }


def _handle_sw_recent_runs(args: dict[str, Any]) -> dict[str, Any]:
    """Read the telemetry JSONL and surface recent run_completed events."""
    project = _resolve_project_dir(args)
    claude_dir = project / ".claude"
    limit = int((args or {}).get("limit", 10))

    telemetry_path = claude_dir / "sw-telemetry.jsonl"
    if not telemetry_path.exists():
        return {"source": "telemetry", "runs": []}

    runs: list[dict[str, Any]] = []
    try:
        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "run_completed":
                continue
            runs.append(
                {
                    "run_id": ev.get("run_id", ""),
                    "status": ev.get("status", "unknown"),
                    "total_cost_usd": ev.get("total_cost_usd", 0.0),
                    "duration_seconds": ev.get("duration_seconds", 0.0),
                    "completed_count": ev.get("completed_count", 0),
                    "failed_count": ev.get("failed_count", 0),
                    "skipped_count": ev.get("skipped_count", 0),
                }
            )
    except OSError as exc:
        return {"source": "telemetry", "runs": [], "error": str(exc)}

    # Last N runs (jsonl is append-only chronological).
    return {"source": "telemetry", "runs": runs[-limit:]}


def _handle_sw_milestone_detail(args: dict[str, Any]) -> dict[str, Any]:
    """Read telemetry to surface per-phase status for a single milestone."""
    project = _resolve_project_dir(args)
    claude_dir = project / ".claude"
    milestone_name = (args or {}).get("milestone")
    if not milestone_name:
        raise ValueError("milestone argument is required")

    telemetry_path = claude_dir / "sw-telemetry.jsonl"
    if not telemetry_path.exists():
        return {"milestone": milestone_name, "phases": []}

    phases: list[dict[str, Any]] = []
    milestone_cost = 0.0
    milestone_status = "unknown"
    try:
        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("milestone") != milestone_name:
                continue
            if ev.get("type") == "phase_completed":
                phases.append(
                    {
                        "phase": ev.get("phase", ""),
                        "cost_usd": ev.get("cost_usd", 0.0),
                        "duration_ms": ev.get("duration_ms", 0),
                        "session_id": ev.get("session_id", ""),
                        "input_tokens": ev.get("input_tokens", 0),
                        "output_tokens": ev.get("output_tokens", 0),
                        "cache_hit_rate": ev.get("cache_hit_rate", 0.0),
                    }
                )
                milestone_cost += ev.get("cost_usd", 0.0)
            elif ev.get("type") == "milestone_completed":
                milestone_status = ev.get("status", "completed")
                milestone_cost = ev.get("cost_usd", milestone_cost)
    except OSError as exc:
        return {"milestone": milestone_name, "phases": [], "error": str(exc)}

    # Latest gap report (if archived).
    safe_ms = "".join(c if c.isalnum() or c in "-_." else "_" for c in milestone_name)
    gap_path = claude_dir / "reports" / safe_ms / "review" / "gap-report.json"
    latest_gap: dict[str, Any] | None = None
    if gap_path.exists():
        try:
            gap_data = json.loads(gap_path.read_text(encoding="utf-8"))
            latest_gap = {
                "critical": gap_data.get("critical_gaps", 0),
                "architectural": gap_data.get("architectural_gaps", 0),
                "important": gap_data.get("important_gaps", 0),
                "minor": gap_data.get("minor_gaps", 0),
                "deferred": gap_data.get("deferred_gaps", 0),
                "total": gap_data.get("total_gaps_found", 0),
                "converged": gap_data.get("converged", False),
            }
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "milestone": milestone_name,
        "status": milestone_status,
        "cost_usd": round(milestone_cost, 4),
        "phases": phases,
        "latest_gap_report": latest_gap,
    }


def _handle_sw_metrics(args: dict[str, Any]) -> dict[str, Any]:
    """Aggregate cost + duration across the telemetry log."""
    project = _resolve_project_dir(args)
    claude_dir = project / ".claude"

    telemetry_path = claude_dir / "sw-telemetry.jsonl"
    if not telemetry_path.exists():
        return {"total_cost_usd": 0.0, "milestone_count": 0, "phase_count": 0}

    total_cost = 0.0
    cost_by_phase: dict[str, float] = {}
    cost_by_milestone: dict[str, float] = {}
    phase_count = 0
    milestone_completed_count = 0
    milestone_failed_count = 0

    try:
        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "phase_completed":
                phase_count += 1
                cost = ev.get("cost_usd", 0.0)
                total_cost += cost
                phase = ev.get("phase", "unknown")
                cost_by_phase[phase] = cost_by_phase.get(phase, 0.0) + cost
                ms = ev.get("milestone", "unknown")
                cost_by_milestone[ms] = cost_by_milestone.get(ms, 0.0) + cost
            elif t == "milestone_completed":
                status = ev.get("status", "")
                if status == "completed":
                    milestone_completed_count += 1
                elif status == "failed":
                    milestone_failed_count += 1
    except OSError as exc:
        return {"error": str(exc)}

    return {
        "total_cost_usd": round(total_cost, 4),
        "phase_count": phase_count,
        "milestone_completed": milestone_completed_count,
        "milestone_failed": milestone_failed_count,
        "cost_by_phase": {k: round(v, 4) for k, v in cost_by_phase.items()},
        "cost_by_milestone": {k: round(v, 4) for k, v in cost_by_milestone.items()},
    }


def _handle_sw_estimate(args: dict[str, Any]) -> dict[str, Any]:
    """Pre-run cost + duration estimate from workflow.json."""
    from superpower_workflow.estimator import estimate

    project = _resolve_project_dir(args)
    cfg_path = project / ".claude" / "workflow.json"
    if not cfg_path.exists():
        return {"error": f"workflow.json not found at {cfg_path}"}

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"failed to read workflow.json: {exc}"}

    result = estimate(cfg, project)
    result["project_dir"] = str(project)
    return result


def _handle_sw_gap_report(args: dict[str, Any]) -> dict[str, Any]:
    """Read the archived gap report for a milestone+phase."""
    project = _resolve_project_dir(args)
    claude_dir = project / ".claude"
    milestone = (args or {}).get("milestone")
    phase = (args or {}).get("phase")
    if not milestone or not phase:
        raise ValueError("milestone and phase arguments are required")

    include_raw = bool((args or {}).get("include_raw", False))
    safe_ms = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(milestone))
    safe_phase = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(phase))
    gap_path = claude_dir / "reports" / safe_ms / safe_phase / "gap-report.json"

    if not gap_path.exists():
        return {
            "milestone": milestone,
            "phase": phase,
            "error": f"gap report not found at {gap_path}",
        }

    try:
        data = json.loads(gap_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"milestone": milestone, "phase": phase, "error": str(exc)}

    result: dict[str, Any] = {
        "milestone": milestone,
        "phase": phase,
        "counts": {
            "critical": data.get("critical_gaps", 0),
            "architectural": data.get("architectural_gaps", 0),
            "important": data.get("important_gaps", 0),
            "minor": data.get("minor_gaps", 0),
            "deferred": data.get("deferred_gaps", 0),
            "total": data.get("total_gaps_found", 0),
        },
        "converged": data.get("converged", False),
    }
    if include_raw:
        result["findings"] = data.get("gaps", [])
    return result


def _handle_sw_doctor(args: dict[str, Any]) -> dict[str, Any]:
    """Run pre-flight health checks via doctor.run_checks."""
    from superpower_workflow.doctor import run_checks

    project = _resolve_project_dir(args)
    results = run_checks(project)
    return {
        "project_dir": str(project),
        "healthy": all(r.ok for r in results),
        "checks": [{"status": "pass" if r.ok else "fail", "message": r.message} for r in results],
    }


# Tool name → handler dispatch table.
_TOOL_HANDLERS = {
    "sw_status": _handle_sw_status,
    "sw_recent_runs": _handle_sw_recent_runs,
    "sw_milestone_detail": _handle_sw_milestone_detail,
    "sw_metrics": _handle_sw_metrics,
    "sw_estimate": _handle_sw_estimate,
    "sw_gap_report": _handle_sw_gap_report,
    "sw_doctor": _handle_sw_doctor,
}


def dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Public dispatch entry point — exposed for unit testing without the
    full MCP transport stack."""
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return handler(args or {})


# ----- server bootstrap -----


async def _serve_stdio() -> None:
    """Run the MCP server over stdio. Blocks until the client disconnects."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent

    server = Server("superpower-workflow")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return _tool_definitions()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        try:
            result = dispatch_tool(name, arguments or {})
        except ValueError as exc:
            # Tool name unknown or required arg missing.
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
        except Exception as exc:  # noqa: BLE001
            # Don't leak stack traces to the client; log for the operator.
            logger.exception("MCP tool %s raised", name)
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"internal error in {name}: {type(exc).__name__}"}),
                )
            ]
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point invoked by `sw mcp-server`. Raises a friendly error if
    the optional `mcp` SDK isn't installed."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        import sys

        print(
            "ERROR: The MCP SDK is not installed.\n"
            "Install it with: pip install superpower-workflow[mcp]\n"
            "Or directly:    pip install mcp",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    import asyncio

    asyncio.run(_serve_stdio())
