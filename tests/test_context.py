"""Tests for context generator module."""

from superpower_workflow.context import build_context_summary


class TestEmptyCompleted:
    """Test behavior when no milestones are completed."""

    def test_empty_completed_returns_empty(self):
        """build_context_summary returns 'No prior milestones.' when completed is empty."""
        result = build_context_summary([])
        assert result == "No prior milestones."


class TestSingleMilestone:
    """Test behavior with a single milestone."""

    def test_single_milestone(self):
        """Single milestone name appears in output."""
        result = build_context_summary(["authentication"])
        assert "authentication" in result
        assert "Recent:" in result


class TestMultipleMilestones:
    """Test behavior with multiple milestones."""

    def test_four_milestones_summarizes_older(self):
        """Last 3 detailed, first one in summary."""
        completed = ["setup", "database", "api", "frontend"]
        result = build_context_summary(completed)

        assert "setup complete." in result
        assert "Recent: database, api, frontend." in result


class TestWordCapping:
    """Test that output is capped at 200 words."""

    def test_context_capped_at_200_words(self):
        """20 milestones result in output with <= 200 words."""
        completed = [f"milestone_{i}" for i in range(20)]
        result = build_context_summary(completed)

        word_count = len(result.split())
        assert word_count <= 200
