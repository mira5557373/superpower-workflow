"""Tests for the spec decomposer module."""

from __future__ import annotations

import json
from unittest.mock import patch

from superpower_workflow.decomposer import decompose
from superpower_workflow.runner import ClaudeResult


class TestDecomposeReturnsMilestones:
    """Test that decompose returns milestones from valid response."""

    def test_decompose_returns_milestones(self, tmp_path):
        """decompose returns milestones list."""
        milestones = [
            {
                "name": "p1-m1",
                "spec_sections": "1",
                "description": "d",
                "depends_on": [],
            }
        ]
        mock_result = ClaudeResult(text=json.dumps(milestones), is_error=False)
        with patch("superpower_workflow.decomposer.run_claude", return_value=mock_result):
            result = decompose(spec_path="spec.md", model="opus", cwd=str(tmp_path))
        assert len(result) >= 1


class TestDecomposeReturnsEmptyOnError:
    """Test that decompose returns empty list on error."""

    def test_decompose_returns_empty_on_error(self, tmp_path):
        """decompose returns empty list when first pass errors."""
        mock_result = ClaudeResult(text="error", is_error=True)
        with patch("superpower_workflow.decomposer.run_claude", return_value=mock_result):
            result = decompose(spec_path="spec.md", model="opus", cwd=str(tmp_path))
        assert result == []


class TestDecomposeHandlesJsonInMarkdown:
    """Test that decompose extracts JSON from markdown code blocks."""

    def test_decompose_handles_json_in_markdown(self, tmp_path):
        """decompose extracts JSON from markdown ```json blocks."""
        text = '```json\n[{"name":"m1","spec_sections":"1","description":"d","depends_on":[]}]\n```'
        mock_result = ClaudeResult(text=text, is_error=False)
        with patch("superpower_workflow.decomposer.run_claude", return_value=mock_result):
            result = decompose(spec_path="spec.md", model="opus", cwd=str(tmp_path))
        assert len(result) == 1
