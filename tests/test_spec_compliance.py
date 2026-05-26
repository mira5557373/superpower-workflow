from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from superpower_workflow.validation.spec_compliance import (
    build_compliance_prompt,
    parse_compliance_output,
    run_spec_compliance,
)


class TestBuildCompliancePrompt:
    def test_includes_spec_path(self):
        prompt = build_compliance_prompt("docs/spec.md", "4, 5, 6", "src/mymodule/")
        assert "docs/spec.md" in prompt
        assert "4, 5, 6" in prompt

    def test_includes_module_dir(self):
        prompt = build_compliance_prompt("spec.md", "1", "src/mod/")
        assert "src/mod/" in prompt

    def test_includes_output_instructions(self):
        prompt = build_compliance_prompt("spec.md", "1", "src/")
        assert ".spec-compliance.json" in prompt


class TestParseComplianceOutput:
    def test_parses_valid_json(self):
        raw = json.dumps(
            {
                "spec_path": "spec.md",
                "spec_sections": "4, 5",
                "total_requirements": 10,
                "implemented": 8,
                "missing": 2,
                "details": [
                    {
                        "requirement": "feature A",
                        "status": "implemented",
                        "evidence": "mod.py:func_a",
                    },
                    {
                        "requirement": "feature B",
                        "status": "missing",
                        "evidence": "not found",
                    },
                ],
            }
        )
        result = parse_compliance_output(raw)
        assert result["total_requirements"] == 10
        assert result["implemented"] == 8
        assert result["missing"] == 2
        assert len(result["details"]) == 2

    def test_returns_empty_on_invalid_json(self):
        result = parse_compliance_output("not json")
        assert result["total_requirements"] == 0
        assert result["missing"] == 0

    def test_returns_empty_on_missing_fields(self):
        result = parse_compliance_output(json.dumps({"foo": "bar"}))
        assert result["total_requirements"] == 0


class TestRunSpecCompliance:
    def test_calls_run_claude_and_writes_output(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        mock_result = MagicMock()
        mock_result.text = json.dumps(
            {
                "spec_path": "spec.md",
                "spec_sections": "1",
                "total_requirements": 5,
                "implemented": 4,
                "missing": 1,
                "details": [{"requirement": "feat", "status": "missing", "evidence": "not found"}],
            }
        )
        mock_result.cost_usd = 2.0
        mock_result.is_error = False

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_spec_compliance(
            spec_path="docs/spec.md",
            spec_sections="1, 2",
            module_dirs=["src/mod/"],
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=3.0,
            cwd=str(tmp_path),
            output_path=claude_dir / ".spec-compliance.json",
        )

        assert report["missing"] == 1
        assert (claude_dir / ".spec-compliance.json").exists()
        mock_run_claude.assert_called_once()

    def test_returns_empty_on_error(self, tmp_path: Path):
        mock_result = MagicMock()
        mock_result.is_error = True
        mock_result.text = ""
        mock_result.cost_usd = 0.5

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_spec_compliance(
            spec_path="spec.md",
            spec_sections="1",
            module_dirs=["src/"],
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=3.0,
            cwd=str(tmp_path),
        )

        assert report["total_requirements"] == 0
