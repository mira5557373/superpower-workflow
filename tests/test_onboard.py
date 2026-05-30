"""Tests for `sw onboard` wizard (T1.9.5)."""

from __future__ import annotations

import io
import json
import sys

from superpower_workflow.onboard import (
    SIZE_PRESETS,
    OnboardConfig,
    build_workflow_config,
    detect_existing_specs,
    run_onboard,
    write_config,
)


class TestRunOnboardNonInteractive:
    def test_returns_defaults_when_not_interactive(self, tmp_path):
        cfg = run_onboard(tmp_path, interactive=False)
        assert cfg.model == "opus"
        assert cfg.size_preset == "medium"
        assert cfg.enable_gap_curator is True
        assert cfg.enable_spec_linter is True

    def test_detects_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        cfg = run_onboard(tmp_path, interactive=False)
        assert cfg.project_type == "python"


class TestDetectExistingSpecs:
    def test_finds_root_spec(self, tmp_path):
        (tmp_path / "spec.md").write_text("x")
        specs = detect_existing_specs(tmp_path)
        assert len(specs) == 1
        assert specs[0].name == "spec.md"

    def test_finds_docs_supersecs(self, tmp_path):
        sdir = tmp_path / "docs" / "superpowers" / "specs"
        sdir.mkdir(parents=True)
        (sdir / "2026-05-30-feature.md").write_text("x")
        specs = detect_existing_specs(tmp_path)
        assert len(specs) == 1

    def test_dedupes(self, tmp_path):
        (tmp_path / "spec.md").write_text("x")
        sdir = tmp_path / "docs" / "superpowers" / "specs"
        sdir.mkdir(parents=True)
        (sdir / "feature.md").write_text("x")
        specs = detect_existing_specs(tmp_path)
        # 1 root spec + 1 nested spec
        assert len(specs) == 2

    def test_empty_dir_returns_empty(self, tmp_path):
        assert detect_existing_specs(tmp_path) == []


class TestBuildWorkflowConfig:
    def test_size_preset_drives_budgets(self, tmp_path):
        for preset in SIZE_PRESETS:
            cfg = OnboardConfig(spec_path="s.md", size_preset=preset)
            wf = build_workflow_config(tmp_path, cfg)
            assert wf["budgets"]["plan"] == SIZE_PRESETS[preset]["plan"]
            assert wf["max_total_budget_usd"] == SIZE_PRESETS[preset]["max_total_budget_usd"]

    def test_validation_toggles_honored(self, tmp_path):
        cfg = OnboardConfig(
            enable_gap_curator=False,
            enable_strict_mode=True,
            enable_spec_linter=False,
        )
        wf = build_workflow_config(tmp_path, cfg)
        assert wf["validation"]["gap_curator"] is False
        assert wf["validation"]["strict_mode"] is True
        assert wf["validation"]["spec_linter"] is False

    def test_quality_gates_populated_when_enabled(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        cfg = OnboardConfig(enable_quality_gates=True)
        wf = build_workflow_config(tmp_path, cfg)
        assert "bandit" in wf["quality_gates"]["sast"]

    def test_quality_gates_empty_when_disabled(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        cfg = OnboardConfig(enable_quality_gates=False)
        wf = build_workflow_config(tmp_path, cfg)
        assert wf["quality_gates"] == {}


class TestWriteConfig:
    def test_writes_atomically(self, tmp_path):
        config = {"spec": "x.md", "milestones": []}
        path = write_config(tmp_path, config)
        assert path.exists()
        assert json.loads(path.read_text())["spec"] == "x.md"


class TestInteractiveSmoke:
    def test_interactive_with_canned_stdin_writes_config(self, tmp_path, monkeypatch):
        """Drive the wizard end-to-end with canned input."""
        (tmp_path / "spec.md").write_text("dummy")
        responses = (
            "\n".join(
                [
                    "spec.md",  # spec path (default would work too)
                    "sonnet",  # model
                    "small",  # size
                    "y",  # gap_curator
                    "n",  # strict_mode
                    "y",  # spec_linter
                    "y",  # quality_gates
                    "n",  # ci_integration
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(responses))
        cfg = run_onboard(tmp_path, interactive=True)
        assert cfg.spec_path == "spec.md"
        assert cfg.model == "sonnet"
        assert cfg.size_preset == "small"
        assert cfg.enable_gap_curator is True
        assert cfg.enable_strict_mode is False
