from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.plugins.interface import Plugin, PluginVetoError
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import load_state


def _config(tmp_path: Path, **overrides) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "convergence": {
            "max_iterations": 1,
            "min_gaps_for_substantial": 20,
            "persistent_gap_downgrade_after": 3,
        },
        "verify_commands": {"test": "echo ok", "lint": None, "format": None},
        "git_strategy": "main",
        "telemetry": {"enabled": False},
        "milestones": [{"name": "m1"}],
        "plugins": {"enabled": True, "blocked": []},
        "docs": {
            "readme": {"enabled": False, "template": None, "sections": []},
            "changelog": {"enabled": False},
            "api": {"tool": "sphinx", "output_dir": "docs/api"},
            "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
        },
    }
    config.update(overrides)
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    (tmp_path / "spec.md").write_text("# Spec")


def _ok_result() -> ClaudeResult:
    return ClaudeResult(text="done", is_error=False, cost_usd=1.0)


def _smart_subprocess(cmd, **kwargs):
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    if "git" in cmd_str and "rev-parse" in cmd_str:
        return CompletedProcess(args=cmd, returncode=0, stdout="abc1234", stderr="")
    if "git" in cmd_str and ("tag" in cmd_str or "push" in cmd_str):
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    if "echo" in cmd_str:
        return CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class TestOrchestratorPluginHooks:
    def test_loads_plugins_on_init(self, tmp_path: Path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]) as mock_load,
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            Orchestrator(tmp_path)
        mock_load.assert_called_once()

    def test_calls_pre_phase_for_each_phase(self, tmp_path: Path):
        _config(tmp_path)
        mock_plugin = MagicMock(spec=Plugin)
        mock_plugin.name = "test"
        mock_plugin.version = "1.0"
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[mock_plugin]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        pre_phase_calls = mock_plugin.pre_phase.call_args_list
        phases_seen = [c.args[0] for c in pre_phase_calls]
        assert "plan" in phases_seen
        assert "implement" in phases_seen
        assert len(phases_seen) >= 3

    def test_calls_post_milestone(self, tmp_path: Path):
        _config(tmp_path)
        mock_plugin = MagicMock(spec=Plugin)
        mock_plugin.name = "test"
        mock_plugin.version = "1.0"
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[mock_plugin]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_plugin.post_milestone.assert_called()

    def test_veto_stops_phase(self, tmp_path: Path):
        _config(tmp_path)
        mock_plugin = MagicMock(spec=Plugin)
        mock_plugin.name = "veto"
        mock_plugin.version = "1.0"
        mock_plugin.pre_phase.side_effect = PluginVetoError("blocked")
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[mock_plugin]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.failed

    def test_disabled_plugins_not_loaded(self, tmp_path: Path):
        _config(tmp_path, plugins={"enabled": False, "blocked": []})
        with (
            patch("superpower_workflow.orchestrator.load_plugins") as mock_load,
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            Orchestrator(tmp_path)
        mock_load.assert_not_called()

    def test_blocked_plugins_passed_to_loader(self, tmp_path: Path):
        _config(tmp_path, plugins={"enabled": True, "blocked": ["bad-plugin"]})
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]) as mock_load,
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            Orchestrator(tmp_path)
        mock_load.assert_called_once_with(blocked=["bad-plugin"])


class TestOrchestratorDocsHooks:
    def test_generates_changelog_when_enabled(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": True},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch(
                "superpower_workflow.orchestrator.generate_changelog",
                return_value="# Changelog",
            ) as mock_cl,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_cl.assert_called_once()

    def test_generates_diagram_when_enabled(self, tmp_path: Path):
        src = tmp_path / "src" / "mypackage"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": False},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": True, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch(
                "superpower_workflow.orchestrator.generate_mermaid",
                return_value="graph TD",
            ) as mock_mm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_mm.assert_called_once()

    def test_skips_docs_when_all_disabled(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": False},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.generate_changelog") as mock_cl,
            patch("superpower_workflow.orchestrator.generate_mermaid") as mock_mm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_cl.assert_not_called()
        mock_mm.assert_not_called()

    def test_generates_readme_when_enabled(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": True, "template": None, "sections": ["overview"]},
                "changelog": {"enabled": False},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch(
                "superpower_workflow.orchestrator.generate_readme",
                return_value="# README",
            ) as mock_rm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_rm.assert_called_once()

    def test_docs_failure_does_not_fail_milestone(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": True},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch(
                "superpower_workflow.orchestrator.generate_changelog",
                side_effect=RuntimeError("git broke"),
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
