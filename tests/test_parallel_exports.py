from __future__ import annotations


class TestParallelPackageExports:
    def test_all_public_types_exported(self):
        from superpower_workflow.parallel import __all__

        expected = {
            "ThreadSafeBudget",
            "WorktreeManager",
            "WorktreeInfo",
            "MergeResult",
            "ModelRouter",
            "ComplexityScore",
            "RouteDecision",
            "RoutingRule",
            "score_complexity",
            "DependencyGraph",
            "ExecutionWave",
            "ParallelPlanner",
            "ParallelExecutor",
            "ParallelResult",
            "BestOfNRunner",
            "CandidateResult",
            "score_candidate",
            "RemoteConfig",
            "RemoteRunner",
            "RemoteResult",
        }
        assert set(__all__) == expected

    def test_imports_resolve(self):
        from superpower_workflow.parallel import (
            BestOfNRunner,
            ModelRouter,
            ParallelExecutor,
            ParallelPlanner,
            RemoteRunner,
            ThreadSafeBudget,
            WorktreeManager,
        )

        assert ThreadSafeBudget is not None
        assert WorktreeManager is not None
        assert ModelRouter is not None
        assert ParallelPlanner is not None
        assert ParallelExecutor is not None
        assert BestOfNRunner is not None
        assert RemoteRunner is not None
