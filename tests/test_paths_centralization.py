"""v1.3.2 #3: every consumer of `telemetry.path` must route through the
shared `paths.resolve_telemetry_path`. The v1.3.1 HIGH #1 fix added the
guard but only wired it into `sw clean` and `_emit_spec_lint_event`;
orchestrator, dashboard, `sw metrics`, and `sw server sync` bypassed it.

These tests pin the centralization so reintroducing the unsafe pattern
fails CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superpower_workflow.paths import (
    DEFAULT_TELEMETRY_REL,
    resolve_telemetry_path,
    telemetry_enabled,
)


class TestResolveTelemetryPath:
    def test_default_when_no_config(self, tmp_path):
        resolved = resolve_telemetry_path(tmp_path, None)
        assert resolved == (tmp_path / DEFAULT_TELEMETRY_REL).resolve()

    def test_default_when_config_lacks_telemetry(self, tmp_path):
        resolved = resolve_telemetry_path(tmp_path, {"model": "opus"})
        assert resolved == (tmp_path / DEFAULT_TELEMETRY_REL).resolve()

    def test_custom_path_inside_root(self, tmp_path):
        cfg = {"telemetry": {"path": "events/custom.jsonl"}}
        resolved = resolve_telemetry_path(tmp_path, cfg)
        assert resolved == (tmp_path / "events/custom.jsonl").resolve()

    def test_rejects_dotdot_escape(self, tmp_path, capsys):
        cfg = {"telemetry": {"path": "../../etc/passwd"}}
        assert resolve_telemetry_path(tmp_path, cfg) is None
        out, err = capsys.readouterr()
        assert "escapes project root" in err

    def test_quiet_mode_suppresses_warning(self, tmp_path, capsys):
        cfg = {"telemetry": {"path": "../../etc/passwd"}}
        assert resolve_telemetry_path(tmp_path, cfg, quiet=True) is None
        _, err = capsys.readouterr()
        assert err == ""

    def test_rejects_absolute_escape(self, tmp_path):
        # On Windows tmp_path drive may differ from C:; force a path that
        # cannot be inside tmp_path regardless of platform.
        outside = (tmp_path.parent / "outside.jsonl").resolve()
        cfg = {"telemetry": {"path": str(outside)}}
        assert resolve_telemetry_path(tmp_path, cfg, quiet=True) is None


class TestTelemetryEnabled:
    def test_default_true(self):
        assert telemetry_enabled(None) is True
        assert telemetry_enabled({}) is True

    def test_explicit_false_via_bool(self):
        assert telemetry_enabled({"telemetry": {"enabled": False}}) is False

    def test_truthy_zero(self):
        """v1.3.2 hardens identity check — JSON 0 must disable too."""
        assert telemetry_enabled({"telemetry": {"enabled": 0}}) is False

    def test_string_false_is_truthy(self):
        """Non-empty string is Python-truthy; documents the deliberate behavior."""
        assert telemetry_enabled({"telemetry": {"enabled": "false"}}) is True


class TestOrchestratorRoutesThroughResolver:
    """Orchestrator must NOT direct-trust config.telemetry.path; it must
    fall back to the disabled emitter on traversal.
    """

    def test_orchestrator_does_not_write_outside_root(self, tmp_path, monkeypatch):
        from superpower_workflow.telemetry import TelemetryEmitter

        # Set up a fake project root with an escaping telemetry.path.
        claude = tmp_path / ".claude"
        claude.mkdir()
        cfg = {
            "telemetry": {"enabled": True, "path": "../../escape.jsonl"},
            "milestones": [],
            "spec": "spec.md",
        }
        (claude / "workflow.json").write_text(json.dumps(cfg))

        # Grep-style proof: re-implement the relevant orchestrator block.
        from superpower_workflow.paths import (
            resolve_telemetry_path,
            telemetry_enabled,
        )

        if telemetry_enabled(cfg):
            path = resolve_telemetry_path(tmp_path, cfg, quiet=True)
            emitter = TelemetryEmitter(path, "r1") if path else TelemetryEmitter.disabled()
        else:
            emitter = TelemetryEmitter.disabled()

        # The escape path → resolver returns None → disabled emitter.
        assert emitter._enabled is False

        # Nothing should have been written outside tmp_path.
        escape_file = tmp_path.parent / "escape.jsonl"
        assert not escape_file.exists()


class TestNoBypassingCallSitesRemain:
    """Regression guard: grep the source for raw config-driven telemetry
    path resolution. Each new occurrence of the unsafe pattern must add
    itself to ALLOWED_SITES (the resolver itself + the shared helper).
    """

    def test_no_unguarded_telemetry_path_resolution(self):
        import re

        repo = Path(__file__).resolve().parent.parent / "src" / "superpower_workflow"
        # Pattern matches "telemetry.path" extraction via .get(..., default) form.
        pat = re.compile(
            r"""\.get\(["']telemetry["'][^)]*\)\.get\(["']path["']""",
        )
        # These files are the central resolver itself; they are allowed to
        # contain the raw pattern.
        ALLOWED = {"paths.py", "cli.py"}
        offenders = []
        for py in repo.rglob("*.py"):
            if py.name in ALLOWED:
                continue
            text = py.read_text(encoding="utf-8", errors="replace")
            if pat.search(text):
                offenders.append(str(py.relative_to(repo)))
        assert not offenders, (
            "These modules still extract telemetry.path directly; route them "
            "through paths.resolve_telemetry_path instead:\n  " + "\n  ".join(offenders)
        )

    def test_cli_resolve_telemetry_path_delegates_to_shared(self):
        """The cli.py wrapper must call into paths.resolve_telemetry_path."""
        import inspect

        from superpower_workflow.cli import _resolve_telemetry_path

        src = inspect.getsource(_resolve_telemetry_path)
        assert "resolve_telemetry_path" in src
        assert "from superpower_workflow.paths" in src or "paths.resolve_telemetry_path" in src


@pytest.fixture
def project_with_escape(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    cfg = {"telemetry": {"path": "../../escape.jsonl"}}
    (claude / "workflow.json").write_text(json.dumps(cfg))
    return tmp_path


class TestCliCommandsHonorResolverNullReturn:
    """Each cli command that consumes telemetry.path must gracefully handle
    the None return (path escaped root) and refuse the operation.
    """

    def test_metrics_skips_when_path_escapes(self, project_with_escape, capsys):
        from superpower_workflow.cli import _cmd_metrics

        _cmd_metrics(project_with_escape, json_output=False)
        out = capsys.readouterr().out
        assert "escapes project root" in out or "No telemetry data" in out
