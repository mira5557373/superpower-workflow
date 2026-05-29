"""Tests for the gap curator module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from superpower_workflow.validation.gap_curator import (
    _extract_referenced_files,
    build_curator_prompt,
    parse_curator_output,
    run_gap_curator,
)


class TestExtractReferencedFiles:
    def test_extracts_from_categorized_lists(self):
        raw = {
            "important": ["fix store.py:45 leak"],
            "minor": ["cli.py:12 has issue"],
        }
        assert _extract_referenced_files(raw) == {"store.py", "cli.py"}

    def test_extracts_from_flat_list(self):
        raw = {"gaps": ["bug at todo/storage.py:99"]}
        assert _extract_referenced_files(raw) == {"todo/storage.py"}

    def test_extracts_from_dict_summaries(self):
        raw = {"important": [{"summary": "issue in tests/test_cli.py:23"}]}
        assert _extract_referenced_files(raw) == {"tests/test_cli.py"}

    def test_no_files_returns_empty(self):
        raw = {"important": ["general concern"]}
        assert _extract_referenced_files(raw) == set()


class TestBuildCuratorPrompt:
    def test_review_phase_requires_diff_anchor(self):
        prompt = build_curator_prompt(
            phase="review",
            raw_gap_report={"important": ["x"]},
            spec_text="spec content",
            compliance_text="compliance data",
            diff_text="--- a/file.py\n+++ b/file.py",
        )
        assert "EXISTS in the diff" in prompt
        assert "SPEC COMPLIANCE FINDINGS" in prompt
        assert "DIFF" in prompt

    def test_plan_phase_allows_plan_anchors(self):
        prompt = build_curator_prompt(
            phase="plan",
            raw_gap_report={"important": ["x"]},
            spec_text="spec",
            compliance_text="",  # plan phase: no compliance yet
            diff_text="",
        )
        assert "plan markdown" in prompt
        # No compliance section when empty
        assert "SPEC COMPLIANCE FINDINGS" not in prompt

    def test_conservative_bias_present(self):
        prompt = build_curator_prompt(
            phase="review", raw_gap_report={}, spec_text="", compliance_text="", diff_text=""
        )
        assert "CONSERVATIVE BIAS" in prompt
        assert "KEEP the gap" in prompt

    def test_demands_pure_json_output(self):
        """Soak finding #A (transferred): curator prompt must not ask for file writes."""
        prompt = build_curator_prompt(
            phase="review", raw_gap_report={}, spec_text="", compliance_text="", diff_text=""
        )
        assert "SINGLE JSON object" in prompt
        assert "NOTHING ELSE" in prompt
        assert "no tool calls" in prompt or "no tool calls" in prompt.lower()

    def test_schema_includes_compat_fields(self):
        """Curator output schema must remain wire-compatible with the original
        gap_report consumers (critical/architectural/important/minor/deferred)."""
        prompt = build_curator_prompt(
            phase="review", raw_gap_report={}, spec_text="", compliance_text="", diff_text=""
        )
        for key in (
            '"critical_gaps"',
            '"architectural_gaps"',
            '"important_gaps"',
            '"minor_gaps"',
            '"deferred_gaps"',
            '"total_gaps_found"',
            '"converged"',
        ):
            assert key in prompt, f"prompt missing {key}"


class TestParseCuratorOutput:
    def test_parses_valid_json(self):
        text = '{"curated_gaps": [{"summary": "x"}], "total_gaps_found": 1}'
        out = parse_curator_output(text)
        assert out is not None
        assert out["total_gaps_found"] == 1
        assert len(out["curated_gaps"]) == 1

    def test_extracts_json_from_surrounding_prose(self):
        text = (
            'Here is the curated report:\n{"curated_gaps": [], "total_gaps_found": 0}\nThat is all.'
        )
        out = parse_curator_output(text)
        assert out is not None
        assert out["total_gaps_found"] == 0

    def test_rejects_non_json(self):
        assert parse_curator_output("nope") is None
        assert parse_curator_output("") is None

    def test_rejects_missing_curated_gaps_field(self):
        """Schema sanity: curated_gaps must be a list."""
        text = '{"total_gaps_found": 0}'
        assert parse_curator_output(text) is None

    def test_rejects_invalid_json(self):
        text = '{"curated_gaps": [unparseable'
        assert parse_curator_output(text) is None


