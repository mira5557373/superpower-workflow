"""Tests for project_detect (T1.8.4)."""

from __future__ import annotations

from superpower_workflow.project_detect import (
    detect,
    detect_languages,
    language_supported,
)


class TestDetectLanguages:
    def test_python_via_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        assert detect_languages(tmp_path) == ["python"]

    def test_python_via_setup_py(self, tmp_path):
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")
        assert "python" in detect_languages(tmp_path)

    def test_typescript_via_tsconfig(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text("{}")
        assert "typescript" in detect_languages(tmp_path)

    def test_javascript_via_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert "javascript" in detect_languages(tmp_path)

    def test_rust_via_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
        assert "rust" in detect_languages(tmp_path)

    def test_go_via_gomod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module x\n")
        assert "go" in detect_languages(tmp_path)

    def test_mixed_languages_returns_all(self, tmp_path):
        """G1.8.6: mixed projects (e.g., Python backend + TS frontend) return both."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "package.json").write_text("{}")
        langs = detect_languages(tmp_path)
        assert "python" in langs
        assert "javascript" in langs

    def test_empty_dir_returns_empty(self, tmp_path):
        assert detect_languages(tmp_path) == []


class TestDetectProfile:
    def test_python_profile_has_ruff_and_bandit(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        profile = detect(tmp_path)
        assert profile.primary_language == "python"
        assert "ruff check" in profile.verify_commands["lint"]
        assert "pytest" in profile.verify_commands["test"]
        assert "bandit" in profile.quality_gates["sast"]
        assert "pip-audit" in profile.quality_gates["dep_scan"]
        assert "radon" in profile.quality_gates["complexity"]

    def test_typescript_profile_has_eslint_and_npm_audit(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text("{}")
        profile = detect(tmp_path)
        assert profile.primary_language == "typescript"
        assert "eslint" in profile.verify_commands["lint"]
        assert "npm audit" in profile.quality_gates["dep_scan"]

    def test_rust_profile_has_cargo_audit(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
        profile = detect(tmp_path)
        assert profile.primary_language == "rust"
        assert "cargo audit" in profile.quality_gates["dep_scan"]
        assert "clippy" in profile.verify_commands["lint"]

    def test_go_profile_has_govulncheck(self, tmp_path):
        (tmp_path / "go.mod").write_text("module x\n")
        profile = detect(tmp_path)
        assert profile.primary_language == "go"
        assert "govulncheck" in profile.quality_gates["dep_scan"]

    def test_empty_project_returns_empty_profile(self, tmp_path):
        profile = detect(tmp_path)
        assert profile.languages == []
        assert profile.primary_language == "generic"
        assert profile.verify_commands == {}
        assert profile.quality_gates == {}

    def test_mixed_python_typescript_merges_dep_scans(self, tmp_path):
        """Mixed projects: primary's verify_commands + merged dep_scans."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "package.json").write_text("{}")
        profile = detect(tmp_path)
        assert profile.primary_language == "python"
        # Python's dep_scan wins
        assert "pip-audit" in profile.quality_gates["dep_scan"]


class TestLanguageSupported:
    def test_known_languages(self):
        assert language_supported("python")
        assert language_supported("rust")
        assert language_supported("go")

    def test_unknown_language(self):
        assert not language_supported("brainfuck")
