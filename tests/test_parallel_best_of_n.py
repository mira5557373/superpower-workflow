from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from superpower_workflow.parallel.best_of_n import (
    BestOfNRunner,
    CandidateResult,
    score_candidate,
)
from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.worktree import MergeResult, WorktreeInfo, WorktreeManager


class TestScoreCandidate:
    def test_all_green_high_score(self):
        c = CandidateResult(
            index=0,
            model="opus",
            worktree="wt0",
            tests_passing=True,
            lint_clean=True,
            gap_count=0,
            cost_usd=5.0,
        )
        assert score_candidate(c) > 0.8

    def test_tests_failing_penalized(self):
        passing = CandidateResult(
            index=0,
            model="opus",
            worktree="wt0",
            tests_passing=True,
            lint_clean=True,
            gap_count=2,
            cost_usd=5.0,
        )
        failing = CandidateResult(
            index=1,
            model="opus",
            worktree="wt1",
            tests_passing=False,
            lint_clean=True,
            gap_count=2,
            cost_usd=5.0,
        )
        assert score_candidate(passing) > score_candidate(failing)

    def test_fewer_gaps_scores_higher(self):
        few = CandidateResult(
            index=0,
            model="opus",
            worktree="wt0",
            tests_passing=True,
            lint_clean=True,
            gap_count=1,
            cost_usd=5.0,
        )
        many = CandidateResult(
            index=1,
            model="opus",
            worktree="wt1",
            tests_passing=True,
            lint_clean=True,
            gap_count=10,
            cost_usd=5.0,
        )
        assert score_candidate(few) > score_candidate(many)

    def test_lint_clean_bonus(self):
        clean = CandidateResult(
            index=0,
            model="opus",
            worktree="wt0",
            tests_passing=True,
            lint_clean=True,
            gap_count=3,
            cost_usd=5.0,
        )
        dirty = CandidateResult(
            index=1,
            model="opus",
            worktree="wt1",
            tests_passing=True,
            lint_clean=False,
            gap_count=3,
            cost_usd=5.0,
        )
        assert score_candidate(clean) > score_candidate(dirty)

    def test_score_between_zero_and_one(self):
        c = CandidateResult(
            index=0,
            model="opus",
            worktree="wt0",
            tests_passing=False,
            lint_clean=False,
            gap_count=100,
            cost_usd=50.0,
        )
        assert 0.0 <= score_candidate(c) <= 1.0


class TestBestOfNRunner:
    def _make_runner(self, n: int = 3, budget: float = 500.0):
        budget_obj = ThreadSafeBudget(budget)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=Path(f"/tmp/wt/{name}"), branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(success=True, merged_branch="", conflicts=[])
        return BestOfNRunner(n=n, budget=budget_obj, worktree_mgr=mock_mgr), mock_mgr

    def test_runs_n_candidates(self):
        runner, mock_mgr = self._make_runner(n=3)
        call_count = {"n": 0}

        def run_fn(name: str, cwd: str) -> CandidateResult:
            idx = call_count["n"]
            call_count["n"] += 1
            return CandidateResult(
                index=idx,
                model="opus",
                worktree=cwd,
                tests_passing=True,
                lint_clean=True,
                gap_count=idx,
                cost_usd=5.0,
            )

        winner = runner.run("m1", run_fn=run_fn)
        assert call_count["n"] == 3
        assert winner.gap_count == 0

    def test_selects_highest_scoring_candidate(self):
        runner, mock_mgr = self._make_runner(n=3)
        candidates = [
            CandidateResult(
                index=0,
                model="opus",
                worktree="wt0",
                tests_passing=True,
                lint_clean=True,
                gap_count=5,
                cost_usd=5.0,
            ),
            CandidateResult(
                index=1,
                model="sonnet",
                worktree="wt1",
                tests_passing=True,
                lint_clean=True,
                gap_count=0,
                cost_usd=3.0,
            ),
            CandidateResult(
                index=2,
                model="haiku",
                worktree="wt2",
                tests_passing=False,
                lint_clean=True,
                gap_count=2,
                cost_usd=1.0,
            ),
        ]

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return candidates.pop(0)

        winner = runner.run("m1", run_fn=run_fn)
        assert winner.index == 1
        assert winner.gap_count == 0

    def test_merges_only_winner(self):
        runner, mock_mgr = self._make_runner(n=2)
        candidates = [
            CandidateResult(
                index=0,
                model="opus",
                worktree="wt0",
                tests_passing=True,
                lint_clean=True,
                gap_count=5,
                cost_usd=5.0,
            ),
            CandidateResult(
                index=1,
                model="opus",
                worktree="wt1",
                tests_passing=True,
                lint_clean=True,
                gap_count=0,
                cost_usd=5.0,
            ),
        ]

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return candidates.pop(0)

        runner.run("m1", run_fn=run_fn)
        assert mock_mgr.merge.call_count == 1

    def test_cleans_up_all_worktrees(self):
        runner, mock_mgr = self._make_runner(n=3)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return CandidateResult(
                index=0,
                model="opus",
                worktree=cwd,
                tests_passing=True,
                lint_clean=True,
                gap_count=0,
                cost_usd=5.0,
            )

        runner.run("m1", run_fn=run_fn)
        assert mock_mgr.remove.call_count == 3

    def test_n_equals_one_no_comparison(self):
        runner, mock_mgr = self._make_runner(n=1)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return CandidateResult(
                index=0,
                model="opus",
                worktree=cwd,
                tests_passing=True,
                lint_clean=True,
                gap_count=0,
                cost_usd=5.0,
            )

        winner = runner.run("m1", run_fn=run_fn)
        assert winner is not None
        assert mock_mgr.create.call_count == 1

    def test_all_candidates_fail_raises(self):
        runner, mock_mgr = self._make_runner(n=2)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            raise RuntimeError("crash")

        with pytest.raises(RuntimeError, match="All 2 candidates failed"):
            runner.run("m1", run_fn=run_fn)
        assert mock_mgr.remove.call_count == 2

    def test_n_zero_treated_as_one(self):
        runner, mock_mgr = self._make_runner(n=0)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return CandidateResult(
                index=0,
                model="opus",
                worktree=cwd,
                tests_passing=True,
                lint_clean=True,
                gap_count=0,
                cost_usd=5.0,
            )

        winner = runner.run("m1", run_fn=run_fn)
        assert winner is not None
        assert mock_mgr.create.call_count == 1
