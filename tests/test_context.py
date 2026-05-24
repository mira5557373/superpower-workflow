"""Tests for context generator module."""

from pathlib import Path
from unittest.mock import patch

from superpower_workflow.context import build_context_summary


def test_empty_completed_returns_no_prior():
    """Test that empty completed list returns 'No prior milestones.'"""
    summary = build_context_summary(completed=[], project_root=Path("/tmp"))
    assert summary == "No prior milestones."


def test_single_milestone_shows_name():
    """Test that single milestone appears in output."""
    summary = build_context_summary(completed=["p1-m1-foundations"], project_root=Path("/tmp"))
    assert "p1-m1-foundations" in summary


def test_dependency_detail_included():
    """Test that dependencies from current_milestone are listed."""
    ms = {"name": "p1-m5", "depends_on": ["p1-m3", "p1-m4"]}
    summary = build_context_summary(
        completed=["p1-m1", "p1-m2", "p1-m3", "p1-m4"],
        project_root=Path("/tmp"),
        current_milestone=ms,
        milestones=[ms],
    )
    assert "p1-m3" in summary
    assert "p1-m4" in summary


def test_context_capped_at_400_words():
    """Test that output is capped at 400 words."""
    completed = [f"p1-m{i}" for i in range(25)]
    summary = build_context_summary(completed=completed, project_root=Path("/tmp"))
    assert len(summary.split()) <= 400


def test_older_milestones_summarized():
    """Test that recent milestones are included in output."""
    completed = ["m1", "m2", "m3", "m4", "m5", "m6"]
    summary = build_context_summary(completed=completed, project_root=Path("/tmp"))
    assert "m6" in summary
    assert "m5" in summary


def test_paths_use_forward_slashes():
    """Test that output uses forward slashes, not backslashes."""
    summary = build_context_summary(completed=["m1"], project_root=Path("/tmp"))
    assert "\\\\" not in summary


def test_graceful_on_git_failure():
    """Test that function works gracefully when git commands fail."""

    def failing_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    with patch("superpower_workflow.context.subprocess.run", side_effect=failing_run):
        summary = build_context_summary(completed=["m1"], project_root=Path("/tmp"))
    assert "m1" in summary


def test_claude_md_pointer():
    """Test that output mentions CLAUDE.md."""
    summary = build_context_summary(completed=["m1"], project_root=Path("/tmp"))
    assert "CLAUDE.md" in summary


def test_no_completed_still_works_with_milestone():
    """Test that with no completed milestones, returns 'No prior milestones.' even with current_milestone."""
    ms = {"name": "m1", "depends_on": []}
    summary = build_context_summary(completed=[], project_root=Path("/tmp"), current_milestone=ms)
    assert summary == "No prior milestones."
