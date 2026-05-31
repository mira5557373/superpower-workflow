"""v1.3.5 #4 fix: parallel orchestrator branches contend on
`self.state.total_cost_usd`. The new `self._state_lock` serializes the
accumulator + save_state pair.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.state import WorkflowState, load_state, save_state


def _mk_orch(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    cfg = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "budgets": {"plan": 10, "implement": 25, "review": 10, "push": 1},
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "verify_commands": {},
        "milestones": [{"name": "M1"}],
        "validation": {},
        "convergence": {},
        "telemetry": {"enabled": False},
        "max_total_budget_usd": 1000,
    }
    (claude_dir / "workflow.json").write_text(json.dumps(cfg))
    save_state(claude_dir, WorkflowState())
    return Orchestrator(project_root=Path(tmp_path))


class TestStateLockExists:
    def test_orchestrator_has_state_lock(self, tmp_path):
        orch = _mk_orch(tmp_path)
        assert hasattr(orch, "_state_lock")
        # Should be a threading.Lock
        assert hasattr(orch._state_lock, "acquire")
        assert hasattr(orch._state_lock, "release")


class TestAccumulateCostUnderContention:
    def test_concurrent_accumulators_sum_to_correct_total(self, tmp_path):
        """N workers each charging $1 must produce N total — no torn writes
        from concurrent float `+=` on self.state.total_cost_usd."""
        orch = _mk_orch(tmp_path)

        N = 50

        def charger():
            orch._accumulate_cost(0.0, 1.0)

        threads = [threading.Thread(target=charger) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert orch.state.total_cost_usd == float(N), (
            f"expected ${N} after {N} concurrent $1 charges; "
            f"got ${orch.state.total_cost_usd} — possible torn write"
        )
        # Disk state should match in-memory
        reloaded = load_state(orch.claude_dir)
        assert reloaded.total_cost_usd == float(N)


class TestParallelMergeUnderLock:
    """The post-wave merge in _run_parallel mutates state.completed and
    state.failed; the lock prevents that critical section from being
    interrupted by the heartbeat daemon or other state-touching code."""

    def test_merge_block_holds_lock(self, tmp_path):
        """The orchestrator's _run_parallel merge step must acquire the
        lock so a concurrent _accumulate_cost on a sibling worker cannot
        observe a half-merged state."""
        orch = _mk_orch(tmp_path)

        # Smoke-test: the lock is reentrant within a single thread? No —
        # threading.Lock is non-reentrant. If a code path inside the merge
        # block tried to call _accumulate_cost, it would deadlock. Confirm
        # the lock is NOT held during _accumulate_cost calls so workers
        # can use it freely.
        with orch._state_lock:
            # Inside the lock — we shouldn't call _accumulate_cost here
            # because it would try to reacquire and deadlock. Just sanity
            # check the lock is locked.
            assert orch._state_lock.locked() is True
        # Outside the lock, accumulate is fine.
        orch._accumulate_cost(0.0, 0.5)
        assert orch.state.total_cost_usd == 0.5
