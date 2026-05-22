"""Phase-specific prompt templates per spec section 7."""

from __future__ import annotations


def system_prompt() -> str:
    return (
        "Do NOT ask clarifying questions. Use best judgment and note uncertainties.\n"
        "Follow all instructions in CLAUDE.md if present.\n"
        "If your context was compacted, re-read the plan or spec before continuing.\n"
        "Use conventional commits. Follow TDD when implementing code."
    )


def phase_a_prompt(name: str, context_summary: str, spec_path: str, sections: str) -> str:
    return (
        f"You are executing Phase A (Plan + Ultrathink) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
        f"1. Read the spec at {spec_path}, focusing on sections {sections}.\n"
        f"2. Use the superpowers:writing-plans skill to create a TDD implementation plan\n"
        f"   (10-25 tasks). Save to docs/superpowers/plans/ with today's date and {name}.\n"
        f"3. Run ultrathink-gap-analysis on the plan.\n"
        f"4. Fix critical gaps inline. Write .claude/.gap-report.json with this schema:\n"
        '   {{"pass": N, "critical_gaps": N, "architectural_gaps": N, "important_gaps": N,\n'
        '    "minor_gaps": N, "deferred_gaps": N, "total_gaps_found": N,\n'
        '    "gaps_fixed_this_pass": N, "tests_green": true, "lint_clean": true,\n'
        '    "converged": true/false}}\n'
        f"   critical_gaps/important_gaps = remaining AFTER fixes, not total found.\n"
        f"5. Commit the final plan."
    )


def phase_b_prompt(name: str, context_summary: str, plan_path: str) -> str:
    return (
        f"You are executing Phase B (Implementation) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
        f"Execute the plan at {plan_path} using the superpowers:subagent-driven-development\n"
        f"skill. Implement ALL tasks with TDD (red -> green -> commit per task).\n"
        f"If the plan exceeds 25 tasks, report OVERSIZED.\n"
        f"Commit each task individually with conventional commit messages.\n\n"
        f"If context is compacted, re-read the plan at {plan_path}."
    )


def phase_c_prompt(
    name: str,
    context_summary: str,
    plan_commit_sha: str,
    verify_test: str,
    verify_lint: str,
    verify_format: str,
) -> str:
    return (
        f"You are executing Phase C (Review + Fix) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
        f"1. Run post-impl-review on all files changed since {plan_commit_sha}.\n"
        f"2. Fix ALL critical-mechanical and important issues. Flag architectural gaps in the report.\n"
        f"3. Commit fixes as a single commit.\n"
        f"4. Write .claude/.gap-report.json with gap counts.\n"
        f"   critical_gaps/important_gaps = remaining AFTER fixes.\n"
        f"   tests_green and lint_clean = state after running verify commands.\n\n"
        f"Verification: {verify_test}, {verify_lint}, {verify_format}"
    )


def phase_d_prompt(name: str, branch: str) -> str:
    return (
        f"Tag HEAD as {name}. If remote origin exists, run:\n"
        f"git push origin {branch} --tags\n"
        f"If push fails, report TAG_ONLY."
    )
