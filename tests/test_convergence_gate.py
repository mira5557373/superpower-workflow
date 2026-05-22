"""Tests for convergence gate hook."""

import json

import pytest

from superpower_workflow.hooks.convergence_gate import compute_exit_code


def _write(claude_dir, phase=None, gap_report=None):
    """Helper to write phase and gap report files."""
    claude_dir.mkdir(parents=True, exist_ok=True)
    if phase:
        (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase))
    if gap_report:
        (claude_dir / ".gap-report.json").write_text(json.dumps(gap_report))


@pytest.fixture
def tmp_claude_dir(tmp_path):
    """Create a temporary .claude directory for testing."""
    return tmp_path / ".claude"


class TestNoPhaseState:
    """Test when phase state is missing."""

    def test_no_phase_state_allows_stop(self, tmp_claude_dir):
        """No .workflow-phase.json → exit 0."""
        _write(tmp_claude_dir)
        code = compute_exit_code(tmp_claude_dir)
        assert code == 0


class TestCriticalGaps:
    """Test when critical gaps exist."""

    def test_critical_gaps_block_stop(self, tmp_claude_dir):
        """critical_gaps=2 → exit 2."""
        phase = {"phase": "review", "iteration": 0, "max_iterations": 5}
        gap_report = {
            "critical_gaps": 2,
            "important_gaps": 0,
            "tests_green": True,
            "lint_clean": True,
        }
        _write(tmp_claude_dir, phase=phase, gap_report=gap_report)
        code = compute_exit_code(tmp_claude_dir)
        assert code == 2


class TestConvergenceUltrathink:
    """Test ultrathink phase convergence logic."""

    def test_converged_allows_stop(self, tmp_claude_dir):
        """critical=0, important=2, previous=5 → exit 0 (2<=3)."""
        phase = {
            "phase": "ultrathink",
            "iteration": 0,
            "max_iterations": 5,
            "previous_important_gaps": 5,
        }
        gap_report = {
            "critical_gaps": 0,
            "important_gaps": 2,
            "tests_green": True,
            "lint_clean": True,
        }
        _write(tmp_claude_dir, phase=phase, gap_report=gap_report)
        code = compute_exit_code(tmp_claude_dir)
        assert code == 0


class TestMaxIterations:
    """Test max iterations limit."""

    def test_max_iterations_allows_stop(self, tmp_claude_dir):
        """iteration=5, max=5, critical=3 → exit 0."""
        phase = {"phase": "ultrathink", "iteration": 5, "max_iterations": 5}
        gap_report = {
            "critical_gaps": 3,
            "important_gaps": 0,
            "tests_green": True,
            "lint_clean": True,
        }
        _write(tmp_claude_dir, phase=phase, gap_report=gap_report)
        code = compute_exit_code(tmp_claude_dir)
        assert code == 0


class TestNoGapReport:
    """Test when gap report is missing."""

    def test_no_gap_report_blocks_stop(self, tmp_claude_dir):
        """phase exists but no gap report → exit 2."""
        phase = {"phase": "ultrathink", "iteration": 0, "max_iterations": 5}
        _write(tmp_claude_dir, phase=phase)
        code = compute_exit_code(tmp_claude_dir)
        assert code == 2


class TestReviewPhase:
    """Test review phase specific logic."""

    def test_review_phase_requires_zero_important(self, tmp_claude_dir):
        """review phase, important=1 → exit 2."""
        phase = {"phase": "review", "iteration": 0, "max_iterations": 5}
        gap_report = {
            "critical_gaps": 0,
            "important_gaps": 1,
            "tests_green": True,
            "lint_clean": True,
        }
        _write(tmp_claude_dir, phase=phase, gap_report=gap_report)
        code = compute_exit_code(tmp_claude_dir)
        assert code == 2

    def test_review_tests_not_green_blocks(self, tmp_claude_dir):
        """review phase, tests_green=False → exit 2."""
        phase = {"phase": "review", "iteration": 0, "max_iterations": 5}
        gap_report = {
            "critical_gaps": 0,
            "important_gaps": 0,
            "tests_green": False,
            "lint_clean": True,
        }
        _write(tmp_claude_dir, phase=phase, gap_report=gap_report)
        code = compute_exit_code(tmp_claude_dir)
        assert code == 2


class TestIterationUpdates:
    """Test phase state updates on block."""

    def test_hook_updates_previous_important_on_block(self, tmp_claude_dir):
        """after exit 2, check phase file updated with iteration+1 and previous_important_gaps set."""
        _write(tmp_claude_dir)
        phase = {"phase": "ultrathink", "iteration": 1, "max_iterations": 5}
        gap_report = {
            "critical_gaps": 0,
            "important_gaps": 4,
            "tests_green": True,
            "lint_clean": True,
        }
        _write(tmp_claude_dir, phase=phase, gap_report=gap_report)

        code = compute_exit_code(tmp_claude_dir)
        assert code == 2

        updated_phase = json.loads((tmp_claude_dir / ".workflow-phase.json").read_text())
        assert updated_phase["iteration"] == 2
        assert updated_phase["previous_important_gaps"] == 4


class TestMalformedGapReport:
    """Test error handling for malformed gap report."""

    def test_malformed_gap_report_blocks(self, tmp_claude_dir):
        """invalid JSON in gap report → exit 2."""
        tmp_claude_dir.mkdir(parents=True, exist_ok=True)
        phase = {"phase": "ultrathink", "iteration": 0, "max_iterations": 5}
        (tmp_claude_dir / ".workflow-phase.json").write_text(json.dumps(phase))
        (tmp_claude_dir / ".gap-report.json").write_text("{invalid json")

        code = compute_exit_code(tmp_claude_dir)
        assert code == 2
