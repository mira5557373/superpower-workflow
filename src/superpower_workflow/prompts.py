"""Phase-specific prompt templates per spec section 7."""

from __future__ import annotations


def system_prompt() -> str:
    return (
        "Do NOT ask clarifying questions. Use best judgment and note uncertainties.\n"
        "Follow all instructions in CLAUDE.md if present.\n"
        "If your context was compacted, re-read the plan or spec before continuing.\n"
        "Use conventional commits. Follow TDD when implementing code.\n"
        "Include a Generated-By trailer on every commit: "
        'git commit --trailer "Generated-By: <your-model-name>"'
    )


def phase_a_prompt(name: str, context_summary: str, spec_path: str, sections: str) -> str:
    return (
        f"You are executing Phase A (Plan + Ultrathink) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
        f"Before writing the plan:\n"
        f"- If CLAUDE.md does not exist in the project root, create one with:\n"
        f"  project name, tech stack, module map, conventions, and hard guardrails.\n"
        f"  Commit it before starting the plan.\n"
        f"- Read CLAUDE.md for project conventions and module map\n"
        f"- Read the __init__.py and main module of each dependency listed in the context\n"
        f"- Understand the interfaces you will build against\n\n"
        f"1. Read the spec at {spec_path}, focusing on sections {sections}.\n"
        f"2. Use the superpowers:writing-plans skill to create a TDD implementation plan\n"
        f"   (10-25 tasks). Save to docs/superpowers/plans/ with today's date and {name}.\n"
        f"3. Run ultrathink-gap-analysis on the plan.\n"
        f"4. Fix critical gaps inline. Write .claude/.gap-report.json with this schema:\n"
        '   {{"pass": N, "critical_gaps": N, "architectural_gaps": N, "important_gaps": N,\n'
        '    "minor_gaps": N, "deferred_gaps": N, "total_gaps_found": N,\n'
        '    "gaps_fixed_this_pass": N, "tests_green": true, "lint_clean": true,\n'
        '    "converged": true/false,\n'
        '    "gap_summaries": ["[ultrathink] description...", "[post-impl] description..."]}}\n'
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
        f"Commit each task individually with conventional commit messages.\n"
        f"\nWrite code with production deployment in mind: structured logging, error handling,\n"
        f"input validation at boundaries. TDD first -- after tests pass, add production\n"
        f"concerns as a refactoring step within the same task.\n"
        f"\nAfter each task, before committing: run lint on changed files, fix issues. "
        f"Do NOT commit code that fails lint or tests. These are HARD gates.\n\n"
        f"If context is compacted, re-read the plan at {plan_path}."
    )


def phase_c_prompt(
    name: str,
    context_summary: str,
    plan_commit_sha: str,
    verify_test: str,
    verify_lint: str,
    verify_format: str,
    compliance_report: dict | None = None,
    verification_report: dict | None = None,
) -> str:
    base = (
        f"You are executing Phase C (Review + Fix) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
    )

    extras = ""
    if compliance_report and compliance_report.get("missing", 0) > 0:
        extras += "\nThese spec requirements are missing from the implementation:\n"
        for d in compliance_report.get("details", []):
            if d.get("status") == "missing":
                extras += f"- {d.get('requirement', '?')} ({d.get('evidence', '')})\n"
        extras += "Implement them during this review phase.\n"

    if verification_report and verification_report.get("broken", 0) > 0:
        extras += "\nThese features exist but don't work correctly:\n"
        for d in verification_report.get("details", []):
            if d.get("status") == "fail":
                reason = d.get("reason", "")
                test = d.get("test", "")
                extras += f"- {d.get('feature', '?')}: FAIL"
                if reason:
                    extras += f" — {reason}"
                if test:
                    extras += f" ({test})"
                extras += "\n"
        extras += "Fix them during this review phase.\n"

    return (
        base + extras + f"1. Run post-impl-review on all files changed since {plan_commit_sha}.\n"
        f"2. Then run production-readiness-review on the same files.\n"
        f"3. Fix post-impl issues first (correctness), then production issues (hardening).\n"
        f"4. Re-run full test suite after all fixes.\n"
        f"5. Commit fixes. Tag each gap [post-impl] or [production] in gap_summaries.\n"
        f"6. Write .claude/.gap-report.json.\n\n"
        f"Verification: {verify_test}, {verify_lint}, {verify_format}"
    )


def phase_d_prompt(name: str, branch: str) -> str:
    return (
        f"Tag HEAD as {name}. If remote origin exists, run:\n"
        f"git push origin {branch} --tags\n"
        f"If push fails, report TAG_ONLY."
    )
