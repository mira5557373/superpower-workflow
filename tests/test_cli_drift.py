"""Smoke tests for `sw drift` CLI subcommand (v1.3.19)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from superpower_workflow import cli as cli_module


@pytest.fixture
def project_with_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project dir with .claude/workflow.json (no telemetry yet)."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "workflow.json").write_text(
        json.dumps(
            {
                "model": "claude-opus-4-7",
                "drift_detection": {"enabled": True, "baseline_floor": 15},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def run_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[..., tuple[int, str, str]]:
    """Call `cli.main()` with given argv; return (exit_code, stdout, stderr)."""

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


class TestDriftCli:
    def test_drift_no_telemetry_yet(self, project_with_workflow: Path, run_cli) -> None:
        code, out, err = run_cli("drift")
        assert code == 0, err
        assert "drift" in (out + err).lower() or "baseline" in (out + err).lower()

    def test_drift_json_no_telemetry(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("drift", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["rows"] == []
        assert payload["baseline_floor"] == 15
        assert payload["model"] == "claude-opus-4-7"

    def test_drift_with_telemetry(self, project_with_workflow: Path, run_cli) -> None:
        telemetry = project_with_workflow / ".claude" / "sw-telemetry.jsonl"
        events = [
            {
                "type": "phase_completed",
                "phase": "implement",
                "cost_usd": 2.0 + i * 0.1,
                "duration_ms": 60_000.0,
                "cache_hit_rate": 0.5,
            }
            for i in range(20)
        ]
        telemetry.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

        code, out, _ = run_cli("drift", "--json")
        assert code == 0
        payload = json.loads(out)
        assert len(payload["rows"]) >= 1
        metrics = {r["metric"] for r in payload["rows"]}
        assert "cost_usd" in metrics

    def test_drift_metric_filter(self, project_with_workflow: Path, run_cli) -> None:
        telemetry = project_with_workflow / ".claude" / "sw-telemetry.jsonl"
        events = [
            {
                "type": "phase_completed",
                "phase": "implement",
                "cost_usd": 2.0 + i * 0.1,
                "duration_ms": 60_000.0,
                "cache_hit_rate": 0.5,
            }
            for i in range(20)
        ]
        telemetry.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

        code, out, _ = run_cli("drift", "--json", "--metric", "cost_usd")
        assert code == 0
        payload = json.loads(out)
        assert all(r["metric"] == "cost_usd" for r in payload["rows"])

    def test_drift_no_workflow_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_cli
    ) -> None:
        (tmp_path / ".claude").mkdir()
        monkeypatch.chdir(tmp_path)
        code, out, _ = run_cli("drift")
        assert code == 0
        assert "workflow.json" in out
