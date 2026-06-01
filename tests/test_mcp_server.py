"""Tests for the sw MCP server (v1 — 7 read-only tools).

The transport-layer behavior (stdio JSON-RPC over the `mcp` SDK) is
covered by integration tests that spawn the server as a subprocess.
These unit tests pin the dispatch contract: every tool registered in
the catalog is dispatchable, returns the documented shape, rejects
invalid args, and (where applicable) rejects path traversal.

Side-effecting `sw_run_milestone` is intentionally NOT in v1's
dispatch table; verified by the catalog-stability test.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from superpower_workflow.mcp_server import (
    _TOOL_HANDLERS,
    _resolve_project_dir,
    _tool_definitions,
    dispatch_tool,
)
from superpower_workflow.state import WorkflowState, save_state


def _make_project(tmp_path: Path, *, with_state: bool = True) -> Path:
    """Build a minimal project directory with .claude/ + workflow.json + state."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    cfg = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "budgets": {"plan": 25, "implement": 25, "review": 10, "push": 3},
        "effort": {"plan": "max"},
        "verify_commands": {},
        "milestones": [{"name": "M1"}, {"name": "M2"}],
        "plugins": {},
        "validation": {},
        "quality_gates": {},
        "telemetry": {"enabled": False},
        "max_total_budget_usd": 100.0,
    }
    (claude_dir / "workflow.json").write_text(json.dumps(cfg))
    if with_state:
        s = WorkflowState()
        s.run_id = "01TESTMCP1234567890ABCDEFG"
        save_state(claude_dir, s)
    (tmp_path / "spec.md").write_text("# Spec\n")
    return tmp_path


# ---- catalog stability ----


class TestToolCatalog:
    """Lock the v1 tool surface — adding/removing tools requires explicit
    change to this test."""

    EXPECTED_NAMES = {
        "sw_status",
        "sw_recent_runs",
        "sw_milestone_detail",
        "sw_metrics",
        "sw_estimate",
        "sw_gap_report",
        "sw_doctor",
    }

    def test_catalog_lists_exactly_seven_tools(self):
        defs = _tool_definitions()
        assert len(defs) == 7, f"Expected 7 tools; got {len(defs)}"

    def test_catalog_names_match_expected(self):
        defs = _tool_definitions()
        actual = {t.name for t in defs}
        assert actual == self.EXPECTED_NAMES, (
            f"Tool name set drifted. Expected {self.EXPECTED_NAMES}, got {actual}"
        )

    def test_sw_run_milestone_not_in_v1(self):
        """Side-effecting tool deferred per adversarial Verdict 1
        (dry_run default-true, confirm_token, max_cost_usd gates needed)."""
        defs = _tool_definitions()
        names = {t.name for t in defs}
        assert "sw_run_milestone" not in names, (
            "sw_run_milestone must NOT ship in v1 — adversarial review "
            "flagged safety gates that need to land first."
        )

    def test_every_tool_has_valid_input_schema(self):
        defs = _tool_definitions()
        for t in defs:
            schema = t.inputSchema
            assert isinstance(schema, dict), f"{t.name} inputSchema must be dict"
            assert schema.get("type") == "object", f"{t.name} inputSchema.type must be 'object'"
            assert "properties" in schema, f"{t.name} inputSchema must have properties"

    def test_every_catalog_tool_has_a_handler(self):
        defs = _tool_definitions()
        for t in defs:
            assert t.name in _TOOL_HANDLERS, f"Tool {t.name} declared but no handler registered"


# ---- project-dir resolution ----


class TestProjectDirResolution:
    def test_explicit_arg_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/nonexistent/env/path")
        p = _resolve_project_dir({"project_dir": str(tmp_path)})
        assert p == tmp_path.resolve()

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        p = _resolve_project_dir({})
        assert p == tmp_path.resolve()

    def test_cwd_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        p = _resolve_project_dir({})
        assert p == tmp_path.resolve()

    def test_bad_explicit_falls_through_to_cwd(self, tmp_path, monkeypatch):
        """Falls through the candidate list (explicit → env → cwd) and
        returns the first one that resolves to a valid directory. Bad
        explicit path doesn't raise — it just gets skipped."""
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        p = _resolve_project_dir({"project_dir": "/this/path/does/not/exist/anywhere"})
        assert p == tmp_path.resolve()

    def test_raises_when_no_candidate_resolves(self, monkeypatch):
        """If every candidate fails (no explicit arg, env unset, cwd
        somehow invalid), ValueError surfaces."""
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        with (
            patch("os.getcwd", return_value="/totally/nonexistent/path/x"),
            pytest.raises(ValueError),
        ):
            _resolve_project_dir({})


# ---- sw_status ----


