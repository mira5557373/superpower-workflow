from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.executor import ParallelExecutor, ParallelResult
from superpower_workflow.parallel.planner import ExecutionWave
from superpower_workflow.parallel.worktree import MergeResult, WorktreeInfo, WorktreeManager


class TestParallelExecutor:
    def _make_executor(self, max_workers: int = 2, budget: float = 500.0):
        return ParallelExecutor(
            budget=ThreadSafeBudget(budget),
            max_workers=max_workers,
        )

    def test_execute_wave_runs_all_milestones(self):
        executor = self._make_executor()
        wave = ExecutionWave(index=0, milestones=["m1", "m2", "m3"])

        def run_fn(name: str, cwd: str) -> ParallelResult:
            return ParallelResult(
                milestone=name,
                success=True,
                cost_usd=5.0,
                worktree=cwd,
            )

        results = executor.execute_wave(wave, run_fn=run_fn)
        assert len(results) == 3
        names = {r.milestone for r in results}
        assert names == {"m1", "m2", "m3"}
        assert all(r.success for r in results)

    def test_execute_wave_respects_max_workers(self):
        concurrent_count = {"max": 0, "current": 0}
        lock = threading.Lock()

        def run_fn(name: str, cwd: str) -> ParallelResult:
            with lock:
                concurrent_count["current"] += 1
                concurrent_count["max"] = max(concurrent_count["max"], concurrent_count["current"])
            time.sleep(0.05)
            with lock:
                concurrent_count["current"] -= 1
            return ParallelResult(milestone=name, success=True, cost_usd=1.0, worktree=cwd)

        executor = self._make_executor(max_workers=2)
        wave = ExecutionWave(index=0, milestones=["m1", "m2", "m3", "m4"])
        executor.execute_wave(wave, run_fn=run_fn)
        assert concurrent_count["max"] <= 2

    def test_execute_wave_accumulates_cost(self):
        budget = ThreadSafeBudget(100.0)
        executor = ParallelExecutor(budget=budget, max_workers=2)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            budget.spend(10.0)
            return ParallelResult(milestone=name, success=True, cost_usd=10.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2", "m3"])
        executor.execute_wave(wave, run_fn=run_fn)
        assert budget.spent == 30.0

    def test_execute_wave_handles_failure(self):
        executor = self._make_executor()

        def run_fn(name: str, cwd: str) -> ParallelResult:
            if name == "m2":
                return ParallelResult(
                    milestone=name,
                    success=False,
                    cost_usd=3.0,
                    worktree=cwd,
                    error="Phase B failed",
                )
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2", "m3"])
        results = executor.execute_wave(wave, run_fn=run_fn)
        failed = [r for r in results if not r.success]
        assert len(failed) == 1
        assert failed[0].milestone == "m2"
        assert failed[0].error == "Phase B failed"

    def test_execute_wave_stops_on_budget_exhaustion(self):
        budget = ThreadSafeBudget(15.0)
        executor = ParallelExecutor(budget=budget, max_workers=1)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            cost = 10.0
            if not budget.spend(cost):
                return ParallelResult(
                    milestone=name,
                    success=False,
                    cost_usd=0.0,
                    worktree=cwd,
                    error="budget_exhausted",
                )
            return ParallelResult(milestone=name, success=True, cost_usd=cost, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2", "m3"])
        results = executor.execute_wave(wave, run_fn=run_fn)
        succeeded = [r for r in results if r.success]
        assert len(succeeded) == 1

    def test_execute_wave_exception_in_run_fn(self):
        executor = self._make_executor()

        def run_fn(name: str, cwd: str) -> ParallelResult:
            if name == "m2":
                raise RuntimeError("unexpected crash")
            return ParallelResult(milestone=name, success=True, cost_usd=1.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2", "m3"])
        results = executor.execute_wave(wave, run_fn=run_fn)
        m2 = [r for r in results if r.milestone == "m2"][0]
        assert m2.success is False
        assert "unexpected crash" in (m2.error or "")

    def test_execute_empty_wave(self):
        executor = self._make_executor()
        wave = ExecutionWave(index=0, milestones=[])
        results = executor.execute_wave(wave, run_fn=lambda n, c: None)
        assert results == []


class TestWorktreeIsolatedExecution:
    def test_creates_worktree_per_milestone(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(success=True, merged_branch="", conflicts=[])
        executor = ParallelExecutor(budget=budget, max_workers=2, worktree_mgr=mock_mgr)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2"])
        executor.execute_wave_isolated(wave, run_fn=run_fn)
        assert mock_mgr.create.call_count == 2

    def test_passes_worktree_path_as_cwd(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(success=True, merged_branch="", conflicts=[])
        executor = ParallelExecutor(budget=budget, max_workers=1, worktree_mgr=mock_mgr)
        cwds = []

        def run_fn(name: str, cwd: str) -> ParallelResult:
            cwds.append(cwd)
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1"])
        executor.execute_wave_isolated(wave, run_fn=run_fn)
        assert cwds[0] == "/tmp/wt/m1"

    def test_merges_successful_milestones(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(success=True, merged_branch="", conflicts=[])
        executor = ParallelExecutor(budget=budget, max_workers=2, worktree_mgr=mock_mgr)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2"])
        executor.execute_wave_isolated(wave, run_fn=run_fn)
        assert mock_mgr.merge.call_count == 2

    def test_skips_merge_for_failed_milestones(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(success=True, merged_branch="", conflicts=[])
        executor = ParallelExecutor(budget=budget, max_workers=2, worktree_mgr=mock_mgr)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            if name == "m2":
                return ParallelResult(
                    milestone=name, success=False, cost_usd=1.0, worktree=cwd, error="fail"
                )
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2"])
        executor.execute_wave_isolated(wave, run_fn=run_fn)
        merge_names = [
            c.args[0] if c.args else c.kwargs.get("name") for c in mock_mgr.merge.call_args_list
        ]
        assert "m1" in merge_names
        assert "m2" not in merge_names

    def test_cleans_up_worktrees_after_execution(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(success=True, merged_branch="", conflicts=[])
        executor = ParallelExecutor(budget=budget, max_workers=2, worktree_mgr=mock_mgr)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1"])
        executor.execute_wave_isolated(wave, run_fn=run_fn)
        assert mock_mgr.remove.call_count == 1

    def test_worktrees_cleaned_up_on_exception(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.side_effect = RuntimeError("merge exploded")
        executor = ParallelExecutor(budget=budget, max_workers=1, worktree_mgr=mock_mgr)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1"])
        with pytest.raises(RuntimeError, match="merge exploded"):
            executor.execute_wave_isolated(wave, run_fn=run_fn)
        assert mock_mgr.remove.call_count >= 1
