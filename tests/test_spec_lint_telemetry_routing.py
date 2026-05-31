"""v1.3.1 HIGH #4: _emit_spec_lint_event must route through TelemetryEmitter
and respect both telemetry.path and telemetry.enabled.
"""

from __future__ import annotations

import json

from superpower_workflow.cli import _emit_spec_lint_event
from superpower_workflow.validation.spec_linter import lint_spec


def _make_report(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("## Functional\n1. The app must persist a todo.\n" + " word" * 250)
    return lint_spec(spec)


def _read_events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestEmitSpecLintRouting:
    def test_writes_to_default_path_when_no_workflow_json(self, tmp_path):
        """No workflow.json → uses .claude/telemetry.jsonl default."""
        (tmp_path / ".claude").mkdir()
        report = _make_report(tmp_path)
        _emit_spec_lint_event(tmp_path, report)
        events = _read_events(tmp_path / ".claude" / "telemetry.jsonl")
        assert len(events) == 1
        assert events[0]["type"] == "spec_lint_completed"
        assert events[0]["score"] == report.score

    def test_respects_custom_telemetry_path(self, tmp_path):
        """v1.3.1 HIGH #4: previously hardcoded .claude/telemetry.jsonl."""
        cd = tmp_path / ".claude"
        cd.mkdir()
        (cd / "workflow.json").write_text(
            json.dumps({"telemetry": {"path": "custom-events.jsonl"}})
        )
        report = _make_report(tmp_path)
        _emit_spec_lint_event(tmp_path, report)
        events = _read_events(tmp_path / "custom-events.jsonl")
        assert len(events) == 1

    def test_respects_telemetry_disabled(self, tmp_path):
        """v1.3.1 HIGH #4: telemetry.enabled = false must skip emission."""
        cd = tmp_path / ".claude"
        cd.mkdir()
        (cd / "workflow.json").write_text(json.dumps({"telemetry": {"enabled": False}}))
        report = _make_report(tmp_path)
        _emit_spec_lint_event(tmp_path, report)
        # Default path should not exist (nothing written)
        default_jsonl = cd / "telemetry.jsonl"
        if default_jsonl.exists():
            assert _read_events(default_jsonl) == []

    def test_path_traversal_telemetry_blocked(self, tmp_path):
        """Combined with HIGH #1: telemetry.path escaping project root is rejected."""
        cd = tmp_path / ".claude"
        cd.mkdir()
        (cd / "workflow.json").write_text(json.dumps({"telemetry": {"path": "../../etc/passwd"}}))
        report = _make_report(tmp_path)
        _emit_spec_lint_event(tmp_path, report)
        # Nothing should be written anywhere reachable
        default = cd / "telemetry.jsonl"
        assert _read_events(default) == []

    def test_event_dict_has_expected_fields(self, tmp_path):
        """Schema check: emitted event has run_id, spec_path, score, counts."""
        (tmp_path / ".claude").mkdir()
        report = _make_report(tmp_path)
        _emit_spec_lint_event(tmp_path, report, run_id="r-abc")
        events = _read_events(tmp_path / ".claude" / "telemetry.jsonl")
        assert events
        e = events[0]
        for k in (
            "type",
            "run_id",
            "spec_path",
            "score",
            "checks_passed",
            "checks_warned",
            "checks_failed",
            "blocker_count",
        ):
            assert k in e, f"missing field {k}"
        assert e["run_id"] == "r-abc"
