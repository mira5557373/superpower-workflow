from __future__ import annotations

import json

from superpower_workflow.telemetry import (
    BestOfNCompleted,
    ModelRouted,
    ParallelWaveCompleted,
    ParallelWaveStarted,
    RemoteExecution,
    WorktreeCreated,
    WorktreeMerged,
)


class TestParallelTelemetryEvents:
    def test_model_routed_event(self):
        e = ModelRouted(
            milestone="m1", model="sonnet", complexity_score=0.45, reason="score 0.45 >= 0.3"
        )
        d = e.to_dict()
        assert d["type"] == "model_routed"
        assert d["model"] == "sonnet"
        assert d["complexity_score"] == 0.45

    def test_parallel_wave_started_event(self):
        e = ParallelWaveStarted(wave_index=0, milestones=["m1", "m2"], worker_count=4)
        d = e.to_dict()
        assert d["type"] == "parallel_wave_started"
        assert d["milestones"] == ["m1", "m2"]

    def test_parallel_wave_completed_event(self):
        e = ParallelWaveCompleted(
            wave_index=0,
            succeeded=["m1"],
            failed=["m2"],
            total_cost_usd=15.0,
            duration_seconds=120.5,
        )
        d = e.to_dict()
        assert d["type"] == "parallel_wave_completed"
        assert d["succeeded"] == ["m1"]
        assert d["failed"] == ["m2"]

    def test_worktree_created_event(self):
        e = WorktreeCreated(milestone="m1", branch="sw-parallel/m1", worktree_path="/tmp/wt/m1")
        d = e.to_dict()
        assert d["type"] == "worktree_created"
        assert d["branch"] == "sw-parallel/m1"

    def test_worktree_merged_event(self):
        e = WorktreeMerged(milestone="m1", branch="sw-parallel/m1", success=True, conflicts=0)
        d = e.to_dict()
        assert d["type"] == "worktree_merged"
        assert d["success"] is True

    def test_best_of_n_completed_event(self):
        e = BestOfNCompleted(
            milestone="m1",
            n=3,
            winner_index=1,
            winner_model="sonnet",
            winner_score=0.95,
            total_cost_usd=30.0,
        )
        d = e.to_dict()
        assert d["type"] == "best_of_n_completed"
        assert d["winner_index"] == 1

    def test_remote_execution_event(self):
        e = RemoteExecution(milestone="m1", host="example.com", success=True, cost_usd=12.5)
        d = e.to_dict()
        assert d["type"] == "remote_execution"
        assert d["host"] == "example.com"

    def test_events_serialize_to_json(self):
        e = ModelRouted(milestone="m1", model="opus", complexity_score=0.8, reason="test")
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "model_routed"
        assert parsed["milestone"] == "m1"
