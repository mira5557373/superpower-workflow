"""T1.6.2 / G1.6.7 — assert the gitignore template includes every entry the
real-soak experience told us is required. New entries land here before
shipping.
"""

from __future__ import annotations

import subprocess

import pytest

from superpower_workflow.cli import (
    PYTHON_GITIGNORE_ENTRIES,
    SW_GITIGNORE_ENTRIES,
    _cmd_init,
    _cmd_migrate_gitignore,
)

REQUIRED_PYTHON_ENTRIES = {
    ".venv/",
    "__pycache__/",
    "*.pyc",
    "dist/",
    "build/",
    "*.egg-info/",
    # added in v1.1.6 after multiple soak failures
    ".coverage",
    ".coverage.*",
    "htmlcov/",
    ".tox/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytest_cache/",
}

REQUIRED_SW_ENTRIES = {
    ".claude/workflow-state.json",
    ".claude/.workflow-phase.json",
    ".claude/.gap-report.json",
    ".claude/.gap-report.raw.json",
    ".claude/.workflow.lock",
    ".claude/.workflow.lock.json",
    ".claude/.workflow.lock.filelock",
    ".claude/workflow-complete.json",
    ".claude/workflow-*.log",
    ".claude/telemetry.jsonl",
    ".claude/audit-trail.jsonl",
    ".worktrees/",
    ".claude/.gap-validation.json",
    ".claude/.spec-compliance.json",
    ".claude/.feature-verification.json",
    ".claude/.quality-gate-results.json",
    ".claude/reports/",
}


class TestGitignoreTemplate:
    def test_python_template_includes_required_entries(self):
        missing = REQUIRED_PYTHON_ENTRIES - set(PYTHON_GITIGNORE_ENTRIES)
        assert not missing, f"PYTHON_GITIGNORE_ENTRIES missing: {missing}"

    def test_sw_template_includes_required_entries(self):
        missing = REQUIRED_SW_ENTRIES - set(SW_GITIGNORE_ENTRIES)
        assert not missing, f"SW_GITIGNORE_ENTRIES missing: {missing}"


class TestInitWritesGitignore:
    @pytest.fixture
    def fresh_project(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        return tmp_path

    def test_init_creates_gitignore_with_required_entries(self, fresh_project):
        _cmd_init(fresh_project)
        content = (fresh_project / ".gitignore").read_text()
        for entry in REQUIRED_PYTHON_ENTRIES | REQUIRED_SW_ENTRIES:
            assert entry in content, f"missing {entry} in fresh-init .gitignore"


class TestMigrateGitignore:
    @pytest.fixture
    def fresh_project(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        return tmp_path

    def test_migrate_creates_gitignore_when_absent(self, fresh_project):
        gi = fresh_project / ".gitignore"
        assert not gi.exists()
        _cmd_migrate_gitignore(fresh_project)
        assert gi.exists()
        content = gi.read_text()
        # All required entries land
        for entry in REQUIRED_PYTHON_ENTRIES | REQUIRED_SW_ENTRIES:
            assert entry in content

    def test_migrate_idempotent(self, fresh_project):
        """Running twice produces the same file content."""
        _cmd_migrate_gitignore(fresh_project)
        first = (fresh_project / ".gitignore").read_text()
        _cmd_migrate_gitignore(fresh_project)
        second = (fresh_project / ".gitignore").read_text()
        assert first == second

    def test_migrate_appends_only_missing(self, fresh_project):
        """Pre-existing entries don't get duplicated."""
        gi = fresh_project / ".gitignore"
        gi.write_text("# existing\n.venv/\n*.pyc\n")
        _cmd_migrate_gitignore(fresh_project)
        content = gi.read_text()
        # Pre-existing entries shouldn't double up
        assert content.count(".venv/\n") == 1
        assert content.count("*.pyc\n") == 1
        # New entries land
        assert ".coverage" in content
        assert ".ruff_cache/" in content

    def test_migrate_preserves_existing_content(self, fresh_project):
        """User's own gitignore entries above sw additions stay intact."""
        gi = fresh_project / ".gitignore"
        gi.write_text("# my project rules\nsecrets.env\nnotes.md\n")
        _cmd_migrate_gitignore(fresh_project)
        content = gi.read_text()
        assert "secrets.env" in content
        assert "notes.md" in content
        assert "# my project rules" in content
