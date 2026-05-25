from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.worktree import WorktreeManager


@dataclass
class CandidateResult:
    index: int
    model: str
    worktree: str
    tests_passing: bool = False
    lint_clean: bool = False
    gap_count: int = 0
    cost_usd: float = 0.0
    quality_score: float = 0.0


def score_candidate(c: CandidateResult) -> float:
    score = 0.0
    if c.tests_passing:
        score += 0.5
    if c.lint_clean:
        score += 0.2
    gap_penalty = min(c.gap_count * 0.03, 0.3)
    score += 0.3 - gap_penalty
    return max(0.0, min(1.0, score))


class BestOfNRunner:
    def __init__(
        self,
        n: int,
        budget: ThreadSafeBudget,
        worktree_mgr: WorktreeManager,
    ) -> None:
        self._n = max(1, n)
        self._budget = budget
        self._worktree_mgr = worktree_mgr

    def run(
        self,
        milestone: str,
        run_fn: Callable[[str, str], CandidateResult],
    ) -> CandidateResult:
        worktree_names = [f"{milestone}-bon-{i}" for i in range(self._n)]
        worktrees = {}
        for name in worktree_names:
            wt = self._worktree_mgr.create(name)
            worktrees[name] = wt

        candidates: list[CandidateResult] = []
        with ThreadPoolExecutor(max_workers=self._n) as pool:
            futures = {
                pool.submit(run_fn, milestone, str(worktrees[name].path)): name
                for name in worktree_names
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    result.quality_score = score_candidate(result)
                    candidates.append(result)
                except Exception:
                    pass

        if not candidates:
            for name in worktree_names:
                self._worktree_mgr.remove(name, prune_branch=True)
            raise RuntimeError(f"All {self._n} candidates failed for {milestone}")

        winner = max(candidates, key=lambda c: c.quality_score)
        winner_wt_name = worktree_names[winner.index]
        self._worktree_mgr.merge(winner_wt_name)

        for name in worktree_names:
            self._worktree_mgr.remove(name, prune_branch=True)

        return winner
