"""Tests for doctor pre-flight health checks module."""

import json
from unittest.mock import patch

import pytest

from superpower_workflow.doctor import run_checks


@pytest.fixture
def tmp_project_root(tmp_path):
    """Create a temporary project root with .claude directory."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    return tmp_path


class TestMissingConfigFails:
    """Test that missing workflow.json results in failure."""

    def test_missing_config_fails(self, tmp_project_root):
        """run_checks returns CheckResult with ok=False when workflow.json missing."""
        with patch("superpower_workflow.doctor.shutil.which", return_value="claude"):
            results = run_checks(tmp_project_root)

        # Find the config check result
        config_check = [r for r in results if "workflow.json" in r.message][0]
        assert config_check.ok is False
        assert "workflow.json" in config_check.message

    def test_missing_config_message_suggests_init(self, tmp_project_root):
        """Missing config message mentions sw init."""
        with patch("superpower_workflow.doctor.shutil.which", return_value="claude"):
            results = run_checks(tmp_project_root)

        config_check = [r for r in results if "workflow.json" in r.message][0]
        assert "sw init" in config_check.message


class TestValidConfigPasses:
    """Test that valid workflow.json passes."""

    def test_valid_config_passes(self, tmp_project_root):
        """run_checks returns ok=True for valid workflow.json."""
        # Create valid workflow.json
        config = {
            "schema_version": 1,
            "spec": "spec.md",
            "milestones": [],
        }
        config_path = tmp_project_root / ".claude" / "workflow.json"
        config_path.write_text(json.dumps(config))

        with patch("superpower_workflow.doctor.shutil.which", return_value="claude"):
            results = run_checks(tmp_project_root)

        config_check = [r for r in results if "workflow.json" in r.message][0]
        assert config_check.ok is True
        assert "valid" in config_check.message

    def test_config_missing_schema_version_fails(self, tmp_project_root):
        """Config without schema_version fails."""
        config = {
            "spec": "spec.md",
            "milestones": [],
        }
        config_path = tmp_project_root / ".claude" / "workflow.json"
        config_path.write_text(json.dumps(config))

        with patch("superpower_workflow.doctor.shutil.which", return_value="claude"):
            results = run_checks(tmp_project_root)

        config_check = [r for r in results if "workflow.json" in r.message][0]
        assert config_check.ok is False
        assert "required fields" in config_check.message

    def test_config_missing_spec_fails(self, tmp_project_root):
        """Config without spec fails."""
        config = {
            "schema_version": 1,
            "milestones": [],
        }
        config_path = tmp_project_root / ".claude" / "workflow.json"
        config_path.write_text(json.dumps(config))

        with patch("superpower_workflow.doctor.shutil.which", return_value="claude"):
            results = run_checks(tmp_project_root)

        config_check = [r for r in results if "workflow.json" in r.message][0]
        assert config_check.ok is False
        assert "required fields" in config_check.message

    def test_invalid_json_fails(self, tmp_project_root):
        """Invalid JSON in workflow.json fails."""
        config_path = tmp_project_root / ".claude" / "workflow.json"
        config_path.write_text("{ invalid json }")

        with patch("superpower_workflow.doctor.shutil.which", return_value="claude"):
            results = run_checks(tmp_project_root)

        config_check = [r for r in results if "workflow.json" in r.message][0]
        assert config_check.ok is False
        assert "not valid JSON" in config_check.message


class TestClaudeNotInstalledFails:
    """Test that missing Claude Code installation fails."""

    def test_claude_not_installed_fails(self, tmp_project_root):
        """run_checks returns ok=False when Claude Code not installed."""
        config = {
            "schema_version": 1,
            "spec": "spec.md",
            "milestones": [],
        }
        config_path = tmp_project_root / ".claude" / "workflow.json"
        config_path.write_text(json.dumps(config))

        with patch("superpower_workflow.doctor.shutil.which", return_value=None):
            results = run_checks(tmp_project_root)

        claude_check = [r for r in results if "Claude Code" in r.message][0]
        assert claude_check.ok is False

    def test_claude_check_is_first(self, tmp_project_root):
        """Claude Code check is the first result."""
        config = {
            "schema_version": 1,
            "spec": "spec.md",
            "milestones": [],
        }
        config_path = tmp_project_root / ".claude" / "workflow.json"
        config_path.write_text(json.dumps(config))

        with patch("superpower_workflow.doctor.shutil.which", return_value="claude"):
            results = run_checks(tmp_project_root)

        assert "Claude Code" in results[0].message
