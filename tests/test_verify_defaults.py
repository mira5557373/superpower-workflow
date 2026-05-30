"""T1.6.4 — `sw verify-defaults` audits telemetry against the default-flip
eligibility framework. Three states: insufficient data, qualifies, insufficient.
"""

from __future__ import annotations

import json

from superpower_workflow.cli import _cmd_verify_defaults


def _write_telemetry(claude_dir, events):
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "telemetry.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )


class TestVerifyDefaults:
    def test_reports_insufficient_when_no_telemetry(self, tmp_path, capsys):
        _cmd_verify_defaults(tmp_path)
        out = capsys.readouterr().out
        assert "No telemetry" in out

    def test_reports_insufficient_when_under_three_milestones(self, tmp_path, capsys):
        _write_telemetry(
            tmp_path / ".claude",
            [
                {"type": "milestone_completed", "milestone": "m1"},
                {"type": "milestone_completed", "milestone": "m2"},
            ],
        )
        _cmd_verify_defaults(tmp_path)
        out = capsys.readouterr().out
        assert "insufficient data" in out.lower()

    def test_reports_qualifies_when_curator_attrition_high(self, tmp_path, capsys):
        _write_telemetry(
            tmp_path / ".claude",
            [{"type": "milestone_completed", "milestone": f"m{i}"} for i in range(3)]
            + [
                {"type": "gap_curation_completed", "attrition_pct": 60.0},
                {"type": "gap_curation_completed", "attrition_pct": 70.0},
                {"type": "gap_curation_completed", "attrition_pct": 55.0},
            ],
        )
        _cmd_verify_defaults(tmp_path)
        out = capsys.readouterr().out
        assert "gap_curator default-flip: QUALIFIES" in out

    def test_reports_insufficient_when_attrition_low(self, tmp_path, capsys):
        _write_telemetry(
            tmp_path / ".claude",
            [{"type": "milestone_completed", "milestone": f"m{i}"} for i in range(3)]
            + [
                {"type": "gap_curation_completed", "attrition_pct": 10.0},
                {"type": "gap_curation_completed", "attrition_pct": 20.0},
                {"type": "gap_curation_completed", "attrition_pct": 15.0},
            ],
        )
        _cmd_verify_defaults(tmp_path)
        out = capsys.readouterr().out
        assert "gap_curator default-flip: INSUFFICIENT" in out

    def test_strict_mode_convergence_qualifies(self, tmp_path, capsys):
        _write_telemetry(
            tmp_path / ".claude",
            [{"type": "milestone_completed", "milestone": f"m{i}"} for i in range(3)]
            + [
                {"type": "strict_mode_iteration", "converged": True},
                {"type": "strict_mode_iteration", "converged": True},
                {"type": "strict_mode_iteration", "converged": True},
                {"type": "strict_mode_iteration", "converged": True},
                {"type": "strict_mode_iteration", "converged": False},
            ],
        )
        _cmd_verify_defaults(tmp_path)
        out = capsys.readouterr().out
        assert "strict_mode default-flip: QUALIFIES" in out

    def test_handles_corrupt_telemetry_lines(self, tmp_path, capsys):
        """Bad JSON lines are skipped, not fatal."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "telemetry.jsonl").write_text(
            "not json\n" + json.dumps({"type": "milestone_completed"}) + "\n{partial\n"
        )
        _cmd_verify_defaults(tmp_path)
        out = capsys.readouterr().out
        # Should still report (count of 1 milestone)
        assert "Milestones completed: 1" in out
