"""v1.3.4 #15: cost is persisted to state INCREMENTALLY after every Claude
call, not just at milestone completion.

Pre-fix: a milestone whose Phase B raised _PhaseError lost every dollar
Phase A had already spent. A runaway spec retrying 3 times could spend
~3x max_total_budget_usd before the budget check noticed.

Post-fix: every accumulator update via _accumulate_cost charges
self.state.total_cost_usd and persists state to disk; retry's budget
check at the top of the next iteration sees the spent money.
"""

from __future__ import annotations

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.state import WorkflowState, save_state


def _mk_orch(tmp_path):
    """Construct a minimal Orchestrator pinned to tmp_path."""
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
    (claude_dir / "workflow.json").write_text(__import__("json").dumps(cfg))
    state = WorkflowState()
    save_state(claude_dir, state)
    orch = Orchestrator(project_root=tmp_path)
    return orch


class TestAccumulateCostPersists:
    def test_accumulate_updates_state_and_returns_new_local(self, tmp_path):
        orch = _mk_orch(tmp_path)
        # Initial state.
        assert orch.state.total_cost_usd == 0.0
        new = orch._accumulate_cost(0.0, 1.50)
        assert new == 1.50
        assert orch.state.total_cost_usd == 1.50

        new = orch._accumulate_cost(new, 0.75)
        assert new == 2.25
        assert orch.state.total_cost_usd == 2.25

    def test_accumulate_persists_to_disk(self, tmp_path):
        from superpower_workflow.state import load_state

        orch = _mk_orch(tmp_path)
        orch._accumulate_cost(0.0, 4.99)
        # Reload from disk in a fresh state instance.
        reloaded = load_state(orch.claude_dir)
        assert reloaded.total_cost_usd == 4.99

    def test_zero_delta_is_a_noop(self, tmp_path):
        """Don't churn the disk for free charges."""
        orch = _mk_orch(tmp_path)
        from superpower_workflow.state import STATE_FILE

        state_path = orch.claude_dir / STATE_FILE
        # Touch baseline mtime
        save_state(orch.claude_dir, orch.state)
        m0 = state_path.stat().st_mtime
        orch._accumulate_cost(5.0, 0.0)
        m1 = state_path.stat().st_mtime
        assert m0 == m1, "zero delta should NOT trigger a disk write"

    def test_accumulate_survives_oserror_on_save(self, tmp_path, monkeypatch):
        """Transient I/O failure during save_state must not abort the
        milestone; cost stays in memory and the next charge retries."""
        orch = _mk_orch(tmp_path)
        from superpower_workflow import orchestrator as orch_mod

        def boom(claude_dir, state):
            raise OSError("disk full")

        monkeypatch.setattr(orch_mod, "save_state", boom)
        # Must not raise.
        new = orch._accumulate_cost(0.0, 1.0)
        assert new == 1.0
        # State is still bumped in memory even if disk write failed.
        assert orch.state.total_cost_usd == 1.0


class TestRetryBudgetCheck:
    """v1.3.4 #15 acceptance: a retry sees previously spent cost."""

    def test_failed_milestone_cost_visible_on_next_iteration(self, tmp_path):
        """Simulate phase A spending money then phase B raising; verify
        the recorded cost survives the exception."""
        from superpower_workflow.orchestrator import _PhaseError

        orch = _mk_orch(tmp_path)

        def fake_run_milestone():
            # Phase A spends $3
            orch._accumulate_cost(0.0, 3.0)
            # Phase B raises mid-milestone
            raise _PhaseError("implement", "synthetic failure")

        import contextlib

        with contextlib.suppress(_PhaseError):
            fake_run_milestone()

        # Cost from Phase A must be persisted.
        from superpower_workflow.state import load_state

        reloaded = load_state(orch.claude_dir)
        assert reloaded.total_cost_usd == 3.0, (
            f"expected $3 persisted after Phase A; got ${reloaded.total_cost_usd}"
        )

    def test_three_retries_dont_multiply_budget(self, tmp_path):
        """A spec that fails 3 times after spending $X per attempt must NOT
        spend 3*budget before the budget check trips. Pre-fix this was the
        runaway-cost bug; post-fix the budget check sees cumulative spend."""
        from superpower_workflow.orchestrator import _PhaseError

        orch = _mk_orch(tmp_path)
        max_budget = 10.0

        for _attempt in range(3):
            # Budget gate (mirrors orchestrator line ~327)
            if orch.state.total_cost_usd >= max_budget:
                break
            # Each attempt spends $4 in Phase A then fails Phase B.
            orch._accumulate_cost(0.0, 4.0)
            try:
                raise _PhaseError("implement", "boom")
            except _PhaseError:
                continue

        # Pre-fix: total_cost_usd was 0.0 every iteration (lost across retries)
        # so all 3 attempts ran → 3 * $4 = $12 spent unchecked.
        # Post-fix: after 2 attempts ($8) we're under budget; after 3rd ($12)
        # the loop's next check would fire. Critical: cost is preserved.
        assert orch.state.total_cost_usd >= 8.0, (
            "cost must accumulate across attempts so the budget cap is enforceable"
        )


class TestEndToEndIncremental:
    """Sanity: cost increments visible in state on disk after each charge."""

    def test_disk_state_grows_monotonically(self, tmp_path):
        from superpower_workflow.state import load_state

        orch = _mk_orch(tmp_path)
        deltas = [1.0, 0.5, 0.25, 2.0]
        running = 0.0
        for d in deltas:
            orch._accumulate_cost(0.0, d)
            running += d
            on_disk = load_state(orch.claude_dir).total_cost_usd
            assert abs(on_disk - running) < 1e-6, (
                f"after charging ${d}, disk shows ${on_disk}, expected ${running}"
            )
