from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from superpower_workflow.validation.feature_tester import (
    build_verification_prompt,
    parse_verification_output,
    run_feature_verification,
)


class TestBuildVerificationPrompt:
    def test_includes_compliance_path(self):
        prompt = build_verification_prompt(".claude/.spec-compliance.json")
        assert ".spec-compliance.json" in prompt

    def test_prompt_demands_pure_json_output(self):
        """Soak finding #A: prompt must NOT ask claude to write a file."""
        prompt = build_verification_prompt(".claude/.spec-compliance.json")
        assert "single JSON object" in prompt
        assert "NOTHING ELSE" in prompt
        assert "Write .claude/.feature-verification.json" not in prompt
        assert "No tool calls" in prompt or "no tool calls" in prompt.lower()

    def test_instructs_test_execution(self):
        prompt = build_verification_prompt(".claude/.spec-compliance.json")
        assert "test" in prompt.lower()


class TestParseVerificationOutput:
    def test_parses_valid_json(self):
        raw = json.dumps(
            {
                "total_features": 10,
                "verified_working": 8,
                "broken": 1,
                "manual_review": 1,
                "details": [
                    {"feature": "parser", "status": "pass", "test": "test_parser.py::test_it"},
                    {
                        "feature": "cli",
                        "status": "fail",
                        "test": "test_cli.py::test_it",
                        "reason": "off by one",
                    },
                    {"feature": "docs", "status": "manual_review", "reason": "subjective"},
                ],
            }
        )
        result = parse_verification_output(raw)
        assert result["total_features"] == 10
        assert result["verified_working"] == 8
        assert result["broken"] == 1

    def test_returns_empty_on_invalid(self):
        result = parse_verification_output("not json")
        assert result["total_features"] == 0

    def test_handles_missing_fields(self):
        result = parse_verification_output(json.dumps({"total_features": 5}))
        assert result["total_features"] == 5
        assert result["broken"] == 0


class TestRunFeatureVerification:
    def test_calls_run_claude_and_writes_output(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        compliance = {
            "total_requirements": 5,
            "implemented": 4,
            "missing": 1,
            "details": [
                {"requirement": "feat A", "status": "implemented", "evidence": "mod.py:func"}
            ],
        }
        (claude_dir / ".spec-compliance.json").write_text(json.dumps(compliance))

        mock_result = MagicMock()
        mock_result.text = json.dumps(
            {
                "total_features": 4,
                "verified_working": 3,
                "broken": 1,
                "manual_review": 0,
                "details": [
                    {"feature": "feat A", "status": "fail", "reason": "returns wrong value"}
                ],
            }
        )
        mock_result.cost_usd = 3.5
        mock_result.is_error = False

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_feature_verification(
            compliance_path=claude_dir / ".spec-compliance.json",
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=5.0,
            cwd=str(tmp_path),
            output_path=claude_dir / ".feature-verification.json",
        )

        assert report["broken"] == 1
        assert (claude_dir / ".feature-verification.json").exists()

    def test_skips_when_no_compliance_file(self, tmp_path: Path):
        mock_run_claude = MagicMock()

        report = run_feature_verification(
            compliance_path=tmp_path / ".claude" / ".spec-compliance.json",
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=5.0,
            cwd=str(tmp_path),
        )

        assert report["total_features"] == 0
        mock_run_claude.assert_not_called()

    def test_returns_empty_on_claude_error(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / ".spec-compliance.json").write_text(
            json.dumps(
                {
                    "total_requirements": 1,
                    "implemented": 1,
                    "details": [{"requirement": "a", "status": "implemented", "evidence": "x"}],
                }
            )
        )

        mock_result = MagicMock()
        mock_result.is_error = True
        mock_result.text = ""
        mock_result.cost_usd = 1.0

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_feature_verification(
            compliance_path=claude_dir / ".spec-compliance.json",
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=5.0,
            cwd=str(tmp_path),
        )

        assert report["total_features"] == 0