class TestSwStatus:
    def test_idle_project_returns_status(self, tmp_path):
        proj = _make_project(tmp_path)
        result = dispatch_tool("sw_status", {"project_dir": str(proj)})
        assert result["status"] == "idle"
        assert result["milestones_total"] == 2
        assert result["total_cost_usd"] == 0.0
        assert result["run_id"] == "01TESTMCP1234567890ABCDEFG"

    def test_uninitialized_project(self, tmp_path):
        # No .claude/state.json
        proj = _make_project(tmp_path, with_state=False)
        # Delete state file by recreating the dir
        (proj / ".claude" / "workflow-state.json").unlink(missing_ok=True)
        result = dispatch_tool("sw_status", {"project_dir": str(proj)})
        # Even without state, milestones_total comes from workflow.json
        assert result["milestones_total"] == 2

    def test_running_project_shows_running_status(self, tmp_path):
        proj = _make_project(tmp_path)
        from superpower_workflow.state import load_state

        s = load_state(proj / ".claude")
        s.current_step = "implement"
        save_state(proj / ".claude", s)
        result = dispatch_tool("sw_status", {"project_dir": str(proj)})
        assert result["status"] == "running"
        assert result["current_step"] == "implement"


# ---- sw_recent_runs ----


class TestSwRecentRuns:
    def test_no_telemetry_returns_empty(self, tmp_path):
        proj = _make_project(tmp_path)
        result = dispatch_tool("sw_recent_runs", {"project_dir": str(proj)})
        assert result["runs"] == []
        assert result["source"] == "telemetry"

    def test_extracts_run_completed_events(self, tmp_path):
        proj = _make_project(tmp_path)
        tel = proj / ".claude" / "sw-telemetry.jsonl"
        events = [
            {"type": "phase_completed", "cost_usd": 1.0},  # ignored
            {
                "type": "run_completed",
                "run_id": "01RUN1",
                "status": "completed",
                "total_cost_usd": 5.5,
                "duration_seconds": 120,
                "completed_count": 2,
                "failed_count": 0,
                "skipped_count": 0,
            },
            {
                "type": "run_completed",
                "run_id": "01RUN2",
                "status": "failed",
                "total_cost_usd": 1.0,
                "duration_seconds": 60,
                "completed_count": 0,
                "failed_count": 1,
                "skipped_count": 0,
            },
        ]
        tel.write_text("\n".join(json.dumps(e) for e in events))
        result = dispatch_tool("sw_recent_runs", {"project_dir": str(proj)})
        assert len(result["runs"]) == 2
        assert result["runs"][0]["run_id"] == "01RUN1"
        assert result["runs"][1]["status"] == "failed"

    def test_limit_takes_last_n(self, tmp_path):
        proj = _make_project(tmp_path)
        tel = proj / ".claude" / "sw-telemetry.jsonl"
        events = [
            {"type": "run_completed", "run_id": f"01RUN{i}", "status": "completed"}
            for i in range(5)
        ]
        tel.write_text("\n".join(json.dumps(e) for e in events))
        result = dispatch_tool("sw_recent_runs", {"project_dir": str(proj), "limit": 2})
        assert len(result["runs"]) == 2
        # Last 2 chronologically.
        assert result["runs"][0]["run_id"] == "01RUN3"
        assert result["runs"][1]["run_id"] == "01RUN4"


# ---- sw_milestone_detail ----


class TestSwMilestoneDetail:
    def test_returns_phases_for_milestone(self, tmp_path):
        proj = _make_project(tmp_path)
        tel = proj / ".claude" / "sw-telemetry.jsonl"
        events = [
            {
                "type": "phase_completed",
                "milestone": "M1",
                "phase": "plan",
                "cost_usd": 1.0,
                "duration_ms": 1000,
                "input_tokens": 50,
                "output_tokens": 200,
            },
            {
                "type": "phase_completed",
                "milestone": "M1",
                "phase": "implement",
                "cost_usd": 2.5,
                "duration_ms": 2500,
            },
            {
                "type": "phase_completed",
                "milestone": "M2",  # different milestone — must be excluded
                "phase": "plan",
                "cost_usd": 99,
            },
        ]
        tel.write_text("\n".join(json.dumps(e) for e in events))
        result = dispatch_tool("sw_milestone_detail", {"project_dir": str(proj), "milestone": "M1"})
        assert result["milestone"] == "M1"
        assert len(result["phases"]) == 2
        assert result["phases"][0]["phase"] == "plan"
        assert result["phases"][0]["cost_usd"] == 1.0

    def test_missing_milestone_arg_raises(self, tmp_path):
        proj = _make_project(tmp_path)
        with pytest.raises(ValueError, match="milestone"):
            dispatch_tool("sw_milestone_detail", {"project_dir": str(proj)})


# ---- sw_metrics ----


class TestSwMetrics:
    def test_aggregates_cost_by_phase_and_milestone(self, tmp_path):
        proj = _make_project(tmp_path)
        tel = proj / ".claude" / "sw-telemetry.jsonl"
        events = [
            {"type": "phase_completed", "milestone": "M1", "phase": "plan", "cost_usd": 1.0},
            {"type": "phase_completed", "milestone": "M1", "phase": "implement", "cost_usd": 2.0},
            {"type": "phase_completed", "milestone": "M2", "phase": "plan", "cost_usd": 1.5},
            {"type": "milestone_completed", "milestone": "M1", "status": "completed"},
            {"type": "milestone_completed", "milestone": "M2", "status": "failed"},
        ]
        tel.write_text("\n".join(json.dumps(e) for e in events))
        result = dispatch_tool("sw_metrics", {"project_dir": str(proj)})
        assert result["total_cost_usd"] == 4.5
        assert result["phase_count"] == 3
        assert result["milestone_completed"] == 1
        assert result["milestone_failed"] == 1
        assert result["cost_by_phase"]["plan"] == 2.5
        assert result["cost_by_milestone"]["M1"] == 3.0


