"""Phase-specific prompt templates for superpower-workflow."""

from __future__ import annotations


def system_prompt() -> str:
    """Return system-level instructions for all phases."""
    return (
        "Do NOT ask clarifying questions. Use best judgment and note uncertainties.\n"
        "Follow all instructions in CLAUDE.md if present.\n"
        "If your context was compacted, re-read the plan or spec before continuing.\n"
        "Use conventional commits. Follow TDD when implementing code."
    )


def phase_a_prompt(name: str, context_summary: str, spec_path: str, sections: str) -> str:
    """Return Phase A (Plan + Ultrathink) prompt with placeholders filled.

    Args:
        name: Milestone name
        context_summary: Context summary
        spec_path: Path to spec file
        sections: Enumerated gap-checked sections
    """
    return (
        f"Milestone: {name}\n"
        f"Context: {context_summary}\n"
        f"Spec: {spec_path}\n"
        f"Sections:\n{sections}\n"
        "\n"
        "Use superpowers:writing-plans to create a detailed implementation plan.\n"
        "Use ultrathink to enumerate >=20 concrete gaps per design section before revising."
    )


def phase_b_prompt(name: str, context_summary: str, plan_path: str) -> str:
    """Return Phase B (Implementation) prompt with placeholders filled.

    Args:
        name: Milestone name
        context_summary: Context summary
        plan_path: Path to plan file
    """
    return (
        f"Milestone: {name}\n"
        f"Context: {context_summary}\n"
        f"Plan: {plan_path}\n"
        "\n"
        "Use superpowers:subagent-driven-development to execute the plan with "
        "independent tasks in parallel where possible.\n"
        "Note: If this plan has >25 tasks, request OVERSIZED report."
    )


def phase_c_prompt(
    name: str,
    context_summary: str,
    plan_commit_sha: str,
    verify_test: str,
    verify_lint: str,
    verify_format: str,
) -> str:
    """Return Phase C (Review + Fix) prompt with placeholders filled.

    Args:
        name: Milestone name
        context_summary: Context summary
        plan_commit_sha: Git SHA of plan commit
        verify_test: Test verification command
        verify_lint: Lint verification command
        verify_format: Format verification command
    """
    return (
        f"Milestone: {name}\n"
        f"Context: {context_summary}\n"
        f"Plan commit: {plan_commit_sha}\n"
        "\n"
        "Verification:\n"
        f"  - Test: {verify_test}\n"
        f"  - Lint: {verify_lint}\n"
        f"  - Format: {verify_format}\n"
        "\n"
        "Use superpowers:requesting-code-review for critical-mechanical fixes.\n"
        "All changes must pass verification commands before completion."
    )


def phase_d_prompt(name: str, branch: str) -> str:
    """Return Phase D (Push + Tag) prompt with placeholders filled.

    Args:
        name: Milestone name
        branch: Git branch name
    """
    return (
        f"Milestone: {name}\n"
        f"Branch: {branch}\n"
        "\n"
        "Push to remote and create annotated tag for this milestone."
    )
