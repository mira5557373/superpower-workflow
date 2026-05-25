from __future__ import annotations

import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from superpower_workflow.integrations.github import (
    fetch_issue,
    issue_to_milestone,
    parse_issue_ref,
)


class TestParseIssueRef:
    def test_bare_number(self):
        repo, number = parse_issue_ref("42", default_repo="owner/repo")
        assert repo == "owner/repo"
        assert number == 42

    def test_hash_prefix(self):
        repo, number = parse_issue_ref("#42", default_repo="owner/repo")
        assert repo == "owner/repo"
        assert number == 42

    def test_full_ref(self):
        repo, number = parse_issue_ref("myorg/myrepo#99")
        assert repo == "myorg/myrepo"
        assert number == 99

    def test_no_default_repo_bare_number(self):
        repo, number = parse_issue_ref("42")
        assert repo == ""
        assert number == 42

    def test_invalid_number_raises(self):
        with pytest.raises(ValueError):
            parse_issue_ref("not-a-number")


class TestFetchIssue:
    def test_fetches_via_gh_cli(self):
        issue_json = {
            "title": "Fix login",
            "body": "Login is broken for SSO users",
            "labels": [{"name": "bug"}],
            "assignees": [{"login": "dev1"}],
        }
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(issue_json), stderr=""
            )
            result = fetch_issue("42", default_repo="owner/repo")
        assert result["title"] == "Fix login"
        assert result["body"] == "Login is broken for SSO users"
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "42" in cmd[cmd.index("view") + 1]

    def test_includes_repo_flag_when_provided(self):
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"title":"t","body":"b","labels":[],"assignees":[]}',
                stderr="",
            )
            fetch_issue("owner/repo#42")
        cmd = mock_run.call_args[0][0]
        assert "--repo" in cmd
        assert "owner/repo" in cmd

    def test_raises_on_gh_failure(self):
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not found"
            )
            with pytest.raises(RuntimeError, match="fetch issue"):
                fetch_issue("999", default_repo="owner/repo")


class TestIssueToMilestone:
    def test_basic_conversion(self):
        issue = {
            "title": "Add dark mode",
            "body": "Support dark mode in the settings page",
            "labels": [{"name": "feature"}],
            "assignees": [],
        }
        ms = issue_to_milestone(issue)
        assert ms["name"] == "add-dark-mode"
        assert ms["description"] == "Add dark mode"
        assert ms["spec_sections"] == "Support dark mode in the settings page"
        assert ms["depends_on"] == []

    def test_label_map(self):
        issue = {
            "title": "Fix crash",
            "body": "App crashes on startup",
            "labels": [{"name": "bug"}],
            "assignees": [],
        }
        ms = issue_to_milestone(issue, label_map={"bug": "fix", "feature": "feature"})
        assert ms["type"] == "fix"

    def test_no_matching_label(self):
        issue = {
            "title": "Something",
            "body": "Details",
            "labels": [{"name": "priority-high"}],
            "assignees": [],
        }
        ms = issue_to_milestone(issue, label_map={"bug": "fix"})
        assert "type" not in ms or ms.get("type") == ""

    def test_long_title_truncated(self):
        issue = {
            "title": "A" * 100,
            "body": "details",
            "labels": [],
            "assignees": [],
        }
        ms = issue_to_milestone(issue)
        assert len(ms["name"]) <= 50

    def test_special_chars_slugified(self):
        issue = {
            "title": "Fix: login & SSO [urgent]",
            "body": "details",
            "labels": [],
            "assignees": [],
        }
        ms = issue_to_milestone(issue)
        assert ms["name"] == "fix-login-sso-urgent"