# ---- sw_estimate ----


class TestSwEstimate:
    def test_returns_estimate_from_workflow_json(self, tmp_path):
        proj = _make_project(tmp_path)
        result = dispatch_tool("sw_estimate", {"project_dir": str(proj)})
        # Estimator returns milestone_count + cost ranges + duration ranges.
        assert result["milestone_count"] == 2
        assert "cost_optimistic" in result
        assert "cost_pessimistic" in result
        assert result["cost_optimistic"] <= result["cost_pessimistic"]

    def test_missing_workflow_json_returns_error(self, tmp_path):
        proj = _make_project(tmp_path)
        (proj / ".claude" / "workflow.json").unlink()
        result = dispatch_tool("sw_estimate", {"project_dir": str(proj)})
        assert "error" in result


# ---- sw_gap_report ----


class TestSwGapReport:
    def test_returns_counts_from_archived_report(self, tmp_path):
        proj = _make_project(tmp_path)
        reports_dir = proj / ".claude" / "reports" / "M1" / "review"
        reports_dir.mkdir(parents=True)
        gap_data = {
            "critical_gaps": 1,
            "architectural_gaps": 2,
            "important_gaps": 3,
            "minor_gaps": 4,
            "deferred_gaps": 0,
            "total_gaps_found": 10,
            "converged": False,
            "gaps": [{"severity": "critical", "title": "X"}],
        }
        (reports_dir / "gap-report.json").write_text(json.dumps(gap_data))

        result = dispatch_tool(
            "sw_gap_report",
            {"project_dir": str(proj), "milestone": "M1", "phase": "review"},
        )
        assert result["counts"]["critical"] == 1
        assert result["counts"]["total"] == 10
        assert result["converged"] is False
        # findings absent by default (large payload).
        assert "findings" not in result

    def test_include_raw_returns_findings(self, tmp_path):
        proj = _make_project(tmp_path)
        reports_dir = proj / ".claude" / "reports" / "M1" / "review"
        reports_dir.mkdir(parents=True)
        (reports_dir / "gap-report.json").write_text(
            json.dumps({"gaps": [{"severity": "x"}], "total_gaps_found": 1})
        )
        result = dispatch_tool(
            "sw_gap_report",
            {
                "project_dir": str(proj),
                "milestone": "M1",
                "phase": "review",
                "include_raw": True,
            },
        )
        assert "findings" in result
        assert result["findings"] == [{"severity": "x"}]

    def test_missing_report_returns_error(self, tmp_path):
        proj = _make_project(tmp_path)
        result = dispatch_tool(
            "sw_gap_report",
            {"project_dir": str(proj), "milestone": "M1", "phase": "review"},
        )
        assert "error" in result

    def test_path_traversal_in_milestone_sanitized(self, tmp_path):
        """Verdict 2 fix — milestone arg is sanitized so '../etc/passwd'
        can't escape the reports/ subdir."""
        proj = _make_project(tmp_path)
        # Even if attacker tries '../', the safe_ms replaces / with _
        result = dispatch_tool(
            "sw_gap_report",
            {
                "project_dir": str(proj),
                "milestone": "../etc/passwd",
                "phase": "review",
            },
        )
        # Returns error (file not found at the sanitized path) — does NOT
        # raise or leak the parent directory.
        assert "error" in result


# ---- sw_doctor ----


class TestSwDoctor:
    def test_returns_check_results(self, tmp_path):
        proj = _make_project(tmp_path)
        result = dispatch_tool("sw_doctor", {"project_dir": str(proj)})
        assert "healthy" in result
        assert isinstance(result["checks"], list)
        # Every check has status + message.
        for c in result["checks"]:
            assert c["status"] in ("pass", "fail")
            assert "message" in c


# ---- unknown tool ----


class TestUnknownTool:
    def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            dispatch_tool("nonexistent_tool", {})


# ---- optional mcp dependency ----


class TestOptionalMcpDependency:
    def test_main_with_mcp_missing_exits_cleanly(self, capsys, monkeypatch):
        """`sw mcp-server` raises SystemExit(1) with a helpful message
        if the mcp SDK is missing — no stack trace, no cryptic ImportError."""
        # Simulate missing mcp by making the import fail.
        import sys as real_sys

        from superpower_workflow import mcp_server

        original_mcp = real_sys.modules.get("mcp")
        real_sys.modules["mcp"] = None  # makes `import mcp` raise

        try:
            with pytest.raises(SystemExit) as exc_info:
                mcp_server.main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "MCP SDK is not installed" in captured.err
            assert "pip install" in captured.err
        finally:
            if original_mcp is not None:
                real_sys.modules["mcp"] = original_mcp
            else:
                real_sys.modules.pop("mcp", None)