class TestRunGapCurator:
    def _ok_claude(self, payload: dict):
        text = json.dumps(payload)
        return MagicMock(text=text, cost_usd=0.4, is_error=False)

    def _err_claude(self):
        return MagicMock(text="", cost_usd=0.05, is_error=True)

    def _mock_fn(self, response):
        def _fn(prompt, **kwargs):
            return response

        return _fn

    def test_returns_curated_on_success(self, tmp_path: Path):
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec\n- todo add\n")
        raw = {"important": ["leak in todo.py:45"], "total_gaps_found": 1}
        response_payload = {
            "curated_gaps": [
                {
                    "summary": "leak in todo.py:45",
                    "file": "todo.py",
                    "line": 45,
                    "severity": "important",
                }
            ],
            "dropped_count": 0,
            "dropped_reasons": {
                "unanchored": 0,
                "spec_duplicate": 0,
                "trivial": 0,
                "speculative": 0,
            },
            "critical_gaps": 0,
            "architectural_gaps": 0,
            "important_gaps": 1,
            "minor_gaps": 0,
            "deferred_gaps": 0,
            "total_gaps_found": 1,
            "converged": False,
        }
        result = run_gap_curator(
            raw_gap_report=raw,
            phase="review",
            project_root=tmp_path,
            spec_path=spec,
            compliance_path=None,
            plan_sha="",
            run_claude_fn=self._mock_fn(self._ok_claude(response_payload)),
            model="opus",
            budget=1.0,
            cwd=str(tmp_path),
        )
        assert result is not None
        assert result["total_gaps_found"] == 1
        assert result["curated"] is True
        assert result["cost_usd"] == 0.4

    def test_returns_none_on_claude_error(self, tmp_path: Path):
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec")
        result = run_gap_curator(
            raw_gap_report={"important": ["x"]},
            phase="review",
            project_root=tmp_path,
            spec_path=spec,
            compliance_path=None,
            plan_sha="",
            run_claude_fn=self._mock_fn(self._err_claude()),
            model="opus",
            budget=1.0,
            cwd=str(tmp_path),
        )
        assert result is None

    def test_returns_none_on_unparseable_output(self, tmp_path: Path):
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec")
        bad_response = MagicMock(text="not json", cost_usd=0.3, is_error=False)
        result = run_gap_curator(
            raw_gap_report={"important": ["x"]},
            phase="review",
            project_root=tmp_path,
            spec_path=spec,
            compliance_path=None,
            plan_sha="",
            run_claude_fn=self._mock_fn(bad_response),
            model="opus",
            budget=1.0,
            cwd=str(tmp_path),
        )
        assert result is None

    def test_writes_output_path_when_given(self, tmp_path: Path):
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec")
        output_path = tmp_path / "curated.json"
        response_payload = {
            "curated_gaps": [],
            "dropped_count": 0,
            "dropped_reasons": {
                "unanchored": 0,
                "spec_duplicate": 0,
                "trivial": 0,
                "speculative": 0,
            },
            "total_gaps_found": 0,
            "converged": True,
        }
        run_gap_curator(
            raw_gap_report={"gaps": ["x"]},
            phase="review",
            project_root=tmp_path,
            spec_path=spec,
            compliance_path=None,
            plan_sha="",
            run_claude_fn=self._mock_fn(self._ok_claude(response_payload)),
            model="opus",
            budget=1.0,
            cwd=str(tmp_path),
            output_path=output_path,
        )
        assert output_path.exists()
        on_disk = json.loads(output_path.read_text())
        assert on_disk["converged"] is True
