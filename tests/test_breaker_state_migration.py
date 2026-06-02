"""v1.3.26 — backward-compat regression test for WorkflowState.breaker_window.

Pre-v1.3.26 workflow-state.json files lack the `breaker_window` field.
Loading them must not raise; the field defaults to an empty list.
"""

from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.state import WorkflowState, load_state


def test_pre_v1326_state_loads_with_empty_breaker_window(tmp_path: Path) -> None:
    """Loading a state file without `breaker_window` defaults to []."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    legacy_state = {
        "current_milestone_index": 0,
        "current_step": "plan",
        "completed": [],
        "failed": [],
        "skipped": [],
        "total_cost_usd": 0.0,
        "run_id": "20260601-000000",
        "started_at": "2026-06-01T00:00:00Z",
        # NOTE: no `breaker_window` key — simulates pre-v1.3.26 state.
    }
    (claude_dir / "workflow-state.json").write_text(json.dumps(legacy_state), encoding="utf-8")

    state = load_state(claude_dir)
    assert state.breaker_window == []  # defaulted, no raise


def test_v1326_state_roundtrip_preserves_window(tmp_path: Path) -> None:
    """A WorkflowState with breaker_window entries round-trips through JSON."""
    from superpower_workflow.state import save_state

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    state = WorkflowState(
        run_id="20260602-test",
        breaker_window=[
            {
                "milestone_name": "M1",
                "primary_class": "policy_violation",
                "confidence": 1.0,
                "triage_event_id": "ev-1",
                "ts": "2026-06-02T00:00:00Z",
            }
        ],
    )
    save_state(claude_dir, state)
    reloaded = load_state(claude_dir)
    assert len(reloaded.breaker_window) == 1
    assert reloaded.breaker_window[0]["primary_class"] == "policy_violation"


def test_state_missing_file_returns_empty_breaker_window(tmp_path: Path) -> None:
    """No state file at all → fresh WorkflowState with empty list."""
    state = load_state(tmp_path / ".claude")
    assert state.breaker_window == []
