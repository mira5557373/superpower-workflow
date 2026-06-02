"""CLI tests for `sw estimate` banded output (v1.3.24)."""

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
    cfg = {
        "spec": "spec.md",
        "model": "claude-haiku-4-5",
        "max_total_budget_usd": 20.0,
        "budgets": {"plan": 1.5, "implement": 5.0, "review": 3.0, "push": 0.5},
        "milestones": [
            {"name": "M1", "depends_on": []},
            {"name": "M2", "depends_on": []},
        ],
    }
    (claude_dir / "workflow.json").write_text(json.dumps(cfg), encoding="utf-8")
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


class TestEstimateBanded:
    def test_default_cold_start(self, project_with_workflow: Path, run_cli) -> None:
        """No telemetry → cold_start tier, default-table prior."""
        code, out, _ = run_cli("estimate")
        assert code == 0
        assert "tier=cold_start" in out
        assert "haiku-4-5" in out
        assert "p10" in out and "p90" in out

    def test_json_schema_snapshot(self, project_with_workflow: Path, run_cli) -> None:
        """JSON output schema locked: schema_version, model_id, band, tier."""
        code, out, _ = run_cli("estimate", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["schema_version"] == 1
        assert payload["model_id"] == "haiku-4-5"
        assert "p10_usd" in payload["band"]
        assert "p50_usd" in payload["band"]
        assert "p90_usd" in payload["band"]
        assert payload["tier"] == "cold_start"
        assert payload["samples_used"] == 0
        assert payload["calibration_source"] == "default_table"

    def test_legacy_flag_falls_back(self, project_with_workflow: Path, run_cli) -> None:
        """--legacy → v1.3.23 single-pair output, NO banded fields."""
        code, out, _ = run_cli("estimate", "--legacy")
        assert code == 0
        assert "Cost:" in out
        assert "legacy" in out
        assert "tier=" not in out  # no banded label

    def test_calibration_subview(self, project_with_workflow: Path, run_cli) -> None:
        """--calibration prints a per-model breakdown table."""
        code, out, _ = run_cli("estimate", "--calibration")
        assert code == 0
        assert "Model" in out
        assert "haiku-4-5" in out
        # Should also show the cold_start label.
        assert "cold_start" in out

    def test_disable_env_var_falls_back(
        self,
        project_with_workflow: Path,
        run_cli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SW_CALIBRATION_DISABLE=1 → estimate_banded returns legacy-shaped dict."""
        monkeypatch.setenv("SW_CALIBRATION_DISABLE", "1")
        code, out, _ = run_cli("estimate", "--json")
        assert code == 0
        payload = json.loads(out)
        # tier reflects the disabled state via 'legacy' source.
        assert payload["tier"] == "legacy"
