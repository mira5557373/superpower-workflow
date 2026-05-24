from superpower_workflow.prompts import (
    phase_a_prompt,
    phase_b_prompt,
    phase_c_prompt,
    phase_d_prompt,
    system_prompt,
)


def test_system_prompt_has_no_questions_instruction():
    p = system_prompt()
    assert "Do NOT ask clarifying questions" in p


def test_phase_a_prompt_includes_spec_and_milestone():
    p = phase_a_prompt(
        name="p1-m2", context_summary="M1 done.", spec_path="spec.md", sections="4.3"
    )
    assert "p1-m2" in p
    assert "spec.md" in p
    assert "4.3" in p
    assert "writing-plans" in p


def test_phase_a_prompt_includes_gap_report_instruction():
    p = phase_a_prompt(name="m1", context_summary="", spec_path="s.md", sections="1")
    assert ".gap-report.json" in p
    assert "critical_gaps" in p


def test_phase_a_prompt_no_verify_line():
    p = phase_a_prompt(name="m1", context_summary="", spec_path="s.md", sections="1")
    assert "Verification:" not in p


def test_phase_b_prompt_includes_plan_path():
    p = phase_b_prompt(name="p1-m2", context_summary="M1 done.", plan_path="plans/p1-m2.md")
    assert "plans/p1-m2.md" in p
    assert "subagent-driven-development" in p
    assert "OVERSIZED" in p
    assert "TDD" in p


def test_phase_b_prompt_includes_compaction_instruction():
    p = phase_b_prompt(name="m1", context_summary="", plan_path="plan.md")
    assert "compacted" in p
    assert "plan.md" in p.split("compacted")[1]


def test_phase_c_prompt_includes_verification():
    p = phase_c_prompt(
        name="p1-m2",
        context_summary="M1 done.",
        plan_commit_sha="abc123",
        verify_test="pytest -q",
        verify_lint="ruff check .",
        verify_format="ruff format --check .",
    )
    assert "abc123" in p
    assert "pytest -q" in p
    assert "production-readiness-review" in p
    assert ".gap-report.json" in p
    assert "post-impl-review" in p


def test_phase_d_prompt_includes_tag_and_branch():
    p = phase_d_prompt(name="p1-m2", branch="main")
    assert "p1-m2" in p
    assert "main" in p
    assert "TAG_ONLY" in p
    assert "git push" in p


def test_phase_a_prompt_includes_read_modules_instruction():
    p = phase_a_prompt(name="m1", context_summary="", spec_path="s.md", sections="1")
    assert "Read CLAUDE.md" in p
    assert "Read the __init__.py" in p


def test_phase_a_prompt_includes_gap_summaries_schema():
    p = phase_a_prompt(name="m1", context_summary="", spec_path="s.md", sections="1")
    assert "gap_summaries" in p


def test_phase_b_prompt_includes_production_mindset():
    p = phase_b_prompt(name="m1", context_summary="", plan_path="plan.md")
    assert "production deployment" in p


def test_phase_c_prompt_includes_production_review():
    p = phase_c_prompt(
        name="m1",
        context_summary="",
        plan_commit_sha="abc",
        verify_test="t",
        verify_lint="l",
        verify_format="f",
    )
    assert "production-readiness-review" in p


def test_system_prompt_includes_trailer_instruction():
    p = system_prompt()
    assert "Generated-By" in p
    assert "git commit --trailer" in p


def test_phase_b_prompt_includes_quality_gate_instruction():
    p = phase_b_prompt(name="m1", context_summary="", plan_path="plan.md")
    assert "lint" in p.lower()
    assert "Do NOT commit" in p


def test_phase_c_prompt_fix_order():
    p = phase_c_prompt(
        name="m1",
        context_summary="",
        plan_commit_sha="abc",
        verify_test="t",
        verify_lint="l",
        verify_format="f",
    )
    post_impl_pos = p.index("post-impl")
    production_pos = p.index("production issues")
    assert post_impl_pos < production_pos
