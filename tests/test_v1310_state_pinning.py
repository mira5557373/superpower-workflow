"""v1.3.10 fix (parallel soak finding): _accumulate_cost must write state
to the PARENT project's .claude/, not the worker's worktree.

Background: v1.3.8 Edit A made Orchestrator.claude_dir a thread-local
property that resolves to the worker's worktree path inside a
_worker_context. That's correct for per-milestone report paths
(.gap-report.json, .spec-compliance.json), but WRONG for run-scoped
state (workflow-state.json).

The parallel soak proved this in vivo:
- Parent state showed total_cost_usd=$0.0000
- Worker worktrees held $1.1073 and $1.6561 of real spend
- Budget cap couldn't see real spend

v1.3.10 pins _accumulate_cost's save_state to Path(self.root)/.claude
regardless of any active _worker_context.
"""

from __future__ import annotations

import json
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
        "max_total_budget_usd": 100,
    }
    (claude_dir / "workflow.json").write_text(json.dumps(cfg))
    save_state(claude_dir, WorkflowState())
    return Orchestrator(project_root=tmp_path)


class TestAccumulateCostPinsToParentState:
    """Inside _worker_context, _accumulate_cost must still write to the
    parent project's state, not the worktree's."""

    def test_cost_lands_in_parent_not_worker_worktree(self, tmp_path):
        """The soak case: worker calls _accumulate_cost inside its
        _worker_context. Parent's state.json must reflect the cost."""
        orch = _mk_orch(tmp_path)

        # Set up a worktree-like directory
        worktree = tmp_path / ".worktrees" / "M-test"
        worktree.mkdir(parents=True)
        worker_claude = worktree / ".claude"
        worker_claude.mkdir()

        # Enter the worker context (mimics what _run_parallel.run_fn does)
        with orch._worker_context(str(worktree), worker_claude):
            orch._accumulate_cost(0.0, 1.5)

        # Parent's state must have the cost
        parent_state = load_state(tmp_path / ".claude")
        assert parent_state.total_cost_usd == 1.5, (
            f"parent state should hold the cost; got ${parent_state.total_cost_usd}"
        )

        # Worker's state file must NOT have been created/modified by
        # _accumulate_cost (the soak's bug was that this received the cost)
        worker_state_path = worker_claude / "workflow-state.json"
        assert not worker_state_path.exists() or load_state(
            worker_claude
        ).total_cost_usd == 0.0, (
            "Worker worktree's state must NOT receive the cost"
        )

    def test_two_concurrent_workers_both_credit_parent(self, tmp_path):
        """Two simultaneous worker contexts both charge the parent state."""
        import threading

        orch = _mk_orch(tmp_path)
        worker_a = tmp_path / ".worktrees" / "A"
        worker_b = tmp_path / ".worktrees" / "B"
        for wt in (worker_a, worker_b):
            (wt / ".claude").mkdir(parents=True)

        barrier = threading.Barrier(2)

        def worker(wt: Path, amount: float):
            with orch._worker_context(str(wt), wt / ".claude"):
                barrier.wait()  # both inside contexts before either charges
                orch._accumulate_cost(0.0, amount)

        t1 = threading.Thread(target=worker, args=(worker_a, 1.10))
        t2 = threading.Thread(target=worker, args=(worker_b, 1.65))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Parent should hold the SUM (state.total_cost_usd is shared).
        parent_state = load_state(tmp_path / ".claude")
        assert abs(parent_state.total_cost_usd - (1.10 + 1.65)) < 1e-6, (
            f"parent should hold $2.75; got ${parent_state.total_cost_usd}"
        )

        # Neither worker worktree state should contain the cost.
        for wt in (worker_a, worker_b):
            wt_state_path = wt / ".claude" / "workflow-state.json"
            if wt_state_path.exists():
                wt_state = load_state(wt / ".claude")
                assert wt_state.total_cost_usd == 0.0, (
                    f"worktree {wt} must not hold cost; got ${wt_state.total_cost_usd}"
                )


class TestSequentialModeStillWorks:
    """Outside any _worker_context, _accumulate_cost continues to write
    to the parent (which IS the same as self.claude_dir in sequential mode)."""

    def test_sequential_mode_writes_to_claude_dir(self, tmp_path):
        orch = _mk_orch(tmp_path)
        orch._accumulate_cost(0.0, 0.42)
        # State is the project's .claude/.
        s = load_state(tmp_path / ".claude")
        assert s.total_cost_usd == 0.42


class TestSoakReproduction:
    """Reproduce the dollar amounts observed in the parallel soak.

    Worker cli-m2 spent $1.1073; worker foundation-m1 spent $1.6561.
    Pre-fix, those landed in the worktree states. Post-fix, they land
    in the parent state (sum = $2.7634).
    """

    def test_exact_soak_pattern(self, tmp_path):
        import threading

        orch = _mk_orch(tmp_path)
        cli_m2 = tmp_path / ".worktrees" / "cli-m2-commands-and-quality"
        foundation_m1 = tmp_path / ".worktrees" / "foundation-m1-db-layer"
        for wt in (cli_m2, foundation_m1):
            (wt / ".claude").mkdir(parents=True)

        def worker(wt: Path, amount: float):
            with orch._worker_context(str(wt), wt / ".claude"):
                orch._accumulate_cost(0.0, amount)

        t1 = threading.Thread(target=worker, args=(cli_m2, 1.1073))
        t2 = threading.Thread(target=worker, args=(foundation_m1, 1.6561))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        parent_state = load_state(tmp_path / ".claude")
        assert abs(parent_state.total_cost_usd - 2.7634) < 1e-3, (
            f"parent should hold $2.7634 (the soak's real spend); "
            f"got ${parent_state.total_cost_usd}"
        )
