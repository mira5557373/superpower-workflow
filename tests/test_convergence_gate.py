"""Tests for convergence gate hook."""

import json
from pathlib import Path

import pytest

from superpower_workflow.hooks.convergence_gate import _is_stuck, compute_exit_code


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


class TestIsStuck:
    """Test _is_stuck loop detection function."""

    def test_detects_repeated_gaps_with_different_line_numbers(self):
        current = [
            "[ultrathink] Store.put missing error at store.py:45",
            "[ultrathink] No validation",
        ]
        previous = [
            "[ultrathink] Store.put missing error at store.py:47",
            "[ultrathink] No validation",
        ]
        assert _is_stuck(current, previous) is True

    def test_allows_new_gaps(self):
        current = ["[ultrathink] New gap A", "[ultrathink] New gap B"]
        previous = ["[ultrathink] Old gap X", "[ultrathink] Old gap Y"]
        assert _is_stuck(current, previous) is False

    def test_handles_empty_current(self):
        assert _is_stuck([], ["some gap"]) is False

    def test_handles_empty_previous(self):
        assert _is_stuck(["some gap"], []) is False

    def test_handles_both_empty(self):
        assert _is_stuck([], []) is False

    def test_strips_path_prefixes(self):
        current = ["[ultrathink] Missing handler in src/handlers/auth.py"]
        previous = ["[ultrathink] Missing handler in handlers/auth.py"]
        assert _is_stuck(current, previous) is True

    def test_partial_overlap_below_threshold(self):
        current = ["gap A", "gap B", "gap C", "gap D", "gap E"]
        previous = ["gap A", "gap B", "gap C", "gap X", "gap Y"]
        # 3/5 = 60% overlap, below 80% threshold
        assert _is_stuck(current, previous) is False


class TestLoopDetectionIntegration:
    """Test loop detection wired into compute_exit_code."""

    def test_stuck_loop_allows_stop(self, tmp_claude_dir):
        """Repeated gaps across iterations -> exit 0 (allow stop)."""
        summaries = ["[ultrathink] Same gap A", "[ultrathink] Same gap B"]
        _write(
            tmp_claude_dir,
            phase={
                "phase": "ultrathink",
                "iteration": 2,
                "max_iterations": 5,
                "previous_important_gaps": 3,
                "previous_gap_summaries": summaries,
            },
            gap_report={
                "critical_gaps": 0,
                "important_gaps": 3,
                "tests_green": True,
                "lint_clean": True,
                "gap_summaries": summaries,
            },
        )
        assert compute_exit_code(tmp_claude_dir) == 0

    def test_not_stuck_continues_iteration(self, tmp_claude_dir):
        """Different gaps across iterations -> exit 2 (block stop)."""
        _write(
            tmp_claude_dir,
            phase={
                "phase": "ultrathink",
                "iteration": 1,
                "max_iterations": 5,
                "previous_important_gaps": 5,
                "previous_gap_summaries": [
                    "[ultrathink] Old gap X",
                    "[ultrathink] Old gap Y",
                ],
            },
            gap_report={
                "critical_gaps": 0,
                "important_gaps": 4,
                "tests_green": True,
                "lint_clean": True,
                "gap_summaries": [
                    "[ultrathink] New gap A",
                    "[ultrathink] New gap B",
                ],
            },
        )
        assert compute_exit_code(tmp_claude_dir) == 2

    def test_increment_stores_current_summaries(self, tmp_claude_dir):
        """After blocking, phase file stores current gap_summaries as previous."""
        _write(
            tmp_claude_dir,
            phase={
                "phase": "ultrathink",
                "iteration": 0,
                "max_iterations": 5,
            },
            gap_report={
                "critical_gaps": 0,
                "important_gaps": 5,
                "tests_green": True,
                "lint_clean": True,
                "gap_summaries": ["[ultrathink] Gap A", "[ultrathink] Gap B"],
            },
        )
        compute_exit_code(tmp_claude_dir)
        updated = json.loads((tmp_claude_dir / ".workflow-phase.json").read_text())
        assert updated["previous_gap_summaries"] == [
            "[ultrathink] Gap A",
            "[ultrathink] Gap B",
        ]


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


class TestGapValidatorIntegration:
    def _setup(self, tmp_path, phase_data=None, gap_data=None, config_data=None):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        if phase_data:
            (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase_data))
        if gap_data:
            (claude_dir / ".gap-report.json").write_text(json.dumps(gap_data))
        if config_data:
            (claude_dir / "workflow.json").write_text(json.dumps(config_data))
        return claude_dir

    def test_lenient_mode_logs_invalid_but_keeps_counts(self, tmp_path: Path):
        """In lenient mode, invalid gaps are warned but counts unchanged."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 2,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": [
                    "[ultrathink] nonexistent.py:999 has bug",
                    "[ultrathink] general concern",
                ],
            },
            config_data={"validation": {"gap_validator": True, "gap_validation_mode": "lenient"}},
        )
        code = compute_exit_code(claude_dir)
        assert code == 0

    def test_strict_mode_subtracts_invalid_gaps(self, tmp_path: Path):
        """In strict mode, invalid gaps reduce counts — convergence becomes easier."""
        (tmp_path / "real.py").write_text("x = 1\n")
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 1,
                "important_gaps": 2,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": [
                    "[ultrathink] nonexistent.py:99 critical bug",
                    "[ultrathink] real.py:1 needs fix",
                    "[ultrathink] general concern",
                ],
            },
            config_data={"validation": {"gap_validator": True, "gap_validation_mode": "strict"}},
        )
        code = compute_exit_code(claude_dir)
        assert code == 0

    def test_validator_disabled_no_change(self, tmp_path: Path):
        """When gap_validator is False, no validation occurs."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 2,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": ["[ultrathink] concern"],
            },
            config_data={"validation": {"gap_validator": False}},
        )
        code = compute_exit_code(claude_dir)
        assert code == 0

    def test_no_config_no_validation(self, tmp_path: Path):
        """When no workflow.json exists, validation is skipped."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 1,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": ["[ultrathink] concern"],
            },
        )
        code = compute_exit_code(claude_dir)
        assert code == 0

    def test_writes_gap_validation_json(self, tmp_path: Path):
        """Validation writes .gap-validation.json output."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 1,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": ["[ultrathink] concern"],
            },
            config_data={"validation": {"gap_validator": True, "gap_validation_mode": "lenient"}},
        )
        compute_exit_code(claude_dir)
        validation_path = claude_dir / ".gap-validation.json"
        assert validation_path.exists()
        data = json.loads(validation_path.read_text())
        assert "total_gaps" in data
