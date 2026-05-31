"""v1.3.1 HIGH #1 regression: sw clean must refuse to delete files outside project_root.

Pre-fix: workflow.json `{"telemetry": {"path": "../../etc/passwd"}}` made
`sw clean` an arbitrary file-delete primitive against any path the user
could read.
"""

from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _resolve_telemetry_path


def _setup(project_root: Path, telemetry_path_value: str) -> None:
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "workflow.json").write_text(
        json.dumps({"telemetry": {"path": telemetry_path_value}})
    )


class TestResolveTelemetryPath:
    def test_default_in_project(self, tmp_path):
        _setup(tmp_path, ".claude/telemetry.jsonl")
        resolved = _resolve_telemetry_path(tmp_path)
        assert resolved is not None
        assert resolved == (tmp_path / ".claude" / "telemetry.jsonl").resolve()

    def test_custom_in_project_accepted(self, tmp_path):
        _setup(tmp_path, "logs/events.jsonl")
        resolved = _resolve_telemetry_path(tmp_path)
        assert resolved is not None
        assert resolved.name == "events.jsonl"

    def test_dotdot_traversal_rejected(self, tmp_path, capsys):
        """The critical regression test — must NOT return a path outside project_root."""
        _setup(tmp_path, "../../etc/passwd")
        resolved = _resolve_telemetry_path(tmp_path)
        assert resolved is None
        captured = capsys.readouterr()
        assert "escapes project root" in captured.err

    def test_absolute_outside_rejected(self, tmp_path, capsys):
        # /tmp/foo is absolute and almost certainly outside tmp_path
        _setup(tmp_path, "/tmp/sw-clean-attack-target")
        resolved = _resolve_telemetry_path(tmp_path)
        assert resolved is None
        captured = capsys.readouterr()
        assert "escapes project root" in captured.err

    def test_missing_workflow_json_returns_default(self, tmp_path):
        """No workflow.json at all → fall back to .claude/telemetry.jsonl."""
        # No setup — pure tmp_path
        resolved = _resolve_telemetry_path(tmp_path)
        assert resolved is not None
        assert resolved == (tmp_path / ".claude" / "telemetry.jsonl").resolve()

    def test_corrupt_workflow_json_returns_default(self, tmp_path):
        cd = tmp_path / ".claude"
        cd.mkdir()
        (cd / "workflow.json").write_text("not valid json {")
        resolved = _resolve_telemetry_path(tmp_path)
        assert resolved is not None
        assert resolved.name == "telemetry.jsonl"
