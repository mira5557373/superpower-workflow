"""Smoke tests for `sw budget` CLI subcommand (v1.3.20)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from superpower_workflow import cli as cli_module


def _make_event(*, run_id: str, cost: float, ts: datetime) -> str:
    return json.dumps(
        {
            "type": "run_completed",
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": run_id,
            "total_cost_usd": cost,
        }
    )


@pytest.fixture
def project_with_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "workflow.json").write_text(
        json.dumps({"model": "claude-opus-4-7", "max_total_budget_usd": 50.0}),
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


class TestBudgetShow:
    def test_show_no_config(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("budget", "show")
        assert code == 0
        assert "No cost ceilings" in out

    def test_show_json_no_config(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("budget", "show", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["configured"] is False

    def test_show_with_ceiling_and_telemetry(self, project_with_workflow: Path, run_cli) -> None:
        # Inject a ceiling + some history.
        cfg_path = project_with_workflow / ".claude" / "workflow.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["cost_ceilings"] = {"daily": {"usd": 100.0, "mode": "block"}}
        cfg_path.write_text(json.dumps(cfg))
        tel = project_with_workflow / ".claude" / "sw-telemetry.jsonl"
        now = datetime.now(UTC)
        tel.write_text(
            "\n".join(
                _make_event(run_id=f"r{i}", cost=5.0, ts=now - timedelta(hours=i + 1))
                for i in range(5)
            )
            + "\n",
            encoding="utf-8",
        )

        code, out, _ = run_cli("budget", "show", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["configured"] is True
        day = next(w for w in payload["windows"] if w["window"] == "day")
        assert day["current_spend_usd"] == 25.0
        assert day["ceiling_usd"] == 100.0
        assert day["headroom_usd"] == 75.0
        assert day["mode"] == "block"

    def test_show_human_output_table(self, project_with_workflow: Path, run_cli) -> None:
        cfg_path = project_with_workflow / ".claude" / "workflow.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["cost_ceilings"] = {"daily": {"usd": 50.0, "mode": "warn"}}
        cfg_path.write_text(json.dumps(cfg))

        code, out, _ = run_cli("budget", "show")
        assert code == 0
        assert "day" in out
        # Right-aligned column gives padded spaces between $ and the number.
        assert "50.00" in out
        assert "warn" in out

    def test_show_window_filter(self, project_with_workflow: Path, run_cli) -> None:
        cfg_path = project_with_workflow / ".claude" / "workflow.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["cost_ceilings"] = {
            "daily": {"usd": 50.0, "mode": "block"},
            "weekly": {"usd": 200.0, "mode": "block"},
        }
        cfg_path.write_text(json.dumps(cfg))

        code, out, _ = run_cli("budget", "show", "--window", "day", "--json")
        assert code == 0
        payload = json.loads(out)
        assert all(w["window"] == "day" for w in payload["windows"])
        assert len(payload["windows"]) == 1


class TestBudgetSet:
    def test_set_writes_workflow_json(self, project_with_workflow: Path, run_cli) -> None:
        code, _, _ = run_cli("budget", "set", "--daily", "75", "--mode", "block")
        assert code == 0
        cfg = json.loads((project_with_workflow / ".claude" / "workflow.json").read_text())
        assert cfg["cost_ceilings"]["daily"] == {"usd": 75.0, "mode": "block"}

    def test_set_multiple_at_once(self, project_with_workflow: Path, run_cli) -> None:
        code, _, _ = run_cli(
            "budget", "set", "--daily", "50", "--weekly", "200", "--monthly", "500"
        )
        assert code == 0
        cfg = json.loads((project_with_workflow / ".claude" / "workflow.json").read_text())
        assert cfg["cost_ceilings"]["daily"]["usd"] == 50.0
        assert cfg["cost_ceilings"]["weekly"]["usd"] == 200.0
        assert cfg["cost_ceilings"]["monthly"]["usd"] == 500.0

    def test_set_zero_rejected(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("budget", "set", "--daily", "0")
        assert code == 0  # the command itself succeeds; bad value is skipped
        assert "Invalid daily value" in out
        cfg = json.loads((project_with_workflow / ".claude" / "workflow.json").read_text())
        assert "daily" not in cfg.get("cost_ceilings", {})


class TestBudgetReset:
    def test_reset_without_confirm_is_dry_run(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("budget", "reset", "--window", "day")
        assert code == 0
        assert "DRY-RUN" in out

    def test_reset_with_confirm_writes_checkpoint(
        self, project_with_workflow: Path, run_cli
    ) -> None:
        code, out, _ = run_cli("budget", "reset", "--window", "day", "--confirm")
        assert code == 0
        assert "Reset day window" in out
        cfg = json.loads((project_with_workflow / ".claude" / "workflow.json").read_text())
        assert "day" in cfg["cost_ceilings"]["reset_checkpoints"]


class TestRunIgnoreCeiling:
    def test_ignore_ceiling_without_env_or_tty_exits_8(
        self, project_with_workflow: Path, run_cli, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verdict revision #3: bare --ignore-ceiling in non-TTY non-env fails."""
        monkeypatch.delenv("SW_ALLOW_CEILING_BYPASS", raising=False)
        # capsys's stdin is not a tty by default.
        code, _, err = run_cli("run", "--ignore-ceiling", "--dry-run")
        assert code == 8
        assert "SW_ALLOW_CEILING_BYPASS" in err

    def test_ignore_ceiling_tty_but_no_stdin_input_exits_8(
        self,
        project_with_workflow: Path,
        run_cli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """v1.3.21 soak regression: `nohup python -c ...` or similar non-
        interactive launches see sys.stdin.isatty()==True but `input()`
        raises EOFError. Must exit 8 cleanly, not crash with a traceback.
        """
        monkeypatch.delenv("SW_ALLOW_CEILING_BYPASS", raising=False)
        # Force sys.stdin.isatty() to return True (the soak's broken path).
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        # Pretend input() raises EOFError as it would in a piped non-TTY.
        monkeypatch.setattr("builtins.input", lambda _prompt="": (_ for _ in ()).throw(EOFError()))
        code, _, err = run_cli("run", "--ignore-ceiling", "--dry-run")
        assert code == 8
        assert "SW_ALLOW_CEILING_BYPASS" in err

    def test_ignore_ceiling_with_env_authorizes(
        self, project_with_workflow: Path, run_cli, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With env var set, the flag passes auth (no exit 8 from preflight)."""
        from superpower_workflow.budget_ceiling import is_bypass_authorized

        monkeypatch.setenv("SW_ALLOW_CEILING_BYPASS", "1")
        authorized, reason = is_bypass_authorized(
            ignore_flag=True,
            env=dict({"SW_ALLOW_CEILING_BYPASS": "1"}),
        )
        assert authorized
        assert reason == "env_var_set"
