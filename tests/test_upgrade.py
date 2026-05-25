from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.upgrade import (
    OutdatedDep,
    detect_package_manager,
    is_major_bump,
    list_outdated,
    perform_upgrade,
)


class TestDetectPackageManager:
    def test_detects_pip(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        assert detect_package_manager(tmp_path) == "pip"

    def test_detects_npm(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "app"}')
        assert detect_package_manager(tmp_path) == "npm"

    def test_detects_requirements(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        assert detect_package_manager(tmp_path) == "pip"

    def test_unknown(self, tmp_path: Path):
        assert detect_package_manager(tmp_path) == "unknown"


class TestIsMajorBump:
    def test_major_bump(self):
        assert is_major_bump("1.2.3", "2.0.0") is True

    def test_minor_bump(self):
        assert is_major_bump("1.2.3", "1.3.0") is False

    def test_patch_bump(self):
        assert is_major_bump("1.2.3", "1.2.4") is False

    def test_same_version(self):
        assert is_major_bump("1.0.0", "1.0.0") is False

    def test_malformed_version(self):
        assert is_major_bump("abc", "def") is False


class TestListOutdatedPip:
    def test_parses_pip_json(self):
        pip_output = json.dumps(
            [
                {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"},
                {"name": "flask", "version": "2.3.0", "latest_version": "3.0.0"},
            ]
        )
        result = CompletedProcess(args=[], returncode=0, stdout=pip_output, stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert len(deps) == 2
        assert deps[0].name == "requests"
        assert deps[0].is_breaking is False
        assert deps[1].name == "flask"
        assert deps[1].is_breaking is True

    def test_empty_output(self):
        result = CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert deps == []

    def test_pip_failure(self):
        result = CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert deps == []


class TestListOutdatedNpm:
    def test_parses_npm_json(self):
        npm_output = json.dumps(
            {
                "lodash": {"current": "4.17.0", "latest": "4.17.21"},
                "react": {"current": "17.0.2", "latest": "18.2.0"},
            }
        )
        result = CompletedProcess(args=[], returncode=1, stdout=npm_output, stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("npm")
        assert len(deps) == 2
        breaking = [d for d in deps if d.is_breaking]
        assert len(breaking) == 1
        assert breaking[0].name == "react"

    def test_unknown_manager_returns_empty(self):
        deps = list_outdated("unknown")
        assert deps == []


class TestPerformUpgrade:
    def test_creates_branch_for_breaking_dep(self):
        dep = OutdatedDep(name="flask", current="2.3.0", latest="3.0.0", is_breaking=True)
        with patch("superpower_workflow.upgrade.subprocess.run") as mock:
            mock.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            result = perform_upgrade(dep, cwd=".")
        branch_calls = [c for c in mock.call_args_list if "checkout" in str(c)]
        assert len(branch_calls) >= 1
        assert result.branch == "upgrade/flask-2.3.0-to-3.0.0"

    def test_non_breaking_upgrade_bumps_in_place(self):
        dep = OutdatedDep(name="requests", current="2.28.0", latest="2.31.0", is_breaking=False)
        with patch("superpower_workflow.upgrade.subprocess.run") as mock:
            mock.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            result = perform_upgrade(dep, cwd=".")
        assert result.branch is None
        assert result.upgraded is True

    def test_pip_install_failure(self):
        dep = OutdatedDep(name="broken", current="1.0", latest="2.0", is_breaking=False)
        with patch("superpower_workflow.upgrade.subprocess.run") as mock:
            mock.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            result = perform_upgrade(dep, cwd=".")
        assert result.upgraded is False
