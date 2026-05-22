"""Tests for prompt template module."""

from superpower_workflow.prompts import (
    phase_a_prompt,
    phase_b_prompt,
    phase_c_prompt,
    phase_d_prompt,
    system_prompt,
)


class TestSystemPrompt:
    """Test system_prompt function."""

    def test_system_prompt_has_no_questions_instruction(self):
        """system_prompt includes 'Do NOT ask clarifying questions' instruction."""
        prompt = system_prompt()
        assert "Do NOT ask clarifying questions" in prompt


class TestPhaseAPrompt:
    """Test phase_a_prompt function."""

    def test_phase_a_prompt_includes_spec_and_milestone(self):
        """phase_a_prompt includes spec_path, name, sections, and writing-plans skill."""
        prompt = phase_a_prompt(
            name="Feature X",
            context_summary="Build feature X",
            spec_path="spec.md",
            sections="1. Section A\n2. Section B",
        )

        assert "Feature X" in prompt
        assert "spec.md" in prompt
        assert "1. Section A" in prompt
        assert "2. Section B" in prompt
        assert "writing-plans" in prompt

    def test_phase_a_prompt_no_verify_line(self):
        """phase_a_prompt does NOT include 'Verification:' line."""
        prompt = phase_a_prompt(
            name="Feature X",
            context_summary="Build feature X",
            spec_path="spec.md",
            sections="1. Section A",
        )

        assert "Verification:" not in prompt


class TestPhaseBPrompt:
    """Test phase_b_prompt function."""

    def test_phase_b_prompt_includes_plan_path(self):
        """phase_b_prompt includes plan_path and subagent-driven-development skill."""
        prompt = phase_b_prompt(
            name="Feature Y",
            context_summary="Implement feature Y",
            plan_path="plan.md",
        )

        assert "Feature Y" in prompt
        assert "plan.md" in prompt
        assert "subagent-driven-development" in prompt


class TestPhaseCPrompt:
    """Test phase_c_prompt function."""

    def test_phase_c_prompt_includes_verification(self):
        """phase_c_prompt includes plan_commit_sha, verify commands, and critical-mechanical."""
        prompt = phase_c_prompt(
            name="Feature Z",
            context_summary="Review and fix feature Z",
            plan_commit_sha="abc1234567",
            verify_test="pytest",
            verify_lint="ruff check",
            verify_format="ruff format --check",
        )

        assert "Feature Z" in prompt
        assert "abc1234567" in prompt
        assert "pytest" in prompt
        assert "ruff check" in prompt
        assert "ruff format --check" in prompt
        assert "critical-mechanical" in prompt
        assert "Verification:" in prompt


class TestPhaseDPrompt:
    """Test phase_d_prompt function."""

    def test_phase_d_prompt_includes_branch(self):
        """phase_d_prompt includes milestone name and branch."""
        prompt = phase_d_prompt(
            name="Release v1.0",
            branch="main",
        )

        assert "Release v1.0" in prompt
        assert "main" in prompt
