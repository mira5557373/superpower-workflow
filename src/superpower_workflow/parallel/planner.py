from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecutionWave:
    index: int
    milestones: list[str] = field(default_factory=list)


class DependencyGraph:
    def __init__(self, milestones: list[dict]) -> None:
        self._deps: dict[str, set[str]] = {}
        self._rdeps: dict[str, set[str]] = {}
        self._names: list[str] = []
        all_names = {ms["name"] for ms in milestones}
        for ms in milestones:
            name = ms["name"]
            self._names.append(name)
            deps = set(ms.get("depends_on", []))
            unknown = deps - all_names
            if unknown:
                raise ValueError(f"Milestone '{name}' depends on unknown: {sorted(unknown)}")
            self._deps[name] = deps
            self._rdeps.setdefault(name, set())
            for dep in deps:
                self._rdeps.setdefault(dep, set()).add(name)

    def is_independent(self, name: str) -> bool:
        return len(self._deps.get(name, set())) == 0

    def dependents_of(self, name: str) -> set[str]:
        return self._rdeps.get(name, set())

    def dependencies_of(self, name: str) -> set[str]:
        return self._deps.get(name, set())

    def topological_sort(self) -> list[str]:
        in_degree: dict[str, int] = {n: len(self._deps.get(n, set())) for n in self._names}
        queue = [n for n in self._names if in_degree[n] == 0]
        result: list[str] = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for dependent in sorted(self._rdeps.get(node, set())):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        if len(result) != len(self._names):
            raise ValueError("Dependency cycle detected")
        return result


class ParallelPlanner:
    def __init__(
        self,
        milestones: list[dict],
        completed: set[str] | None = None,
    ) -> None:
        self._completed = completed or set()
        self._milestones = []
        for ms in milestones:
            if ms["name"] in self._completed:
                continue
            cleaned = dict(ms)
            deps = [d for d in ms.get("depends_on", []) if d not in self._completed]
            if deps:
                cleaned["depends_on"] = deps
            else:
                cleaned.pop("depends_on", None)
            self._milestones.append(cleaned)

    def plan_waves(self) -> list[ExecutionWave]:
        if not self._milestones:
            return []
        graph = DependencyGraph(self._milestones)
        graph.topological_sort()

        remaining = {ms["name"] for ms in self._milestones}
        satisfied = set(self._completed)
        waves: list[ExecutionWave] = []
        idx = 0

        while remaining:
            ready = []
            for name in sorted(remaining):
                deps = graph.dependencies_of(name) - self._completed
                if deps.issubset(satisfied):
                    ready.append(name)
            if not ready:
                raise ValueError("Dependency cycle detected")
            waves.append(ExecutionWave(index=idx, milestones=ready))
            for name in ready:
                remaining.discard(name)
                satisfied.add(name)
            idx += 1

        return waves
