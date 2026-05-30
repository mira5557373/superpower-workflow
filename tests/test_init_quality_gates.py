"""Tests for `sw init --with-quality-gates` (T1.8.2)."""

from __future__ import annotations

import json

from superpower_workflow.cli import _cmd_init


def _read_config(tmp_path):
    return json.loads((tmp_path / ".claude" / "workflow.json").read_text())


class TestInitMinimal:
    def test_minimal_skips_detection(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        _cmd_init(tmp_path, minimal=True)
        config = _read_config(tmp_path)
        # Minimal: legacy null-stub verify_commands
        assert config["verify_commands"] == {"test": None, "lint": None, "format": None}
        assert config["quality_gates"] == {}

    def test_no_flag_detects_but_no_quality_gates(self, tmp_path):
        """Default `sw init` in a Python project: get verify_commands but no QA gates."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        _cmd_init(tmp_path)
        config = _read_config(tmp_path)
        assert "ruff" in config["verify_commands"]["lint"]
        assert config["quality_gates"] == {}


class TestInitWithQualityGates:
    def test_python_project_gets_full_gates(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        _cmd_init(tmp_path, with_quality_gates=True)
        config = _read_config(tmp_path)
        gates = config["quality_gates"]
        assert "bandit" in gates.get("sast", "")
        assert "pip-audit" in gates.get("dep_scan", "")
        assert "radon" in gates.get("complexity", "")
        assert "mypy" in gates.get("type_check", "")

    def test_typescript_project_gets_npm_audit(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text("{}")
        _cmd_init(tmp_path, with_quality_gates=True)
        config = _read_config(tmp_path)
        assert "npm audit" in config["quality_gates"]["dep_scan"]

    def test_rust_project_gets_cargo_audit(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
        _cmd_init(tmp_path, with_quality_gates=True)
        config = _read_config(tmp_path)
        assert "cargo audit" in config["quality_gates"]["dep_scan"]

    def test_empty_project_falls_back_to_legacy(self, tmp_path):
        """No marker files → no detection → empty defaults."""
        _cmd_init(tmp_path, with_quality_gates=True)
        config = _read_config(tmp_path)
        assert config["verify_commands"] == {"test": None, "lint": None, "format": None}
        assert config["quality_gates"] == {}
