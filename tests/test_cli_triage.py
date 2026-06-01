"""CLI surface tests for `sw triage` (v1.3.21)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from superpower_workflow import cli as cli_module


@pytest.fixture
def project_with_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "workflow.json").write_text(
        json.dumps({"model": "claude-opus-4-7"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def run_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[..., tuple[int, str, str]]:
    def _run(*args: str) -> tuple[int, str, str]:
        monkeypatch.setattr(sys, "argv", ["sw", *args])
        code = 0
        try:
            cli_module.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def _seed_failure_telemetry(project: Path, *, milestone: str = "M1") -> Path:
    """Write a minimal telemetry.jsonl that triggers QUALITY_GATE_FAIL."""
    tel = project / ".claude" / "sw-telemetry.jsonl"
    events = [
        {
            "type": "milestone_started",
            "run_id": "r1",
            "milestone": milestone,
            "index": 0,
        },
        {
            "type": "quality_gate_result",
            "run_id": "r1",
            "milestone": milestone,
            "gate": "lint",
            "checkpoint": "QG2",
            "passed": False,
        },
        {
            "type": "milestone_failed",
            "run_id": "r1",
            "milestone": milestone,
            "phase": "review",
            "reason": "quality gate failed",
        },
    ]
    tel.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return tel


class TestTriageNoTelemetry:
    def test_missing_telemetry_exits_2(self, project_with_workflow: Path, run_cli) -> None:
        code, _, _ = run_cli("triage")
        assert code == 2

    def test_missing_telemetry_json_returns_empty(
        self, project_with_workflow: Path, run_cli
    ) -> None:
        code, out, _ = run_cli("triage", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["failures"] == []


class TestTriageWithTelemetry:
    def test_default_lists_failures(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failure_telemetry(project_with_workflow)
        code, out, _ = run_cli("triage")
        assert code == 0
        assert "quality_gate_fail" in out
        assert "1 failure" in out

    def test_json_output_schema(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failure_telemetry(project_with_workflow)
        code, out, _ = run_cli("triage", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["triage_version"] == 1
        assert len(payload["failures"]) == 1
        f = payload["failures"][0]
        assert f["primary_class"] == "quality_gate_fail"
        assert f["confidence"] == 1.0
        assert f["milestone"] == "M1"
        assert isinstance(f["evidence"], list)
        assert len(f["evidence"]) >= 1
        assert payload["summary"]["total_failures"] == 1
        assert payload["summary"]["unknown_count"] == 0

    def test_milestone_filter_match(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failure_telemetry(project_with_workflow, milestone="M-foo")
        code, out, _ = run_cli("triage", "--milestone", "M-foo")
        assert code == 0
        assert "M-foo" in out
        assert "Evidence:" in out  # deep view triggered
        assert "Recommendation:" in out

    def test_milestone_filter_no_match_exit_3(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failure_telemetry(project_with_workflow, milestone="M1")
        code, _, _ = run_cli("triage", "--milestone", "M-missing")
        assert code == 3


class TestTriageConfig:
    def test_triage_disabled_in_config(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failure_telemetry(project_with_workflow)
        cfg_path = project_with_workflow / ".claude" / "workflow.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["triage"] = {"enabled": False}
        cfg_path.write_text(json.dumps(cfg))

        code, out, _ = run_cli("triage")
        assert code == 0
        assert "triage disabled" in out
        assert "workflow.json" in out

    def test_triage_env_kill_switch(
        self, project_with_workflow: Path, run_cli, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_failure_telemetry(project_with_workflow)
        monkeypatch.setenv("SW_TRIAGE_OFF", "1")
        code, out, _ = run_cli("triage")
        assert code == 0
        assert "triage disabled" in out


class TestTriageDeterminism:
    def test_two_invocations_identical_json(self, project_with_workflow: Path, run_cli) -> None:
        """Same telemetry → byte-identical JSON output. Critical invariant."""
        _seed_failure_telemetry(project_with_workflow)
        code1, out1, _ = run_cli("triage", "--json")
        code2, out2, _ = run_cli("triage", "--json")
        assert code1 == 0
        assert code2 == 0
        assert out1 == out2
