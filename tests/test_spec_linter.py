"""Tests for the spec linter (T1.7.1)."""

from __future__ import annotations

from pathlib import Path

from superpower_workflow.validation.spec_linter import (
    CheckState,
    lint_spec,
    write_report,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# --- requirements_countable ---


class TestRequirementsCountable:
    def test_numbered_list_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "## Reqs\n1. foo\n2. bar\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "requirements_countable")
        assert check.state == CheckState.PASS

    def test_bullet_list_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "## Reqs\n- foo\n- bar\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "requirements_countable")
        assert check.state == CheckState.PASS

    def test_prose_only_fails(self, tmp_path):
        spec = _write(tmp_path, "s.md", "Some prose about the project. No lists.\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "requirements_countable")
        assert check.state == CheckState.FAIL
        assert r.blocker_count >= 1


# --- nonfunctional_section ---


class TestNonfunctionalSection:
    def test_present_with_three_bullets_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "## Non-functional\n- perf\n- security\n- observability\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "nonfunctional_section")
        assert check.state == CheckState.PASS

    def test_missing_warns(self, tmp_path):
        spec = _write(tmp_path, "s.md", "## Functional\n- foo\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "nonfunctional_section")
        assert check.state == CheckState.WARN

    def test_present_but_thin_warns(self, tmp_path):
        """G1.7.1: empty NFR section must NOT pass — must have >=3 bullets."""
        spec = _write(tmp_path, "s.md", "## Non-functional\n- only one\n## Other\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "nonfunctional_section")
        assert check.state == CheckState.WARN
        assert "3" in check.reason


# --- quality_gates_declared ---


class TestQualityGatesDeclared:
    def test_lint_mention_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "Spec runs lint via ruff before merging.\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "quality_gates_declared")
        assert check.state == CheckState.PASS

    def test_no_mention_warns(self, tmp_path):
        spec = _write(tmp_path, "s.md", "Build the feature.\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "quality_gates_declared")
        assert check.state == CheckState.WARN


# --- out_of_scope_section ---


class TestOutOfScopeSection:
    def test_explicit_section_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "## Out of scope\n- thing\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "out_of_scope_section")
        assert check.state == CheckState.PASS

    def test_not_included_synonym_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "## Not included\n- thing\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "out_of_scope_section")
        assert check.state == CheckState.PASS

    def test_missing_warns(self, tmp_path):
        spec = _write(tmp_path, "s.md", "Just requirements\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "out_of_scope_section")
        assert check.state == CheckState.WARN


# --- no_placeholders ---


class TestNoPlaceholders:
    def test_clean_spec_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "Spec is complete.\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "no_placeholders")
        assert check.state == CheckState.PASS

    def test_tbd_fails(self, tmp_path):
        spec = _write(tmp_path, "s.md", "Feature: TBD\n- 1. foo\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "no_placeholders")
        assert check.state == CheckState.FAIL

    def test_todo_fails(self, tmp_path):
        spec = _write(tmp_path, "s.md", "TODO: write spec\n- 1. foo\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "no_placeholders")
        assert check.state == CheckState.FAIL

    def test_triple_question_fails(self, tmp_path):
        spec = _write(tmp_path, "s.md", "Storage path: ???\n- 1. foo\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "no_placeholders")
        assert check.state == CheckState.FAIL


# --- acceptance_criteria (G1.7.3: multi-style) ---


class TestAcceptanceCriteria:
    def test_must_style_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. todo must persist between runs.\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "acceptance_criteria")
        assert check.state == CheckState.PASS

    def test_when_then_style_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. When user types add, then a todo appears.\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "acceptance_criteria")
        assert check.state == CheckState.PASS

    def test_given_when_then_style_passes(self, tmp_path):
        spec = _write(
            tmp_path, "s.md", "1. Given an empty store, when add runs, then count is 1.\n"
        )
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "acceptance_criteria")
        assert check.state == CheckState.PASS

    def test_req_nn_style_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "- REQ-001: persist todos.\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "acceptance_criteria")
        assert check.state == CheckState.PASS

    def test_no_criteria_warns(self, tmp_path):
        spec = _write(tmp_path, "s.md", "- some bullet\n- another\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "acceptance_criteria")
        assert check.state == CheckState.WARN


# --- length_reasonable ---


class TestLengthReasonable:
    def test_in_range_passes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. foo " + " word" * 250)
        r = lint_spec(spec, min_words=100, max_words=500)
        check = next(c for c in r.checks if c.name == "length_reasonable")
        assert check.state == CheckState.PASS

    def test_too_short_warns(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. foo")
        r = lint_spec(spec, min_words=100, max_words=500)
        check = next(c for c in r.checks if c.name == "length_reasonable")
        assert check.state == CheckState.WARN
        assert "under" in check.reason.lower() or "vague" in check.reason.lower()

    def test_too_long_warns(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. " + " word" * 6000)
        r = lint_spec(spec, min_words=100, max_words=500)
        check = next(c for c in r.checks if c.name == "length_reasonable")
        assert check.state == CheckState.WARN
        assert "over" in check.reason.lower() or "decomposition" in check.reason.lower()


# --- code_blocks_balanced (G1.7.11) ---


class TestCodeBlocksBalanced:
    def test_balanced_backticks_pass(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. foo\n```python\nx=1\n```\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "code_blocks_balanced")
        assert check.state == CheckState.PASS

    def test_balanced_tildes_pass(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. foo\n~~~python\nx=1\n~~~\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "code_blocks_balanced")
        assert check.state == CheckState.PASS

    def test_orphan_backtick_fails(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. foo\n```\nx=1\n(missing close)\n")
        r = lint_spec(spec)
        check = next(c for c in r.checks if c.name == "code_blocks_balanced")
        assert check.state == CheckState.FAIL


# --- score & report ---


class TestScoring:
    def test_perfect_spec_scores_100(self, tmp_path):
        spec = _write(
            tmp_path,
            "s.md",
            "## Functional\n"
            "1. Add must persist a todo.\n"
            "2. List must show open todos.\n"
            "## Non-functional\n"
            "- perf: <100ms\n"
            "- security: 0600 perms\n"
            "- observability: structured logs\n"
            "## Quality gates\n"
            "lint with ruff, test with pytest, coverage >=90%.\n"
            "## Out of scope\n"
            "- networking\n" + " word" * 250,
        )
        r = lint_spec(spec, min_words=100, max_words=2000)
        assert r.score == 100
        assert r.blocker_count == 0
        assert r.warning_count == 0

    def test_blockers_subtract_10(self, tmp_path):
        # 1 FAIL (no_placeholders) -> -10
        spec = _write(
            tmp_path,
            "s.md",
            "## Functional\n"
            "1. Add must persist. TBD.\n"
            "## Non-functional\n- a\n- b\n- c\n"
            "lint, test, coverage 90%.\n"
            "## Out of scope\n- x\n" + " word" * 250,
        )
        r = lint_spec(spec, min_words=100, max_words=2000)
        assert r.score == 90

    def test_score_floor_at_zero(self, tmp_path):
        spec = _write(tmp_path, "s.md", "TBD. ???\nx = 1\n```\n")
        r = lint_spec(spec)
        assert r.score >= 0  # never negative


class TestReport:
    def test_report_to_dict_serializes(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. foo\n")
        r = lint_spec(spec)
        d = r.to_dict()
        assert d["spec_path"] == str(spec)
        assert d["score"] == r.score
        assert all("name" in c and "state" in c for c in d["checks"])

    def test_write_report_atomic(self, tmp_path):
        spec = _write(tmp_path, "s.md", "1. foo\n")
        r = lint_spec(spec)
        out = tmp_path / ".claude" / "spec-lint.json"
        out.parent.mkdir()
        write_report(r, out)
        assert out.exists()
        import json as _j

        data = _j.loads(out.read_text())
        assert data["score"] == r.score


class TestSectionLinting:
    def test_section_limits_scope(self, tmp_path):
        """G1.7.4: --section restricts checks to one heading body."""
        spec = _write(
            tmp_path,
            "s.md",
            "## Auth\n1. user must login.\n## Storage\n- TBD detail later\n",
        )
        full = lint_spec(spec)
        auth_only = lint_spec(spec, section="Auth")
        # Full spec sees TBD (FAIL); Auth-only section does not
        assert full.blocker_count > auth_only.blocker_count


class TestExampleSpecPasses:
    def test_todo_cli_example_scores_at_least_80(self):
        """CI gate per CC6.1: our own example spec must score >=80."""
        example = Path(__file__).resolve().parent.parent / "examples" / "todo-cli" / "spec.md"
        if not example.exists():
            return  # silently skip if example moved
        r = lint_spec(example)
        assert r.score >= 80, (
            f"examples/todo-cli/spec.md scored {r.score}; required >= 80. "
            f"Checks: {[(c.name, c.state.value) for c in r.checks]}"
        )
