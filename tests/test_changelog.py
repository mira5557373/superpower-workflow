from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.docs.changelog import (
    generate_changelog,
    parse_commits,
    render_changelog,
)


def _git_log_output(lines: list[str]) -> CompletedProcess:
    stdout = "\n".join(lines)
    return CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class TestParseCommits:
    def test_groups_by_prefix(self):
        lines = [
            "abc1234 feat: add login page",
            "def5678 fix: correct validation",
            "ghi9012 test: add unit tests",
        ]
        groups = parse_commits(lines)
        assert len(groups["feat"]) == 1
        assert len(groups["fix"]) == 1
        assert len(groups["test"]) == 1

    def test_scoped_prefix(self):
        lines = ["abc1234 feat(auth): add oauth flow"]
        groups = parse_commits(lines)
        assert len(groups["feat"]) == 1
        assert "oauth" in groups["feat"][0]

    def test_unknown_prefix_goes_to_other(self):
        lines = ["abc1234 misc: cleanup old files"]
        groups = parse_commits(lines)
        assert len(groups["other"]) == 1

    def test_empty_input(self):
        groups = parse_commits([])
        assert all(len(v) == 0 for v in groups.values())

    def test_malformed_line_skipped(self):
        lines = ["not-a-valid-line", "abc1234 feat: valid entry"]
        groups = parse_commits(lines)
        assert len(groups["feat"]) == 1


class TestRenderChangelog:
    def test_renders_sections_with_entries(self):
        groups = {
            "feat": ["- add login page (abc1234)"],
            "fix": ["- correct validation (def5678)"],
            "refactor": [],
            "docs": [],
            "test": [],
            "chore": [],
            "style": [],
            "other": [],
        }
        output = render_changelog(groups)
        assert "### Features" in output
        assert "### Bug Fixes" in output
        assert "### Refactoring" not in output
        assert "abc1234" in output

    def test_empty_groups_produce_empty_output(self):
        groups = {
            k: [] for k in ("feat", "fix", "refactor", "docs", "test", "chore", "style", "other")
        }
        output = render_changelog(groups)
        assert output == ""


class TestGenerateChangelog:
    def test_generates_from_git_log(self):
        log_output = _git_log_output(
            [
                "abc1234 feat: add login",
                "def5678 fix: patch XSS",
            ]
        )
        with patch("superpower_workflow.docs.changelog.subprocess.run", return_value=log_output):
            result = generate_changelog()
        assert "### Features" in result
        assert "### Bug Fixes" in result
        assert "abc1234" in result

    def test_since_tag_passed_to_git(self):
        with patch(
            "superpower_workflow.docs.changelog.subprocess.run",
            return_value=_git_log_output([]),
        ) as mock:
            generate_changelog(since_tag="v0.1.0")
        cmd = mock.call_args[0][0]
        assert "v0.1.0..HEAD" in cmd

    def test_git_failure_returns_empty(self):
        fail = CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")
        with patch("superpower_workflow.docs.changelog.subprocess.run", return_value=fail):
            result = generate_changelog()
        assert result == ""
