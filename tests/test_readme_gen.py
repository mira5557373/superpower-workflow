from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.docs.readme_gen import gather_context, generate_readme
from superpower_workflow.runner import ClaudeResult


class TestGatherContext:
    def test_reads_claude_md(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("# My Project\nSome context here.")
        context = gather_context(tmp_path, cwd=str(tmp_path))
        assert "My Project" in context

    def test_includes_git_log(self, tmp_path: Path):
        log = CompletedProcess(args=[], returncode=0, stdout="abc1234 feat: login\n", stderr="")
        with patch("superpower_workflow.docs.readme_gen.subprocess.run", return_value=log):
            context = gather_context(tmp_path, cwd=str(tmp_path))
        assert "abc1234" in context

    def test_handles_no_claude_md(self, tmp_path: Path):
        log = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("superpower_workflow.docs.readme_gen.subprocess.run", return_value=log):
            context = gather_context(tmp_path, cwd=str(tmp_path))
        assert isinstance(context, str)

    def test_git_failure_still_returns_context(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("# Proj")
        fail = CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")
        with patch("superpower_workflow.docs.readme_gen.subprocess.run", return_value=fail):
            context = gather_context(tmp_path, cwd=str(tmp_path))
        assert "Proj" in context


class TestGenerateReadme:
    def test_returns_claude_output(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("# Project")
        mock_result = ClaudeResult(text="# My README\nGenerated.", is_error=False, cost_usd=0.5)
        with (
            patch("superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result),
            patch(
                "superpower_workflow.docs.readme_gen.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ),
        ):
            result = generate_readme(tmp_path, cwd=str(tmp_path))
        assert "My README" in result

    def test_returns_empty_on_error(self, tmp_path: Path):
        mock_result = ClaudeResult(text="", is_error=True, cost_usd=0.0)
        with (
            patch("superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result),
            patch(
                "superpower_workflow.docs.readme_gen.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ),
        ):
            result = generate_readme(tmp_path, cwd=str(tmp_path))
        assert result == ""

    def test_passes_effort_and_budget_to_claude(self, tmp_path: Path):
        mock_result = ClaudeResult(text="content", is_error=False, cost_usd=0.1)
        with (
            patch(
                "superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result
            ) as mock_claude,
            patch(
                "superpower_workflow.docs.readme_gen.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ),
        ):
            generate_readme(tmp_path, effort="medium", budget=10, cwd=str(tmp_path))
        _, kwargs = mock_claude.call_args
        assert kwargs["effort"] == "medium"
        assert kwargs["budget"] == 10

    def test_passes_sections_to_prompt(self, tmp_path: Path):
        mock_result = ClaudeResult(text="content", is_error=False, cost_usd=0.1)
        with (
            patch(
                "superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result
            ) as mock_claude,
            patch(
                "superpower_workflow.docs.readme_gen.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ),
        ):
            generate_readme(tmp_path, sections=["overview", "api"], cwd=str(tmp_path))
        prompt = mock_claude.call_args[0][0]
        assert "overview" in prompt
        assert "api" in prompt

    def test_uses_template_when_provided(self, tmp_path: Path):
        (tmp_path / "tmpl.md").write_text("# Template\n$project_name")
        mock_result = ClaudeResult(text="content", is_error=False, cost_usd=0.1)
        with (
            patch(
                "superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result
            ) as mock_claude,
            patch(
                "superpower_workflow.docs.readme_gen.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ),
        ):
            generate_readme(tmp_path, template="tmpl.md", cwd=str(tmp_path))
        prompt = mock_claude.call_args[0][0]
        assert "Template" in prompt
