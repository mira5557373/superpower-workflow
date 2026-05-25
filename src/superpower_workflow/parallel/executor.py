from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING

from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.planner import ExecutionWave

if TYPE_CHECKING:
    from superpower_workflow.parallel.worktree import WorktreeInfo, WorktreeManager


@dataclass
class ParallelResult:
    milestone: str
    success: bool
    cost_usd: float = 0.0
    worktree: str = ""
    error: str | None = None
    duration_ms: int = 0


class ParallelExecutor:
    def __init__(
        self,
        budget: ThreadSafeBudget,
        max_workers: int = 4,
        worktree_mgr: WorktreeManager | None = None,
    ) -> None:
        self._budget = budget
        self._max_workers = max_workers
        self._worktree_mgr = worktree_mgr

    def execute_wave(
        self,
        wave: ExecutionWave,
        run_fn: Callable[[str, str], ParallelResult],
        cwd: str = ".",
    ) -> list[ParallelResult]:
        if not wave.milestones:
            return []

        results: list[ParallelResult] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._safe_run, run_fn, name, cwd): name for name in wave.milestones
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)

        return results

    def execute_wave_isolated(
        self,
        wave: ExecutionWave,
        run_fn: Callable[[str, str], ParallelResult],
    ) -> list[ParallelResult]:
        if not wave.milestones or not self._worktree_mgr:
            return self.execute_wave(wave, run_fn)

        worktrees: dict[str, WorktreeInfo] = {}
        for name in wave.milestones:
            wt = self._worktree_mgr.create(name)
            worktrees[name] = wt

        def isolated_run(name: str, _cwd: str) -> ParallelResult:
            wt_path = str(worktrees[name].path)
            return run_fn(name, wt_path)

        try:
            results = self.execute_wave(wave, run_fn=isolated_run)

            for result in results:
                if result.success:
                    self._worktree_mgr.merge(result.milestone)

            return results
        finally:
            for name in wave.milestones:
                self._worktree_mgr.remove(name, prune_branch=True)

    def _safe_run(
        self,
        run_fn: Callable[[str, str], ParallelResult],
        name: str,
        cwd: str,
    ) -> ParallelResult:
        try:
            return run_fn(name, cwd)
        except Exception as e:
            return ParallelResult(
                milestone=name,
                success=False,
                error=str(e),
                worktree=cwd,
            )
