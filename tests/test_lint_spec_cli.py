"""CLI integration tests for `sw lint-spec` and `sw decompose --force` (T1.7.2/T1.7.3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from superpower_workflow.cli import _cmd_decompose, _cmd_lint_spec


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _good_spec() -> str:
    return (
        "## Functional\n"
        "1. The app must persist data.\n"
        "2. The app must list items.\n"
        "## Non-functional\n- perf\n- security\n- observability\n"
        "## Quality gates\nlint, test, coverage >=90%.\n"
        "## Out of scope\n- networking\n" + " word" * 250
    )


def _broken_spec() -> str:
    return "Some prose. TBD details.\n"


class TestLintSpecCli:
    def test_exit_0_on_pass(self, tmp_path, capsys):
        _write(tmp_path / "spec.md", _good_spec())
        rc = _cmd_lint_spec(tmp_path, "spec.md", strict=False, section=None)
        assert rc == 0
        out = capsys.readouterr().out
        assert "PASS" in out or "WARN" in out

    def test_exit_1_on_fail(self, tmp_path, capsys):
        _write(tmp_path / "spec.md", _broken_spec())
        rc = _cmd_lint_spec(tmp_path, "spec.md", strict=False, section=None)
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAIL" in out

    def test_exit_1_on_warn_in_strict(self, tmp_path, capsys):
        # Good spec but small (warns on length) -> WARN under strict -> exit 1
        _write(tmp_path / "spec.md", "## Reqs\n1. foo must work.\n")
        rc = _cmd_lint_spec(tmp_path, "spec.md", strict=True, section=None)
        assert rc == 1

    def test_missing_file_returns_1(self, tmp_path, capsys):
        rc = _cmd_lint_spec(tmp_path, "nonexistent.md", strict=False, section=None)
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_telemetry_event_emitted_when_claude_dir_exists(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "telemetry.jsonl").write_text("")
        _write(tmp_path / "spec.md", _good_spec())
        _cmd_lint_spec(tmp_path, "spec.md", strict=False, section=None)
        events = (tmp_path / ".claude" / "telemetry.jsonl").read_text().strip().splitlines()
        assert any('"type": "spec_lint_completed"' in e for e in events)


class TestDecomposeWithLinter:
    def _setup(self, tmp_path: Path, spec_content: str, linter_enabled: bool = True) -> None:
        (tmp_path / ".claude").mkdir()
        _write(tmp_path / "spec.md", spec_content)
        config = {
            "spec": "spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [],
            "validation": {
                "spec_linter": linter_enabled,
                "spec_linter_strict": False,
                "spec_max_words": 5000,
                "spec_min_words": 200,
            },
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

    def test_decompose_aborts_on_blockers(self, tmp_path, capsys):
        self._setup(tmp_path, _broken_spec())
        with patch("superpower_workflow.decomposer.decompose", return_value=[]):
            try:
                _cmd_decompose(tmp_path, force=False)
                raise AssertionError("expected SystemExit")
            except SystemExit as e:
                assert e.code == 1
        out = capsys.readouterr().out
        assert "blocker" in out.lower()

    def test_decompose_force_skips_blockers(self, tmp_path, capsys):
        self._setup(tmp_path, _broken_spec())
        with patch(
            "superpower_workflow.decomposer.decompose",
            return_value=[{"name": "m1", "description": "test"}],
        ):
            import contextlib

            with contextlib.suppress(SystemExit):
                _cmd_decompose(tmp_path, force=True)
        # No abort with --force; milestones were attempted
        out = capsys.readouterr().out
        assert "FAIL" in out  # report still printed
        # Workflow.json should have a milestone
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert config["milestones"]

    def test_decompose_proceeds_when_clean(self, tmp_path):
        self._setup(tmp_path, _good_spec())
        with patch(
            "superpower_workflow.decomposer.decompose",
            return_value=[{"name": "m1", "description": "test"}],
        ):
            _cmd_decompose(tmp_path, force=False)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert config["milestones"][0]["name"] == "m1"

    def test_decompose_skips_linter_when_disabled(self, tmp_path, capsys):
        self._setup(tmp_path, _broken_spec(), linter_enabled=False)
        with patch(
            "superpower_workflow.decomposer.decompose",
            return_value=[{"name": "m1", "description": "test"}],
        ):
            _cmd_decompose(tmp_path, force=False)
        out = capsys.readouterr().out
        # No lint header printed
        assert "Spec lint:" not in out
