from __future__ import annotations

import pytest

from superpower_workflow.parallel.planner import (
    DependencyGraph,
    ParallelPlanner,
)


class TestDependencyGraph:
    def test_no_dependencies_single_wave(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2"},
            {"name": "m3"},
        ]
        graph = DependencyGraph(milestones)
        assert graph.is_independent("m1")
        assert graph.is_independent("m2")
        assert graph.is_independent("m3")

    def test_linear_chain(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
            {"name": "m3", "depends_on": ["m2"]},
        ]
        graph = DependencyGraph(milestones)
        assert graph.is_independent("m1")
        assert not graph.is_independent("m2")

    def test_dependents_of(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
            {"name": "m3", "depends_on": ["m1"]},
        ]
        graph = DependencyGraph(milestones)
        deps = graph.dependents_of("m1")
        assert "m2" in deps
        assert "m3" in deps

    def test_dependencies_of(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
        ]
        graph = DependencyGraph(milestones)
        assert graph.dependencies_of("m2") == {"m1"}
        assert graph.dependencies_of("m1") == set()

    def test_cycle_detected(self):
        milestones = [
            {"name": "m1", "depends_on": ["m2"]},
            {"name": "m2", "depends_on": ["m1"]},
        ]
        graph = DependencyGraph(milestones)
        with pytest.raises(ValueError, match="cycle"):
            graph.topological_sort()

    def test_unknown_dependency_raises(self):
        milestones = [
            {"name": "m1", "depends_on": ["nonexistent"]},
        ]
        with pytest.raises(ValueError, match="unknown"):
            DependencyGraph(milestones)


class TestParallelPlanner:
    def test_independent_milestones_single_wave(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2"},
            {"name": "m3"},
        ]
        planner = ParallelPlanner(milestones)
        waves = planner.plan_waves()
        assert len(waves) == 1
        assert set(waves[0].milestones) == {"m1", "m2", "m3"}

    def test_linear_chain_gives_sequential_waves(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
            {"name": "m3", "depends_on": ["m2"]},
        ]
        planner = ParallelPlanner(milestones)
        waves = planner.plan_waves()
        assert len(waves) == 3
        assert waves[0].milestones == ["m1"]
        assert waves[1].milestones == ["m2"]
        assert waves[2].milestones == ["m3"]

    def test_diamond_dependency(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
            {"name": "m3", "depends_on": ["m1"]},
            {"name": "m4", "depends_on": ["m2", "m3"]},
        ]
        planner = ParallelPlanner(milestones)
        waves = planner.plan_waves()
        assert len(waves) == 3
        assert waves[0].milestones == ["m1"]
        assert set(waves[1].milestones) == {"m2", "m3"}
        assert waves[2].milestones == ["m4"]

    def test_mixed_deps_and_independent(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
            {"name": "m3"},
            {"name": "m4", "depends_on": ["m1"]},
        ]
        planner = ParallelPlanner(milestones)
        waves = planner.plan_waves()
        assert len(waves) == 2
        assert set(waves[0].milestones) == {"m1", "m3"}
        assert set(waves[1].milestones) == {"m2", "m4"}

    def test_wave_index_assigned(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
        ]
        planner = ParallelPlanner(milestones)
        waves = planner.plan_waves()
        assert waves[0].index == 0
        assert waves[1].index == 1

    def test_empty_milestones(self):
        planner = ParallelPlanner([])
        waves = planner.plan_waves()
        assert waves == []

    def test_skip_completed(self):
        milestones = [
            {"name": "m1"},
            {"name": "m2", "depends_on": ["m1"]},
            {"name": "m3"},
        ]
        planner = ParallelPlanner(milestones, completed={"m1"})
        waves = planner.plan_waves()
        milestone_names = [m for w in waves for m in w.milestones]
        assert "m1" not in milestone_names
        assert "m2" in milestone_names
        assert "m3" in milestone_names
