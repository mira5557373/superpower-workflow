from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.bootstrap import bootstrap, detect_project_type
from superpower_workflow.docs.changelog import generate_changelog
from superpower_workflow.docs.diagrams import generate_mermaid
from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.plugins.interface import Plugin
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import load_state
from superpower_workflow.upgrade import detect_package_manager, list_outdated


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
            "changelog": {"enabled": True},
            "api": {"tool": "sphinx", "output_dir": "docs/api"},
            "diagrams": {"enabled": True, "output": "docs/architecture.mmd"},
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
    if "git" in cmd_str and "log" in cmd_str and "--format" in cmd_str:
        return CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="abc1234 feat: add login\ndef5678 fix: patch bug\n",
            stderr="",
        )
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class TestBootstrapThenRun:
    def test_bootstrap_creates_config_orchestrator_can_load(self, tmp_path: Path):
        bootstrap(tmp_path, project_type="python")
        config_path = tmp_path / ".claude" / "workflow.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "milestones" in config
        assert "docs" in config

    def test_bootstrap_auto_detect_and_scaffold(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        assert detect_project_type(tmp_path) == "python"
        created = bootstrap(tmp_path)
        assert len(created) > 0
        assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "docs" / "index.md").exists()


class TestDocsGeneration:
    def test_changelog_from_real_format(self):
        log = CompletedProcess(
            args=[],
            returncode=0,
            stdout="abc1234 feat: add feature\ndef5678 fix: bugfix\nghi9012 chore: cleanup\n",
            stderr="",
        )
        with patch("superpower_workflow.docs.changelog.subprocess.run", return_value=log):
            result = generate_changelog()
        assert "### Features" in result
        assert "### Bug Fixes" in result
        assert "### Chores" in result

    def test_mermaid_from_real_files(self, tmp_path: Path):
        pkg = tmp_path / "src" / "myapp"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("from myapp.core import run\n")
        (pkg / "core.py").write_text("from myapp.utils import helper\n")
        (pkg / "utils.py").write_text("")
        result = generate_mermaid(pkg, project_prefix="myapp")
        assert "graph TD" in result
        assert "myapp" in result
        assert "-->" in result


class TestPluginLifecycle:
    def test_plugin_hooks_called_during_run(self, tmp_path: Path):
        _config(tmp_path)
        tracker: list[str] = []

        class TrackingPlugin(Plugin):
            name = "tracker"
            version = "1.0"

            def pre_phase(self, phase, milestone):
                tracker.append(f"pre:{phase}")

            def post_phase(self, phase, milestone, result):
                tracker.append(f"post:{phase}")

            def post_milestone(self, milestone, cost):
                tracker.append(f"done:{milestone['name']}")

        with (
            patch(
                "superpower_workflow.orchestrator.load_plugins",
                return_value=[TrackingPlugin()],
            ),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.generate_changelog", return_value=""),
            patch("superpower_workflow.orchestrator.generate_mermaid", return_value="graph TD"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert any("pre:" in t for t in tracker)
        assert any("post:" in t for t in tracker)
        assert "done:m1" in tracker

    def test_multiple_plugins_all_called(self, tmp_path: Path):
        _config(tmp_path)

        class PluginA(Plugin):
            name = "a"
            version = "1.0"
            called = False

            def post_milestone(self, milestone, cost):
                PluginA.called = True

        class PluginB(Plugin):
            name = "b"
            version = "2.0"
            called = False

            def post_milestone(self, milestone, cost):
                PluginB.called = True

        PluginA.called = False
        PluginB.called = False

        with (
            patch(
                "superpower_workflow.orchestrator.load_plugins",
                return_value=[PluginA(), PluginB()],
            ),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.generate_changelog", return_value=""),
            patch("superpower_workflow.orchestrator.generate_mermaid", return_value="graph TD"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert PluginA.called
        assert PluginB.called


class TestUpgradeIntegration:
    def test_detect_and_list_outdated(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        assert detect_package_manager(tmp_path) == "pip"
        pip_output = json.dumps(
            [
                {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"},
            ]
        )
        result = CompletedProcess(args=[], returncode=0, stdout=pip_output, stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert len(deps) == 1
        assert deps[0].name == "requests"

    def test_upgrade_no_deps_file(self, tmp_path: Path):
        assert detect_package_manager(tmp_path) == "unknown"


class TestDocsAndPluginsTogether:
    def test_full_pipeline_with_docs_and_plugins(self, tmp_path: Path):
        src = tmp_path / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("from myapp import __init__\n")
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": True},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": True, "output": "docs/architecture.mmd"},
            },
            plugins={"enabled": True, "blocked": []},
        )

        class CountPlugin(Plugin):
            name = "counter"
            version = "1.0"
            milestone_count = 0

            def post_milestone(self, milestone, cost):
                CountPlugin.milestone_count += 1

        CountPlugin.milestone_count = 0

        with (
            patch(
                "superpower_workflow.orchestrator.load_plugins",
                return_value=[CountPlugin()],
            ),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch(
                "superpower_workflow.orchestrator.generate_changelog",
                return_value="# Changes",
            ) as mock_cl,
            patch(
                "superpower_workflow.orchestrator.generate_mermaid",
                return_value="graph TD",
            ) as mock_mm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
        assert CountPlugin.milestone_count == 1
        mock_cl.assert_called()
        mock_mm.assert_called()
