"""Tests for state management module."""

import json

import pytest

from superpower_workflow.state import (
    GAP_REPORT_FILE,
    LOCK_FILE,
    PHASE_FILE,
    STATE_FILE,
    PhaseState,
    WorkflowState,
    acquire_lock,
    clear_phase_state,
    load_config,
    load_phase_state,
    load_state,
    release_lock,
    save_phase_state,
    save_state,
)


@pytest.fixture
def tmp_claude_dir(tmp_path):
    """Create a temporary .claude directory for testing."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    return claude_dir


class TestLoadStateDefaults:
    """Test WorkflowState loading with defaults."""

    def test_load_state_returns_defaults_when_missing(self, tmp_claude_dir):
        """load_state returns default WorkflowState when file is missing."""
        state = load_state(tmp_claude_dir)

        assert state.current_milestone_index == 0
        assert state.current_step is None
        assert state.last_phase_session_id is None
        assert state.plan_commit_sha is None
        assert state.completed == []
        assert state.total_cost_usd == 0.0
        assert state.spec_sha == ""
        assert state.run_id == ""
        assert state.started_at == ""


class TestSaveAndLoadState:
    """Test WorkflowState save/load roundtrip."""

    def test_save_and_load_state_roundtrip(self, tmp_claude_dir):
        """save_state and load_state preserve all fields."""
        original = WorkflowState(
            current_milestone_index=3,
            current_step="implement_feature",
            last_phase_session_id="session-123",
            plan_commit_sha="abc1234",
            completed=["task1", "task2"],
            total_cost_usd=42.5,
            spec_sha="def5678",
            run_id="run-456",
            started_at="2026-05-22T10:00:00Z",
        )

        save_state(tmp_claude_dir, original)
        loaded = load_state(tmp_claude_dir)

        assert loaded.current_milestone_index == 3
        assert loaded.current_step == "implement_feature"
        assert loaded.last_phase_session_id == "session-123"
        assert loaded.plan_commit_sha == "abc1234"
        assert loaded.completed == ["task1", "task2"]
        assert loaded.total_cost_usd == 42.5
        assert loaded.spec_sha == "def5678"
        assert loaded.run_id == "run-456"
        assert loaded.started_at == "2026-05-22T10:00:00Z"

    def test_save_state_is_atomic(self, tmp_claude_dir):
        """save_state uses atomic write (no .tmp file lingers)."""
        state = WorkflowState(
            current_milestone_index=1,
            completed=["task1"],
        )

        save_state(tmp_claude_dir, state)

        # Verify the state file exists
        state_file = tmp_claude_dir / STATE_FILE
        assert state_file.exists()

        # Verify no .tmp file lingers
        tmp_file = tmp_claude_dir / f"{STATE_FILE}.tmp"
        assert not tmp_file.exists()

        # Verify the content is correct
        loaded = load_state(tmp_claude_dir)
        assert loaded.current_milestone_index == 1
        assert loaded.completed == ["task1"]


class TestPhaseState:
    """Test PhaseState creation, save/load, and clear."""

    def test_phase_state_create_and_clear(self, tmp_claude_dir):
        """save_phase_state and clear_phase_state work correctly."""
        phase = PhaseState(
            phase="brainstorming",
            iteration=2,
            max_iterations=5,
        )

        # Save
        save_phase_state(tmp_claude_dir, phase)
        phase_file = tmp_claude_dir / PHASE_FILE
        assert phase_file.exists()

        # Load
        loaded = load_phase_state(tmp_claude_dir)
        assert loaded is not None
        assert loaded.phase == "brainstorming"
        assert loaded.iteration == 2
        assert loaded.max_iterations == 5

        # Clear
        clear_phase_state(tmp_claude_dir)
        assert not phase_file.exists()

        # Load after clear returns None
        loaded_after_clear = load_phase_state(tmp_claude_dir)
        assert loaded_after_clear is None

    def test_phase_state_previous_important_gaps_tracking(self, tmp_claude_dir):
        """PhaseState tracks previous_important_gaps correctly."""
        phase = PhaseState(
            phase="implementation",
            iteration=1,
            max_iterations=5,
            previous_important_gaps=15,
        )

        save_phase_state(tmp_claude_dir, phase)
        loaded = load_phase_state(tmp_claude_dir)

        assert loaded is not None
        assert loaded.previous_important_gaps == 15

    def test_phase_state_gap_summaries_roundtrip(self, tmp_claude_dir):
        """PhaseState saves and loads previous_gap_summaries correctly."""
        phase = PhaseState(
            phase="ultrathink",
            iteration=2,
            max_iterations=5,
            previous_important_gaps=4,
            previous_gap_summaries=[
                "[ultrathink] Store.put missing error",
                "[ultrathink] No tests for edge case",
            ],
        )
        save_phase_state(tmp_claude_dir, phase)
        loaded = load_phase_state(tmp_claude_dir)
        assert loaded is not None
        assert loaded.previous_gap_summaries == [
            "[ultrathink] Store.put missing error",
            "[ultrathink] No tests for edge case",
        ]

    def test_phase_state_gap_summaries_default_empty(self, tmp_claude_dir):
        """PhaseState defaults previous_gap_summaries to empty list."""
        phase = PhaseState(phase="review", iteration=0)
        save_phase_state(tmp_claude_dir, phase)
        loaded = load_phase_state(tmp_claude_dir)
        assert loaded is not None
        assert loaded.previous_gap_summaries == []

    def test_load_phase_state_returns_none_when_missing(self, tmp_claude_dir):
        """load_phase_state returns None when phase file is missing."""
        loaded = load_phase_state(tmp_claude_dir)
        assert loaded is None


class TestLocking:
    """Test lock file operations."""

    def test_acquire_and_release_lock(self, tmp_claude_dir):
        """acquire_lock and release_lock work correctly."""
        lock_file = tmp_claude_dir / LOCK_FILE

        # Initially no lock
        assert not lock_file.exists()

        # Acquire lock
        acquired = acquire_lock(tmp_claude_dir)
        assert acquired is True
        assert lock_file.exists()

        # Release lock
        release_lock(tmp_claude_dir)
        assert not lock_file.exists()

    def test_lock_prevents_second_acquisition(self, tmp_claude_dir):
        """acquire_lock returns False if already locked."""
        # First acquisition succeeds
        acquired_first = acquire_lock(tmp_claude_dir)
        assert acquired_first is True

        # Second acquisition fails
        acquired_second = acquire_lock(tmp_claude_dir)
        assert acquired_second is False

        # After release, can acquire again
        release_lock(tmp_claude_dir)
        acquired_third = acquire_lock(tmp_claude_dir)
        assert acquired_third is True


class TestConfig:
    def test_load_config_valid(self, tmp_claude_dir):
        config = {
            "schema_version": 1,
            "spec": "spec.md",
            "model": "opus",
            "milestones": [],
        }
        (tmp_claude_dir / "workflow.json").write_text(json.dumps(config))
        loaded = load_config(tmp_claude_dir)
        assert loaded["model"] == "opus"
        assert loaded["schema_version"] == 1

    def test_load_config_missing_raises(self, tmp_claude_dir):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_claude_dir)


class TestGracefulHandling:
    """Test graceful handling of edge cases."""

    def test_clear_phase_state_handles_missing_files_gracefully(self, tmp_claude_dir):
        """clear_phase_state does not raise when files are missing."""
        # Both phase file and gap report file are missing
        assert not (tmp_claude_dir / PHASE_FILE).exists()
        assert not (tmp_claude_dir / GAP_REPORT_FILE).exists()

        # Should not raise
        clear_phase_state(tmp_claude_dir)

        # Still missing
        assert not (tmp_claude_dir / PHASE_FILE).exists()
        assert not (tmp_claude_dir / GAP_REPORT_FILE).exists()

    def test_clear_phase_state_removes_gap_report(self, tmp_claude_dir):
        """clear_phase_state also removes the gap report file."""
        # Create both files
        phase_file = tmp_claude_dir / PHASE_FILE
        gap_file = tmp_claude_dir / GAP_REPORT_FILE

        phase_file.write_text(json.dumps({"phase": "test"}))
        gap_file.write_text(json.dumps({"gaps": []}))

        assert phase_file.exists()
        assert gap_file.exists()

        clear_phase_state(tmp_claude_dir)

        assert not phase_file.exists()
        assert not gap_file.exists()
