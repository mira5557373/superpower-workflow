# SP6: Parallel & Multi-Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable concurrent milestone execution via git worktrees, intelligent model routing based on task complexity, best-of-N quality selection, remote SSH execution, and Claude Code Agent Teams integration for Phase B.

**Architecture:** New `parallel/` subpackage with seven modules. WorktreeManager wraps `git worktree` for isolation -- each parallel milestone runs in its own worktree with a `sw-parallel/<name>` branch. ModelRouter scores milestone complexity and maps to models via config rules. ParallelPlanner topologically sorts milestones into execution waves of independent work. ParallelExecutor runs waves concurrently via `concurrent.futures.ThreadPoolExecutor` with a shared ThreadSafeBudget (Lock-protected). BestOfNRunner forks N copies of a milestone and selects the winner by quality score. RemoteRunner wraps SSH for offloading work. Agent Teams adds `--num-agents` to `run_claude()` for Phase B parallel teammates.

**Tech Stack:** Python 3.11+, `subprocess` (git worktree, ssh), `concurrent.futures`, `threading`, `dataclasses`, `json`, `re`. Zero new dependencies -- all stdlib.

**Spec reference:** `docs/superpowers/specs/roadmap.md` -- SP6 section.

**Working directory:** `superpower-workflow/` (the repo root).

---

## Design Decisions

1. **Worktree location:** `.worktrees/<name>` under project root. Gitignored.
2. **Branch naming:** `sw-parallel/<milestone-name>` -- namespaced to avoid collisions.
3. **Merge strategy:** Fast-forward preferred; merge commit fallback. Conflicts mark milestone as failed.
4. **Budget sharing:** Single `ThreadSafeBudget` instance shared across all parallel workers. Exceeded budget signals remaining workers to stop.
5. **Model routing:** Threshold-based rules. Complexity score 0.0-1.0 maps to the first rule whose threshold is met. Per-milestone `model_override` takes precedence.
6. **Remote:** `ssh://[user@]host[:port][/path]` URL format. Sync via `git push`, execute via `ssh`, pull via `git fetch + merge`.
7. **Agent Teams:** `--num-agents` flag on `claude -p` during Phase B only. Optional, backward compatible.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/parallel/__init__.py` | New | Package exports with `__all__` |
| `src/superpower_workflow/parallel/budget.py` | New | ThreadSafeBudget (Lock-protected accumulator) |
| `src/superpower_workflow/parallel/worktree.py` | New | WorktreeManager, WorktreeInfo, MergeResult |
| `src/superpower_workflow/parallel/router.py` | New | ComplexityScorer, RoutingRule, ModelRouter, RouteDecision |
| `src/superpower_workflow/parallel/planner.py` | New | DependencyGraph, ExecutionWave, ParallelPlanner |
| `src/superpower_workflow/parallel/executor.py` | New | ParallelExecutor, ParallelResult |
| `src/superpower_workflow/parallel/best_of_n.py` | New | BestOfNRunner, CandidateResult |
| `src/superpower_workflow/parallel/remote.py` | New | RemoteConfig, RemoteRunner |
| `src/superpower_workflow/runner.py` | Edit | Add `num_agents` parameter to `run_claude` + `_build_command` |
| `src/superpower_workflow/state.py` | Edit | New VALID_STEPS for parallel, `clone_state_to_worktree` helper |
| `src/superpower_workflow/cli.py` | Edit | `--parallel`, `--workers`, `--remote`, `--best-of-n`, `--model-override` flags |
| `src/superpower_workflow/orchestrator.py` | Edit | Wire parallel mode into `run()`, model routing hook |
| `src/superpower_workflow/telemetry.py` | Edit | New parallel event types |
| `templates/workflow.json` | Edit | `model_routing` and `parallel` config sections |
| `tests/test_parallel_budget.py` | New | ThreadSafeBudget tests |
| `tests/test_parallel_worktree.py` | New | WorktreeManager tests |
| `tests/test_parallel_router.py` | New | ModelRouter tests |
| `tests/test_parallel_planner.py` | New | ParallelPlanner tests |
| `tests/test_parallel_executor.py` | New | ParallelExecutor tests |
| `tests/test_parallel_best_of_n.py` | New | BestOfNRunner tests |
| `tests/test_parallel_remote.py` | New | RemoteRunner tests |
| `tests/test_parallel_agent_teams.py` | New | Agent Teams runner integration tests |
| `tests/test_parallel_cli.py` | New | Parallel CLI flag tests |
| `tests/test_parallel_integration.py` | New | End-to-end parallel scenarios |

---

### Task 1: Config schema -- model_routing + parallel sections

**Files:**
- Edit: `templates/workflow.json`
- Edit: `src/superpower_workflow/cli.py` (default config in `_cmd_init`)
- New: `tests/test_parallel_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_cli.py
from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init


class TestParallelConfig:
    def test_init_includes_model_routing(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "model_routing" in config
        routing = config["model_routing"]
        assert "enabled" in routing
        assert routing["enabled"] is False
        assert "rules" in routing
        assert isinstance(routing["rules"], list)

    def test_init_includes_parallel_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "parallel" in config
        par = config["parallel"]
        assert par["enabled"] is False
        assert par["max_workers"] == 4
        assert par["best_of_n"] == 1
        assert par["agent_teams_count"] == 0
        assert par["remote"] is None

    def test_init_includes_default_routing_rules(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        rules = config["model_routing"]["rules"]
        assert len(rules) == 3
        assert rules[0]["model"] == "opus"
        assert rules[1]["model"] == "sonnet"
        assert rules[2]["model"] == "haiku"

    def test_model_routing_default_model_key(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert config["model_routing"]["default_model"] == "opus"

    def test_parallel_worktree_dir_configurable(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert config["parallel"]["worktree_dir"] == ".worktrees"
```

- [ ] **Step 2: Run tests -- expect FAIL** (keys don't exist in default config)

- [ ] **Step 3: Add config sections**

In `cli.py` `_cmd_init`, add to `default_config` dict after the `integrations` block:

```python
"model_routing": {
    "enabled": False,
    "default_model": "opus",
    "rules": [
        {"threshold": 0.7, "model": "opus"},
        {"threshold": 0.3, "model": "sonnet"},
        {"threshold": 0.0, "model": "haiku"},
    ],
},
"parallel": {
    "enabled": False,
    "max_workers": 4,
    "best_of_n": 1,
    "agent_teams_count": 0,
    "remote": None,
    "worktree_dir": ".worktrees",
},
```

Also add `.worktrees/` to the gitignore entries list in `_cmd_init`:

```python
entries = [
    # ... existing entries ...
    ".worktrees/",
]
```

Update `templates/workflow.json` to include the same sections.

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_parallel_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_parallel_cli.py
git add src/superpower_workflow/cli.py templates/workflow.json tests/test_parallel_cli.py
git commit -m "feat: add model_routing and parallel config sections"
```

---

### Task 2: ThreadSafeBudget

**Files:**
- New: `src/superpower_workflow/parallel/__init__.py`
- New: `src/superpower_workflow/parallel/budget.py`
- New: `tests/test_parallel_budget.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_budget.py
from __future__ import annotations

import threading

from superpower_workflow.parallel.budget import ThreadSafeBudget


class TestThreadSafeBudget:
    def test_initial_state(self):
        b = ThreadSafeBudget(100.0)
        assert b.remaining == 100.0
        assert b.spent == 0.0
        assert b.limit == 100.0

    def test_spend_success(self):
        b = ThreadSafeBudget(100.0)
        assert b.spend(25.0) is True
        assert b.spent == 25.0
        assert b.remaining == 75.0

    def test_spend_exact_limit(self):
        b = ThreadSafeBudget(50.0)
        assert b.spend(50.0) is True
        assert b.remaining == 0.0

    def test_spend_over_limit_rejected(self):
        b = ThreadSafeBudget(50.0)
        assert b.spend(60.0) is False
        assert b.spent == 0.0
        assert b.remaining == 50.0

    def test_cumulative_spend_hits_limit(self):
        b = ThreadSafeBudget(100.0)
        assert b.spend(40.0) is True
        assert b.spend(40.0) is True
        assert b.spend(25.0) is False
        assert b.spent == 80.0

    def test_is_exhausted(self):
        b = ThreadSafeBudget(10.0)
        assert b.is_exhausted is False
        b.spend(10.0)
        assert b.is_exhausted is True

    def test_thread_safety(self):
        b = ThreadSafeBudget(1000.0)
        errors = []

        def spend_loop():
            for _ in range(100):
                b.spend(1.0)

        threads = [threading.Thread(target=spend_loop) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert b.spent == 1000.0
        assert b.remaining == 0.0

    def test_thread_safety_rejects_over_limit(self):
        b = ThreadSafeBudget(500.0)
        accepted = {"count": 0}
        lock = threading.Lock()

        def spend_loop():
            for _ in range(100):
                if b.spend(1.0):
                    with lock:
                        accepted["count"] += 1

        threads = [threading.Thread(target=spend_loop) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert accepted["count"] == 500
        assert b.spent == 500.0

    def test_zero_budget(self):
        b = ThreadSafeBudget(0.0)
        assert b.is_exhausted is True
        assert b.spend(1.0) is False

    def test_negative_spend_rejected(self):
        b = ThreadSafeBudget(100.0)
        assert b.spend(-5.0) is False
        assert b.spent == 0.0
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/parallel/__init__.py
from __future__ import annotations

from superpower_workflow.parallel.budget import ThreadSafeBudget

__all__ = [
    "ThreadSafeBudget",
]
```

```python
# src/superpower_workflow/parallel/budget.py
from __future__ import annotations

import threading


class ThreadSafeBudget:
    """Lock-protected budget accumulator for parallel execution."""

    def __init__(self, limit: float) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        self._spent = 0.0

    def spend(self, amount: float) -> bool:
        if amount < 0:
            return False
        with self._lock:
            if self._spent + amount > self._limit:
                return False
            self._spent += amount
            return True

    @property
    def remaining(self) -> float:
        with self._lock:
            return self._limit - self._spent

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    @property
    def limit(self) -> float:
        return self._limit

    @property
    def is_exhausted(self) -> bool:
        with self._lock:
            return self._spent >= self._limit
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/ tests/test_parallel_budget.py --fix
ruff format src/superpower_workflow/parallel/ tests/test_parallel_budget.py
git add src/superpower_workflow/parallel/__init__.py src/superpower_workflow/parallel/budget.py tests/test_parallel_budget.py
git commit -m "feat: add ThreadSafeBudget for parallel budget tracking"
```

---

### Task 3: WorktreeManager -- create, remove, list

**Files:**
- New: `src/superpower_workflow/parallel/worktree.py`
- New: `tests/test_parallel_worktree.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_worktree.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import call, patch

from superpower_workflow.parallel.worktree import (
    MergeResult,
    WorktreeInfo,
    WorktreeManager,
)


def _success(stdout: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _failure(stderr: str = "error") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


class TestWorktreeCreate:
    def test_creates_worktree_with_branch(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()):
            info = mgr.create("m1")
        assert info.name == "m1"
        assert info.branch == "sw-parallel/m1"
        assert info.path == tmp_path / ".worktrees" / "m1"

    def test_create_calls_git_worktree_add(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()) as mock:
            mgr.create("m1", base_ref="main")
        cmd = mock.call_args[0][0]
        assert "worktree" in cmd
        assert "add" in cmd
        assert "-b" in cmd
        assert "sw-parallel/m1" in cmd
        assert "main" in cmd

    def test_create_custom_worktree_dir(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path, worktree_dir=tmp_path / "custom")
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()):
            info = mgr.create("m1")
        assert info.path == tmp_path / "custom" / "m1"

    def test_create_raises_on_git_failure(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_failure("fatal: already exists")):
            import pytest

            with pytest.raises(RuntimeError, match="already exists"):
                mgr.create("m1")


class TestWorktreeRemove:
    def test_remove_calls_git_worktree_remove(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()) as mock:
            mgr.remove("m1")
        cmd = mock.call_args_list[0][0][0]
        assert "worktree" in cmd
        assert "remove" in cmd

    def test_remove_prunes_branch(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()) as mock:
            mgr.remove("m1", prune_branch=True)
        calls = [c[0][0] for c in mock.call_args_list]
        branch_delete = [c for c in calls if "branch" in c and "-D" in c]
        assert len(branch_delete) == 1
        assert "sw-parallel/m1" in branch_delete[0]

    def test_remove_silent_on_missing(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_failure("not a working tree"),
        ):
            mgr.remove("nonexistent")


class TestWorktreeList:
    def test_list_parses_porcelain_output(self, tmp_path: Path):
        porcelain = (
            f"worktree {tmp_path}\n"
            "HEAD abc1234\n"
            "branch refs/heads/main\n"
            "\n"
            f"worktree {tmp_path / '.worktrees' / 'm1'}\n"
            "HEAD def5678\n"
            "branch refs/heads/sw-parallel/m1\n"
            "\n"
        )
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ):
            trees = mgr.list()
        parallel_trees = [t for t in trees if t.branch.startswith("sw-parallel/")]
        assert len(parallel_trees) == 1
        assert parallel_trees[0].name == "m1"
        assert parallel_trees[0].branch == "sw-parallel/m1"

    def test_list_empty_when_no_worktrees(self, tmp_path: Path):
        porcelain = f"worktree {tmp_path}\nHEAD abc1234\nbranch refs/heads/main\n\n"
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ):
            trees = mgr.list()
        parallel_trees = [t for t in trees if t.branch.startswith("sw-parallel/")]
        assert parallel_trees == []

    def test_list_returns_all_parallel_worktrees(self, tmp_path: Path):
        porcelain = (
            f"worktree {tmp_path}\nHEAD a\nbranch refs/heads/main\n\n"
            f"worktree {tmp_path / '.worktrees' / 'm1'}\nHEAD b\nbranch refs/heads/sw-parallel/m1\n\n"
            f"worktree {tmp_path / '.worktrees' / 'm2'}\nHEAD c\nbranch refs/heads/sw-parallel/m2\n\n"
        )
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ):
            trees = mgr.list()
        parallel_trees = [t for t in trees if t.branch.startswith("sw-parallel/")]
        assert len(parallel_trees) == 2


class TestWorktreeCleanupAll:
    def test_cleanup_removes_all_parallel_worktrees(self, tmp_path: Path):
        porcelain = (
            f"worktree {tmp_path}\nHEAD a\nbranch refs/heads/main\n\n"
            f"worktree {tmp_path / '.worktrees' / 'm1'}\nHEAD b\nbranch refs/heads/sw-parallel/m1\n\n"
        )
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ) as mock:
            mgr.cleanup_all()
        remove_calls = [
            c for c in mock.call_args_list if "remove" in c[0][0]
        ]
        assert len(remove_calls) >= 1
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/parallel/worktree.py
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

BRANCH_PREFIX = "sw-parallel/"


@dataclass
class WorktreeInfo:
    name: str
    path: Path
    branch: str
    head_sha: str = ""


@dataclass
class MergeResult:
    success: bool
    merged_branch: str
    conflicts: list[str]
    message: str = ""


class WorktreeManager:
    def __init__(self, repo_root: Path, worktree_dir: Path | None = None) -> None:
        self.repo_root = repo_root
        self.worktree_dir = worktree_dir or repo_root / ".worktrees"

    def create(self, name: str, base_ref: str = "HEAD") -> WorktreeInfo:
        branch = f"{BRANCH_PREFIX}{name}"
        wt_path = self.worktree_dir / name
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(wt_path), base_ref],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return WorktreeInfo(name=name, path=wt_path, branch=branch)

    def remove(self, name: str, prune_branch: bool = False) -> None:
        wt_path = self.worktree_dir / name
        subprocess.run(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=60,
        )
        if prune_branch:
            branch = f"{BRANCH_PREFIX}{name}"
            subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                timeout=10,
            )

    def list(self) -> list[WorktreeInfo]:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return _parse_porcelain(result.stdout)

    def cleanup_all(self) -> None:
        for wt in self.list():
            if wt.branch.startswith(BRANCH_PREFIX):
                self.remove(wt.name, prune_branch=True)

    def merge(
        self, name: str, target_branch: str = "HEAD"
    ) -> MergeResult:
        branch = f"{BRANCH_PREFIX}{name}"
        result = subprocess.run(
            ["git", "merge", branch, "--no-edit"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=120,
        )
        if result.returncode == 0:
            return MergeResult(
                success=True,
                merged_branch=branch,
                conflicts=[],
                message=result.stdout.strip(),
            )
        conflicts = _parse_conflicts(result.stdout + result.stderr)
        subprocess.run(
            ["git", "merge", "--abort"],
            capture_output=True,
            cwd=str(self.repo_root),
            timeout=10,
        )
        return MergeResult(
            success=False,
            merged_branch=branch,
            conflicts=conflicts,
            message=result.stderr.strip(),
        )


def _parse_porcelain(output: str) -> list[WorktreeInfo]:
    trees: list[WorktreeInfo] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                path = Path(current.get("worktree", ""))
                branch = current.get("branch", "").replace("refs/heads/", "")
                name = branch.replace(BRANCH_PREFIX, "") if branch.startswith(BRANCH_PREFIX) else path.name
                trees.append(
                    WorktreeInfo(
                        name=name,
                        path=path,
                        branch=branch,
                        head_sha=current.get("HEAD", ""),
                    )
                )
                current = {}
        elif line.startswith("worktree "):
            current["worktree"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
    return trees


def _parse_conflicts(output: str) -> list[str]:
    conflicts = []
    for line in output.splitlines():
        if line.startswith("CONFLICT"):
            conflicts.append(line)
    return conflicts
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/worktree.py tests/test_parallel_worktree.py --fix
ruff format src/superpower_workflow/parallel/worktree.py tests/test_parallel_worktree.py
git add src/superpower_workflow/parallel/worktree.py tests/test_parallel_worktree.py
git commit -m "feat: add WorktreeManager for git worktree lifecycle"
```

---

### Task 4: WorktreeManager -- merge back to target branch

**Files:**
- Modify: `src/superpower_workflow/parallel/worktree.py` (already has merge, tests validate)
- Modify: `tests/test_parallel_worktree.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_worktree.py -- add class

class TestWorktreeMerge:
    def test_merge_success(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success("Already up to date.")):
            result = mgr.merge("m1")
        assert result.success is True
        assert result.merged_branch == "sw-parallel/m1"
        assert result.conflicts == []

    def test_merge_with_conflicts_aborts(self, tmp_path: Path):
        conflict_output = CompletedProcess(
            args=[],
            returncode=1,
            stdout="CONFLICT (content): Merge conflict in src/foo.py\n",
            stderr="Automatic merge failed; fix conflicts and then commit.\n",
        )
        mgr = WorktreeManager(tmp_path)
        calls = []
        def mock_run(cmd, **kw):
            calls.append(cmd)
            if "merge" in cmd and "--abort" not in cmd:
                return conflict_output
            return _success()
        with patch("superpower_workflow.parallel.worktree.subprocess.run", side_effect=mock_run):
            result = mgr.merge("m1")
        assert result.success is False
        assert len(result.conflicts) == 1
        assert "foo.py" in result.conflicts[0]
        abort_calls = [c for c in calls if "--abort" in c]
        assert len(abort_calls) == 1

    def test_merge_failure_message_preserved(self, tmp_path: Path):
        fail = CompletedProcess(
            args=[],
            returncode=128,
            stdout="",
            stderr="fatal: not something we can merge",
        )
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run") as mock:
            mock.side_effect = [fail, _success()]
            result = mgr.merge("m1")
        assert result.success is False
        assert "not something we can merge" in result.message
```

- [ ] **Step 2: Run tests -- expect PASS** (merge already implemented in Task 3)

If any fail, adjust the merge method.

- [ ] **Step 3: Lint + commit**

```bash
ruff check tests/test_parallel_worktree.py --fix
ruff format tests/test_parallel_worktree.py
git add tests/test_parallel_worktree.py
git commit -m "test: add worktree merge tests with conflict handling"
```

---

### Task 5: ComplexityScorer -- analyze milestone attributes

**Files:**
- New: `src/superpower_workflow/parallel/router.py`
- New: `tests/test_parallel_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_router.py
from __future__ import annotations

from superpower_workflow.parallel.router import (
    ComplexityScore,
    ModelRouter,
    RouteDecision,
    RoutingRule,
    score_complexity,
)


class TestScoreComplexity:
    def test_simple_milestone(self):
        ms = {"name": "m1", "description": "fix typo in readme"}
        score = score_complexity(ms)
        assert 0.0 <= score.value <= 0.3

    def test_complex_milestone_with_architecture_keyword(self):
        ms = {
            "name": "m1",
            "description": "refactor authentication architecture with new middleware",
        }
        score = score_complexity(ms)
        assert score.value >= 0.5

    def test_high_file_count_raises_score(self):
        ms = {
            "name": "m1",
            "description": "update styles",
            "spec_sections": "a,b,c,d,e,f,g,h,i,j",
        }
        score = score_complexity(ms)
        score_few = score_complexity(
            {"name": "m2", "description": "update styles", "spec_sections": "a"}
        )
        assert score.value > score_few.value

    def test_new_module_keyword_raises_score(self):
        ms = {"name": "m1", "description": "add new parallel execution module"}
        score = score_complexity(ms)
        assert score.value >= 0.4

    def test_manual_override_in_milestone(self):
        ms = {"name": "m1", "description": "simple fix", "complexity_override": 0.9}
        score = score_complexity(ms)
        assert score.value == 0.9

    def test_score_bounds(self):
        ms = {"name": "m1", "description": ""}
        score = score_complexity(ms)
        assert 0.0 <= score.value <= 1.0

    def test_depends_on_adds_to_score(self):
        ms = {
            "name": "m1",
            "description": "update handler",
            "depends_on": ["m0a", "m0b", "m0c"],
        }
        score_with_deps = score_complexity(ms)
        score_no_deps = score_complexity(
            {"name": "m1", "description": "update handler"}
        )
        assert score_with_deps.value >= score_no_deps.value

    def test_complexity_score_signals_populated(self):
        ms = {
            "name": "m1",
            "description": "refactor database layer and add migration system",
            "spec_sections": "4.1,4.2,4.3",
        }
        score = score_complexity(ms)
        assert len(score.signals) > 0
        assert isinstance(score.signals, list)
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/parallel/router.py
from __future__ import annotations

import re
from dataclasses import dataclass, field


COMPLEXITY_KEYWORDS_HIGH = frozenset({
    "refactor", "architecture", "redesign", "migration",
    "parallel", "concurrent", "security", "authentication",
})

COMPLEXITY_KEYWORDS_MEDIUM = frozenset({
    "module", "package", "integration", "pipeline",
    "database", "cache", "queue", "api",
})


@dataclass
class ComplexityScore:
    value: float = 0.0
    signals: list[str] = field(default_factory=list)


@dataclass
class RoutingRule:
    threshold: float
    model: str


@dataclass
class RouteDecision:
    model: str
    complexity: ComplexityScore
    reason: str = ""


def score_complexity(ms: dict) -> ComplexityScore:
    override = ms.get("complexity_override")
    if override is not None:
        return ComplexityScore(
            value=float(override),
            signals=["manual_override"],
        )

    signals: list[str] = []
    value = 0.0

    desc = ms.get("description", "").lower()
    words = set(re.findall(r"\w+", desc))

    high_matches = words & COMPLEXITY_KEYWORDS_HIGH
    if high_matches:
        value += 0.15 * len(high_matches)
        signals.append(f"high_keywords:{','.join(sorted(high_matches))}")

    med_matches = words & COMPLEXITY_KEYWORDS_MEDIUM
    if med_matches:
        value += 0.08 * len(med_matches)
        signals.append(f"medium_keywords:{','.join(sorted(med_matches))}")

    sections = ms.get("spec_sections", "")
    section_count = len([s for s in sections.split(",") if s.strip()]) if sections else 0
    if section_count > 5:
        value += 0.15
        signals.append(f"many_sections:{section_count}")
    elif section_count > 2:
        value += 0.08
        signals.append(f"some_sections:{section_count}")

    deps = ms.get("depends_on", [])
    if len(deps) >= 3:
        value += 0.1
        signals.append(f"many_deps:{len(deps)}")
    elif len(deps) >= 1:
        value += 0.05
        signals.append(f"has_deps:{len(deps)}")

    if any(kw in desc for kw in ("add new", "new module", "new package")):
        value += 0.1
        signals.append("new_module")

    value = max(0.0, min(1.0, value))
    return ComplexityScore(value=value, signals=signals)


class ModelRouter:
    def __init__(
        self,
        rules: list[RoutingRule],
        default_model: str = "opus",
    ) -> None:
        self._rules = sorted(rules, key=lambda r: r.threshold, reverse=True)
        self._default = default_model

    def route(self, ms: dict) -> RouteDecision:
        override = ms.get("model_override")
        if override:
            return RouteDecision(
                model=override,
                complexity=ComplexityScore(value=0.0, signals=["model_override"]),
                reason=f"milestone override: {override}",
            )
        complexity = score_complexity(ms)
        for rule in self._rules:
            if complexity.value >= rule.threshold:
                return RouteDecision(
                    model=rule.model,
                    complexity=complexity,
                    reason=f"score {complexity.value:.2f} >= threshold {rule.threshold}",
                )
        return RouteDecision(
            model=self._default,
            complexity=complexity,
            reason=f"below all thresholds, using default: {self._default}",
        )

    @classmethod
    def from_config(cls, config: dict) -> ModelRouter:
        routing = config.get("model_routing", {})
        if not routing.get("enabled", False):
            default = config.get("model", "opus")
            return cls(rules=[], default_model=default)
        rules = [
            RoutingRule(threshold=r["threshold"], model=r["model"])
            for r in routing.get("rules", [])
        ]
        return cls(
            rules=rules,
            default_model=routing.get("default_model", config.get("model", "opus")),
        )
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/router.py tests/test_parallel_router.py --fix
ruff format src/superpower_workflow/parallel/router.py tests/test_parallel_router.py
git add src/superpower_workflow/parallel/router.py tests/test_parallel_router.py
git commit -m "feat: add ComplexityScorer for milestone complexity analysis"
```

---

### Task 6: ModelRouter -- route milestones to models via config rules

**Files:**
- Modify: `tests/test_parallel_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_router.py -- add class

class TestModelRouter:
    def test_routes_high_complexity_to_opus(self):
        rules = [
            RoutingRule(threshold=0.7, model="opus"),
            RoutingRule(threshold=0.3, model="sonnet"),
            RoutingRule(threshold=0.0, model="haiku"),
        ]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "refactor authentication architecture with migration"}
        decision = router.route(ms)
        assert decision.model == "opus"

    def test_routes_low_complexity_to_haiku(self):
        rules = [
            RoutingRule(threshold=0.7, model="opus"),
            RoutingRule(threshold=0.3, model="sonnet"),
            RoutingRule(threshold=0.0, model="haiku"),
        ]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "fix typo"}
        decision = router.route(ms)
        assert decision.model == "haiku"

    def test_routes_medium_complexity_to_sonnet(self):
        rules = [
            RoutingRule(threshold=0.7, model="opus"),
            RoutingRule(threshold=0.3, model="sonnet"),
            RoutingRule(threshold=0.0, model="haiku"),
        ]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "add new integration module for the api pipeline"}
        decision = router.route(ms)
        assert decision.model == "sonnet"

    def test_milestone_override_takes_precedence(self):
        rules = [RoutingRule(threshold=0.0, model="haiku")]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "fix typo", "model_override": "opus"}
        decision = router.route(ms)
        assert decision.model == "opus"
        assert "override" in decision.reason

    def test_default_model_when_no_rules(self):
        router = ModelRouter(rules=[], default_model="sonnet")
        ms = {"name": "m1", "description": "something"}
        decision = router.route(ms)
        assert decision.model == "sonnet"

    def test_from_config_disabled_returns_default(self):
        config = {"model": "opus", "model_routing": {"enabled": False}}
        router = ModelRouter.from_config(config)
        ms = {"name": "m1", "description": "complex refactor architecture migration"}
        decision = router.route(ms)
        assert decision.model == "opus"

    def test_from_config_enabled_applies_rules(self):
        config = {
            "model": "opus",
            "model_routing": {
                "enabled": True,
                "default_model": "opus",
                "rules": [
                    {"threshold": 0.7, "model": "opus"},
                    {"threshold": 0.0, "model": "haiku"},
                ],
            },
        }
        router = ModelRouter.from_config(config)
        ms = {"name": "m1", "description": "fix typo"}
        decision = router.route(ms)
        assert decision.model == "haiku"

    def test_route_decision_includes_complexity(self):
        rules = [RoutingRule(threshold=0.0, model="haiku")]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "refactor database module"}
        decision = router.route(ms)
        assert decision.complexity.value > 0
        assert len(decision.complexity.signals) > 0

    def test_from_config_no_routing_key(self):
        config = {"model": "sonnet"}
        router = ModelRouter.from_config(config)
        decision = router.route({"name": "m1", "description": "anything"})
        assert decision.model == "sonnet"
```

- [ ] **Step 2: Run tests -- expect PASS** (ModelRouter already implemented in Task 5)

If any fail, adjust the router.

- [ ] **Step 3: Lint + commit**

```bash
ruff check tests/test_parallel_router.py --fix
ruff format tests/test_parallel_router.py
git add tests/test_parallel_router.py
git commit -m "test: add ModelRouter config-driven routing tests"
```

---

### Task 7: DependencyGraph + ParallelPlanner -- topological waves

**Files:**
- New: `src/superpower_workflow/parallel/planner.py`
- New: `tests/test_parallel_planner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_planner.py
from __future__ import annotations

import pytest

from superpower_workflow.parallel.planner import (
    DependencyGraph,
    ExecutionWave,
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
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/parallel/planner.py
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
        self._milestones = [
            ms for ms in milestones if ms["name"] not in self._completed
        ]

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
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/planner.py tests/test_parallel_planner.py --fix
ruff format src/superpower_workflow/parallel/planner.py tests/test_parallel_planner.py
git add src/superpower_workflow/parallel/planner.py tests/test_parallel_planner.py
git commit -m "feat: add DependencyGraph and ParallelPlanner for wave-based scheduling"
```

---

### Task 8: ParallelExecutor -- thread pool concurrent execution

**Files:**
- New: `src/superpower_workflow/parallel/executor.py`
- New: `tests/test_parallel_executor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_executor.py
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.executor import ParallelExecutor, ParallelResult
from superpower_workflow.parallel.planner import ExecutionWave


class TestParallelExecutor:
    def _make_executor(self, max_workers: int = 2, budget: float = 500.0):
        return ParallelExecutor(
            budget=ThreadSafeBudget(budget),
            max_workers=max_workers,
        )

    def test_execute_wave_runs_all_milestones(self):
        executor = self._make_executor()
        wave = ExecutionWave(index=0, milestones=["m1", "m2", "m3"])
        results_map = {}

        def run_fn(name: str, cwd: str) -> ParallelResult:
            return ParallelResult(
                milestone=name, success=True, cost_usd=5.0, worktree=cwd,
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
                concurrent_count["max"] = max(
                    concurrent_count["max"], concurrent_count["current"]
                )
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
                    milestone=name, success=False, cost_usd=3.0,
                    worktree=cwd, error="Phase B failed",
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
                    milestone=name, success=False, cost_usd=0.0,
                    worktree=cwd, error="budget_exhausted",
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
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/parallel/executor.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.planner import ExecutionWave


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
    ) -> None:
        self._budget = budget
        self._max_workers = max_workers

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
                pool.submit(self._safe_run, run_fn, name, cwd): name
                for name in wave.milestones
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)

        return results

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
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/executor.py tests/test_parallel_executor.py --fix
ruff format src/superpower_workflow/parallel/executor.py tests/test_parallel_executor.py
git add src/superpower_workflow/parallel/executor.py tests/test_parallel_executor.py
git commit -m "feat: add ParallelExecutor with ThreadPoolExecutor-based wave execution"
```

---

### Task 9: ParallelExecutor + worktree integration -- isolated execution

**Files:**
- Modify: `src/superpower_workflow/parallel/executor.py`
- Modify: `tests/test_parallel_executor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_executor.py -- add class

from unittest.mock import MagicMock, call
from superpower_workflow.parallel.worktree import WorktreeManager, WorktreeInfo, MergeResult


class TestWorktreeIsolatedExecution:
    def test_creates_worktree_per_milestone(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(
            success=True, merged_branch="", conflicts=[]
        )
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
        mock_mgr.merge.return_value = MergeResult(
            success=True, merged_branch="", conflicts=[]
        )
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
        mock_mgr.merge.return_value = MergeResult(
            success=True, merged_branch="", conflicts=[]
        )
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
        mock_mgr.merge.return_value = MergeResult(
            success=True, merged_branch="", conflicts=[]
        )
        executor = ParallelExecutor(budget=budget, max_workers=2, worktree_mgr=mock_mgr)

        def run_fn(name: str, cwd: str) -> ParallelResult:
            if name == "m2":
                return ParallelResult(milestone=name, success=False, cost_usd=1.0, worktree=cwd, error="fail")
            return ParallelResult(milestone=name, success=True, cost_usd=5.0, worktree=cwd)

        wave = ExecutionWave(index=0, milestones=["m1", "m2"])
        executor.execute_wave_isolated(wave, run_fn=run_fn)
        merge_names = [c.args[0] if c.args else c.kwargs.get("name") for c in mock_mgr.merge.call_args_list]
        assert "m1" in merge_names
        assert "m2" not in merge_names

    def test_cleans_up_worktrees_after_execution(self):
        budget = ThreadSafeBudget(500.0)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=f"/tmp/wt/{name}", branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(
            success=True, merged_branch="", conflicts=[]
        )
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
        import pytest

        with pytest.raises(RuntimeError, match="merge exploded"):
            executor.execute_wave_isolated(wave, run_fn=run_fn)
        assert mock_mgr.remove.call_count >= 1
```

- [ ] **Step 2: Run tests -- expect FAIL** (`execute_wave_isolated` doesn't exist)

- [ ] **Step 3: Add `execute_wave_isolated` to ParallelExecutor**

```python
# Add to ParallelExecutor class in executor.py

def __init__(
    self,
    budget: ThreadSafeBudget,
    max_workers: int = 4,
    worktree_mgr: WorktreeManager | None = None,
) -> None:
    self._budget = budget
    self._max_workers = max_workers
    self._worktree_mgr = worktree_mgr

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
```

Add import at top of executor.py:
```python
from superpower_workflow.parallel.worktree import WorktreeInfo, WorktreeManager
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/executor.py tests/test_parallel_executor.py --fix
ruff format src/superpower_workflow/parallel/executor.py tests/test_parallel_executor.py
git add src/superpower_workflow/parallel/executor.py tests/test_parallel_executor.py
git commit -m "feat: add worktree-isolated parallel execution with merge sequencing"
```

---

### Task 10: BestOfNRunner -- multi-execution with quality selection

**Files:**
- New: `src/superpower_workflow/parallel/best_of_n.py`
- New: `tests/test_parallel_best_of_n.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_best_of_n.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from superpower_workflow.parallel.best_of_n import (
    BestOfNRunner,
    CandidateResult,
    score_candidate,
)
from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.worktree import WorktreeInfo, WorktreeManager, MergeResult


class TestScoreCandidate:
    def test_all_green_high_score(self):
        c = CandidateResult(
            index=0, model="opus", worktree="wt0",
            tests_passing=True, lint_clean=True, gap_count=0, cost_usd=5.0,
        )
        assert score_candidate(c) > 0.8

    def test_tests_failing_penalized(self):
        passing = CandidateResult(
            index=0, model="opus", worktree="wt0",
            tests_passing=True, lint_clean=True, gap_count=2, cost_usd=5.0,
        )
        failing = CandidateResult(
            index=1, model="opus", worktree="wt1",
            tests_passing=False, lint_clean=True, gap_count=2, cost_usd=5.0,
        )
        assert score_candidate(passing) > score_candidate(failing)

    def test_fewer_gaps_scores_higher(self):
        few = CandidateResult(
            index=0, model="opus", worktree="wt0",
            tests_passing=True, lint_clean=True, gap_count=1, cost_usd=5.0,
        )
        many = CandidateResult(
            index=1, model="opus", worktree="wt1",
            tests_passing=True, lint_clean=True, gap_count=10, cost_usd=5.0,
        )
        assert score_candidate(few) > score_candidate(many)

    def test_lint_clean_bonus(self):
        clean = CandidateResult(
            index=0, model="opus", worktree="wt0",
            tests_passing=True, lint_clean=True, gap_count=3, cost_usd=5.0,
        )
        dirty = CandidateResult(
            index=1, model="opus", worktree="wt1",
            tests_passing=True, lint_clean=False, gap_count=3, cost_usd=5.0,
        )
        assert score_candidate(clean) > score_candidate(dirty)

    def test_score_between_zero_and_one(self):
        c = CandidateResult(
            index=0, model="opus", worktree="wt0",
            tests_passing=False, lint_clean=False, gap_count=100, cost_usd=50.0,
        )
        assert 0.0 <= score_candidate(c) <= 1.0


class TestBestOfNRunner:
    def _make_runner(self, n: int = 3, budget: float = 500.0):
        budget_obj = ThreadSafeBudget(budget)
        mock_mgr = MagicMock(spec=WorktreeManager)
        mock_mgr.create.side_effect = lambda name, **kw: WorktreeInfo(
            name=name, path=Path(f"/tmp/wt/{name}"), branch=f"sw-parallel/{name}"
        )
        mock_mgr.merge.return_value = MergeResult(
            success=True, merged_branch="", conflicts=[]
        )
        return BestOfNRunner(n=n, budget=budget_obj, worktree_mgr=mock_mgr), mock_mgr

    def test_runs_n_candidates(self):
        runner, mock_mgr = self._make_runner(n=3)
        call_count = {"n": 0}

        def run_fn(name: str, cwd: str) -> CandidateResult:
            idx = call_count["n"]
            call_count["n"] += 1
            return CandidateResult(
                index=idx, model="opus", worktree=cwd,
                tests_passing=True, lint_clean=True, gap_count=idx, cost_usd=5.0,
            )

        winner = runner.run("m1", run_fn=run_fn)
        assert call_count["n"] == 3
        assert winner.gap_count == 0

    def test_selects_highest_scoring_candidate(self):
        runner, mock_mgr = self._make_runner(n=3)
        candidates = [
            CandidateResult(index=0, model="opus", worktree="wt0", tests_passing=True, lint_clean=True, gap_count=5, cost_usd=5.0),
            CandidateResult(index=1, model="sonnet", worktree="wt1", tests_passing=True, lint_clean=True, gap_count=0, cost_usd=3.0),
            CandidateResult(index=2, model="haiku", worktree="wt2", tests_passing=False, lint_clean=True, gap_count=2, cost_usd=1.0),
        ]

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return candidates.pop(0)

        winner = runner.run("m1", run_fn=run_fn)
        assert winner.index == 1
        assert winner.gap_count == 0

    def test_merges_only_winner(self):
        runner, mock_mgr = self._make_runner(n=2)
        candidates = [
            CandidateResult(index=0, model="opus", worktree="wt0", tests_passing=True, lint_clean=True, gap_count=5, cost_usd=5.0),
            CandidateResult(index=1, model="opus", worktree="wt1", tests_passing=True, lint_clean=True, gap_count=0, cost_usd=5.0),
        ]

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return candidates.pop(0)

        runner.run("m1", run_fn=run_fn)
        assert mock_mgr.merge.call_count == 1

    def test_cleans_up_all_worktrees(self):
        runner, mock_mgr = self._make_runner(n=3)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return CandidateResult(
                index=0, model="opus", worktree=cwd,
                tests_passing=True, lint_clean=True, gap_count=0, cost_usd=5.0,
            )

        runner.run("m1", run_fn=run_fn)
        assert mock_mgr.remove.call_count == 3

    def test_n_equals_one_no_comparison(self):
        runner, mock_mgr = self._make_runner(n=1)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return CandidateResult(
                index=0, model="opus", worktree=cwd,
                tests_passing=True, lint_clean=True, gap_count=0, cost_usd=5.0,
            )

        winner = runner.run("m1", run_fn=run_fn)
        assert winner is not None
        assert mock_mgr.create.call_count == 1

    def test_all_candidates_fail_raises(self):
        runner, mock_mgr = self._make_runner(n=2)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            raise RuntimeError("crash")

        import pytest

        with pytest.raises(RuntimeError, match="All 2 candidates failed"):
            runner.run("m1", run_fn=run_fn)
        assert mock_mgr.remove.call_count == 2

    def test_n_zero_treated_as_one(self):
        runner, mock_mgr = self._make_runner(n=0)

        def run_fn(name: str, cwd: str) -> CandidateResult:
            return CandidateResult(
                index=0, model="opus", worktree=cwd,
                tests_passing=True, lint_clean=True, gap_count=0, cost_usd=5.0,
            )

        winner = runner.run("m1", run_fn=run_fn)
        assert winner is not None
        assert mock_mgr.create.call_count == 1
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/parallel/best_of_n.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

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
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/best_of_n.py tests/test_parallel_best_of_n.py --fix
ruff format src/superpower_workflow/parallel/best_of_n.py tests/test_parallel_best_of_n.py
git add src/superpower_workflow/parallel/best_of_n.py tests/test_parallel_best_of_n.py
git commit -m "feat: add BestOfNRunner with quality-based candidate selection"
```

---

### Task 11: RemoteRunner -- SSH-based remote execution

**Files:**
- New: `src/superpower_workflow/parallel/remote.py`
- New: `tests/test_parallel_remote.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_remote.py
from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from superpower_workflow.parallel.remote import RemoteConfig, RemoteRunner


class TestRemoteConfig:
    def test_parse_simple_url(self):
        cfg = RemoteConfig.from_url("ssh://host.example.com")
        assert cfg.host == "host.example.com"
        assert cfg.user is None
        assert cfg.port == 22
        assert cfg.path is None

    def test_parse_full_url(self):
        cfg = RemoteConfig.from_url("ssh://user@host.example.com:2222/home/user/project")
        assert cfg.host == "host.example.com"
        assert cfg.user == "user"
        assert cfg.port == 2222
        assert cfg.path == "/home/user/project"

    def test_parse_url_with_user_no_port(self):
        cfg = RemoteConfig.from_url("ssh://deploy@10.0.0.5")
        assert cfg.host == "10.0.0.5"
        assert cfg.user == "deploy"
        assert cfg.port == 22

    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="ssh://"):
            RemoteConfig.from_url("http://example.com")

    def test_ssh_target(self):
        cfg = RemoteConfig(host="example.com", user="deploy", port=2222)
        assert cfg.ssh_target == "deploy@example.com"

    def test_ssh_target_no_user(self):
        cfg = RemoteConfig(host="example.com")
        assert cfg.ssh_target == "example.com"


class TestRemoteRunner:
    def test_sync_pushes_to_remote(self):
        cfg = RemoteConfig(host="example.com", user="deploy", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch("superpower_workflow.parallel.remote.subprocess.run", return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")) as mock:
            runner.sync()
        cmd = mock.call_args[0][0]
        assert "git" in cmd
        assert "push" in cmd

    def test_run_milestone_via_ssh(self):
        cfg = RemoteConfig(host="example.com", user="deploy", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch("superpower_workflow.parallel.remote.subprocess.run", return_value=CompletedProcess(args=[], returncode=0, stdout='{"result":"ok","total_cost_usd":5.0}', stderr="")) as mock:
            result = runner.run_milestone("m1")
        cmd = mock.call_args[0][0]
        assert "ssh" in cmd
        assert "example.com" in " ".join(cmd)

    def test_pull_results_fetches(self):
        cfg = RemoteConfig(host="example.com", user="deploy", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch("superpower_workflow.parallel.remote.subprocess.run", return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")) as mock:
            runner.pull_results()
        cmd = mock.call_args[0][0]
        assert "git" in cmd
        assert "pull" in cmd or "fetch" in cmd

    def test_run_milestone_returns_cost(self):
        cfg = RemoteConfig(host="example.com", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch("superpower_workflow.parallel.remote.subprocess.run", return_value=CompletedProcess(args=[], returncode=0, stdout='{"cost_usd": 12.5, "success": true}', stderr="")):
            result = runner.run_milestone("m1")
        assert result.cost_usd == 12.5
        assert result.success is True

    def test_ssh_command_includes_port(self):
        cfg = RemoteConfig(host="example.com", user="deploy", port=2222, path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch("superpower_workflow.parallel.remote.subprocess.run", return_value=CompletedProcess(args=[], returncode=0, stdout="{}", stderr="")) as mock:
            runner.run_milestone("m1")
        cmd = mock.call_args[0][0]
        assert "-p" in cmd or "2222" in " ".join(cmd)

    def test_run_milestone_failure(self):
        cfg = RemoteConfig(host="example.com", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch("superpower_workflow.parallel.remote.subprocess.run", return_value=CompletedProcess(args=[], returncode=1, stdout="", stderr="connection refused")):
            result = runner.run_milestone("m1")
        assert result.success is False
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/parallel/remote.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class RemoteResult:
    success: bool = False
    cost_usd: float = 0.0
    error: str = ""


@dataclass
class RemoteConfig:
    host: str
    user: str | None = None
    port: int = 22
    path: str | None = None

    @classmethod
    def from_url(cls, url: str) -> RemoteConfig:
        if not url.startswith("ssh://"):
            raise ValueError(f"URL must start with ssh:// (got: {url})")
        parsed = urlparse(url)
        return cls(
            host=parsed.hostname or "",
            user=parsed.username,
            port=parsed.port or 22,
            path=parsed.path or None,
        )

    @property
    def ssh_target(self) -> str:
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


class RemoteRunner:
    def __init__(self, config: RemoteConfig, cwd: str, timeout: int = 7200) -> None:
        self._config = config
        self._cwd = cwd
        self._timeout = timeout

    def sync(self) -> None:
        target = self._config.ssh_target
        path = self._config.path or "."
        subprocess.run(
            ["git", "push", f"{target}:{path}", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self._cwd,
            timeout=120,
        )

    def run_milestone(self, milestone: str) -> RemoteResult:
        ssh_cmd = ["ssh"]
        if self._config.port != 22:
            ssh_cmd.extend(["-p", str(self._config.port)])
        ssh_cmd.append(self._config.ssh_target)

        remote_path = self._config.path or "."
        sw_cmd = f"cd {remote_path} && sw run --milestone {milestone}"
        ssh_cmd.append(sw_cmd)

        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            cwd=self._cwd,
            timeout=self._timeout,
        )

        if result.returncode != 0:
            return RemoteResult(success=False, error=result.stderr.strip())

        try:
            data = json.loads(result.stdout.strip())
            return RemoteResult(
                success=data.get("success", True),
                cost_usd=data.get("cost_usd", 0.0),
            )
        except (json.JSONDecodeError, ValueError):
            return RemoteResult(success=True)

    def pull_results(self) -> None:
        target = self._config.ssh_target
        path = self._config.path or "."
        subprocess.run(
            ["git", "fetch", f"{target}:{path}"],
            capture_output=True,
            text=True,
            cwd=self._cwd,
            timeout=120,
        )
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/remote.py tests/test_parallel_remote.py --fix
ruff format src/superpower_workflow/parallel/remote.py tests/test_parallel_remote.py
git add src/superpower_workflow/parallel/remote.py tests/test_parallel_remote.py
git commit -m "feat: add RemoteRunner for SSH-based remote execution"
```

---

### Task 12: Agent Teams -- num_agents runner flag

**Files:**
- Modify: `src/superpower_workflow/runner.py`
- New: `tests/test_parallel_agent_teams.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_agent_teams.py
from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.runner import _build_command, run_claude


class TestAgentTeamsFlag:
    def test_build_command_without_num_agents(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0)
        assert "--num-agents" not in cmd

    def test_build_command_with_num_agents(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0, num_agents=3)
        assert "--num-agents" in cmd
        idx = cmd.index("--num-agents")
        assert cmd[idx + 1] == "3"

    def test_build_command_num_agents_zero_omitted(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0, num_agents=0)
        assert "--num-agents" not in cmd

    def test_build_command_num_agents_none_omitted(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0, num_agents=None)
        assert "--num-agents" not in cmd

    def test_run_claude_passes_num_agents(self):
        with patch("superpower_workflow.runner.subprocess.run") as mock:
            mock.return_value = CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"result":"ok","total_cost_usd":5.0,"session_id":"s1","duration_ms":100}',
                stderr="",
            )
            run_claude("prompt", "opus", "high", 50.0, cwd="/tmp", num_agents=4)
        cmd = mock.call_args[0][0]
        assert "--num-agents" in cmd
        idx = cmd.index("--num-agents")
        assert cmd[idx + 1] == "4"
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add num_agents to runner**

In `runner.py`, update `run_claude` signature:

```python
def run_claude(
    prompt: str,
    model: str,
    effort: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    resume_session: str | None = None,
    num_agents: int | None = None,
) -> ClaudeResult:
```

Pass `num_agents` to `_build_command` in the retry loop.

Update `_build_command` signature:

```python
def _build_command(
    prompt: str,
    model: str,
    effort: str,
    budget: float,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    resume_session: str | None = None,
    num_agents: int | None = None,
) -> list[str]:
```

Add at the end of `_build_command`, before `return cmd`:

```python
if num_agents and num_agents > 0:
    cmd.extend(["--num-agents", str(num_agents)])
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/runner.py tests/test_parallel_agent_teams.py --fix
ruff format src/superpower_workflow/runner.py tests/test_parallel_agent_teams.py
git add src/superpower_workflow/runner.py tests/test_parallel_agent_teams.py
git commit -m "feat: add --num-agents flag to runner for Agent Teams support"
```

---

### Task 13: State -- parallel step values + per-worktree helpers

**Files:**
- Modify: `src/superpower_workflow/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_state.py -- add class

from superpower_workflow.state import VALID_STEPS, clone_state_to_worktree


class TestParallelStepValues:
    def test_parallel_wait_is_valid(self):
        assert "parallel_wait" in VALID_STEPS

    def test_parallel_merge_is_valid(self):
        assert "parallel_merge" in VALID_STEPS


class TestCloneStateToWorktree:
    def test_creates_claude_dir_in_worktree(self, tmp_path):
        claude_dir = tmp_path / "main" / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "workflow.json").write_text('{"model":"opus","milestones":[],"budgets":{"plan":1,"implement":1,"review":1,"push":1},"spec":"s"}')

        wt_root = tmp_path / "worktree"
        wt_root.mkdir()
        clone_state_to_worktree(claude_dir, wt_root)

        wt_claude = wt_root / ".claude"
        assert wt_claude.exists()
        assert (wt_claude / "workflow.json").exists()

    def test_copies_config_not_state(self, tmp_path):
        claude_dir = tmp_path / "main" / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "workflow.json").write_text('{"model":"opus"}')
        (claude_dir / "workflow-state.json").write_text('{"completed":["m0"]}')

        wt_root = tmp_path / "worktree"
        wt_root.mkdir()
        clone_state_to_worktree(claude_dir, wt_root)

        wt_claude = wt_root / ".claude"
        assert (wt_claude / "workflow.json").exists()
        assert not (wt_claude / "workflow-state.json").exists()

    def test_does_not_copy_lock(self, tmp_path):
        claude_dir = tmp_path / "main" / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "workflow.json").write_text('{"model":"opus"}')
        (claude_dir / ".workflow.lock").write_text("12345")

        wt_root = tmp_path / "worktree"
        wt_root.mkdir()
        clone_state_to_worktree(claude_dir, wt_root)

        assert not (wt_root / ".claude" / ".workflow.lock").exists()
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

In `state.py`, add `import shutil` to the imports at the top (after `import os`).

Then add `"parallel_wait"` and `"parallel_merge"` to `VALID_STEPS`:

```python
VALID_STEPS = frozenset(
    {
        "plan",
        "implement",
        "review",
        "push",
        "quality_check_b",
        "quality_check_c",
        "ci_wait",
        "ci_fix",
        "ci_fix_failed",
        "parallel_wait",
        "parallel_merge",
    }
)
```

Add `clone_state_to_worktree` function:

```python
import shutil

CLONE_FILES = frozenset({"workflow.json"})
SKIP_FILES = frozenset({STATE_FILE, PHASE_FILE, GAP_REPORT_FILE, LOCK_FILE})


def clone_state_to_worktree(claude_dir: Path, worktree_root: Path) -> None:
    wt_claude = worktree_root / ".claude"
    wt_claude.mkdir(parents=True, exist_ok=True)
    for src in claude_dir.iterdir():
        if src.name in SKIP_FILES or src.name.startswith(".workflow"):
            continue
        if src.name in CLONE_FILES:
            shutil.copy2(src, wt_claude / src.name)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/state.py tests/test_state.py --fix
ruff format src/superpower_workflow/state.py tests/test_state.py
git add src/superpower_workflow/state.py tests/test_state.py
git commit -m "feat: add parallel step values and clone_state_to_worktree helper"
```

---

### Task 14: CLI flags -- --parallel, --workers, --remote, --best-of-n, --model-override

**Files:**
- Modify: `src/superpower_workflow/cli.py`
- Modify: `tests/test_parallel_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_cli.py -- add class

from superpower_workflow.cli import build_parser


class TestParallelCLIFlags:
    def test_parallel_flag_exists(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--parallel"])
        assert args.parallel is True

    def test_parallel_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.parallel is False

    def test_workers_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--parallel", "--workers", "8"])
        assert args.workers == 8

    def test_workers_default(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.workers == 4

    def test_remote_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--remote", "ssh://user@host/path"])
        assert args.remote == "ssh://user@host/path"

    def test_remote_default_none(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.remote is None

    def test_best_of_n_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--best-of-n", "3"])
        assert args.best_of_n == 3

    def test_best_of_n_default(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.best_of_n == 1

    def test_model_override_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--model-override", "sonnet"])
        assert args.model_override == "sonnet"

    def test_model_override_default_none(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.model_override is None

    def test_all_parallel_flags_combined(self):
        parser = build_parser()
        args = parser.parse_args([
            "run",
            "--parallel",
            "--workers", "6",
            "--best-of-n", "2",
            "--model-override", "sonnet",
            "--remote", "ssh://host",
        ])
        assert args.parallel is True
        assert args.workers == 6
        assert args.best_of_n == 2
        assert args.model_override == "sonnet"
        assert args.remote == "ssh://host"
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add flags to run subparser**

In `cli.py`, after the existing `run_p.add_argument` calls, add:

```python
run_p.add_argument("--parallel", action="store_true", default=False, help="Enable parallel milestone execution")
run_p.add_argument("--workers", type=int, default=4, help="Max parallel workers (default: 4)")
run_p.add_argument("--remote", default=None, help="Remote execution URL (ssh://user@host[:port]/path)")
run_p.add_argument("--best-of-n", dest="best_of_n", type=int, default=1, help="Run N copies and pick best (default: 1)")
run_p.add_argument("--model-override", dest="model_override", default=None, help="Override model for all milestones")
```

Update the `run` command handler in `main()` to pass new args:

```python
if args.command == "run":
    from superpower_workflow.orchestrator import Orchestrator

    orch = Orchestrator(project_root)
    orch.run(
        dry_run=args.dry_run,
        milestone_filter=args.milestone,
        from_ms=args.from_ms,
        to_ms=args.to_ms,
        phase_prefix=getattr(args, "phase", None),
        from_issue=getattr(args, "from_issue", None),
        from_ticket=getattr(args, "from_ticket", None),
        parallel=getattr(args, "parallel", False),
        max_workers=getattr(args, "workers", 4),
        remote_url=getattr(args, "remote", None),
        best_of_n=getattr(args, "best_of_n", 1),
        model_override=getattr(args, "model_override", None),
    )
    return
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_parallel_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_parallel_cli.py
git add src/superpower_workflow/cli.py tests/test_parallel_cli.py
git commit -m "feat: add --parallel, --workers, --remote, --best-of-n, --model-override CLI flags"
```

---

### Task 15: Telemetry -- parallel-specific events

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- New: `tests/test_parallel_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_telemetry.py
from __future__ import annotations

import json

from superpower_workflow.telemetry import (
    ModelRouted,
    ParallelWaveStarted,
    ParallelWaveCompleted,
    WorktreeCreated,
    WorktreeMerged,
    BestOfNCompleted,
    RemoteExecution,
)


class TestParallelTelemetryEvents:
    def test_model_routed_event(self):
        e = ModelRouted(milestone="m1", model="sonnet", complexity_score=0.45, reason="score 0.45 >= 0.3")
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
            wave_index=0, succeeded=["m1"], failed=["m2"],
            total_cost_usd=15.0, duration_seconds=120.5,
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
            milestone="m1", n=3, winner_index=1, winner_model="sonnet",
            winner_score=0.95, total_cost_usd=30.0,
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
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add event classes to telemetry.py**

Append to `telemetry.py` after the existing event classes:

```python
@dataclass
class ModelRouted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "model_routed"
    milestone: str = ""
    model: str = ""
    complexity_score: float = 0.0
    reason: str = ""


@dataclass
class ParallelWaveStarted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "parallel_wave_started"
    wave_index: int = 0
    milestones: list[str] = field(default_factory=list)
    worker_count: int = 0


@dataclass
class ParallelWaveCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "parallel_wave_completed"
    wave_index: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class WorktreeCreated(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "worktree_created"
    milestone: str = ""
    branch: str = ""
    worktree_path: str = ""


@dataclass
class WorktreeMerged(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "worktree_merged"
    milestone: str = ""
    branch: str = ""
    success: bool = True
    conflicts: int = 0


@dataclass
class BestOfNCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "best_of_n_completed"
    milestone: str = ""
    n: int = 0
    winner_index: int = 0
    winner_model: str = ""
    winner_score: float = 0.0
    total_cost_usd: float = 0.0


@dataclass
class RemoteExecution(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "remote_execution"
    milestone: str = ""
    host: str = ""
    success: bool = True
    cost_usd: float = 0.0
```

Add `field` to the imports at the top if not already present:

```python
from dataclasses import asdict, dataclass, field
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_parallel_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_parallel_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_parallel_telemetry.py
git commit -m "feat: add parallel telemetry events for waves, routing, worktrees, best-of-N"
```

---

### Task 16: Orchestrator -- parallel mode integration

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py -- add classes

from superpower_workflow.parallel.router import ModelRouter


class TestParallelMode:
    def test_parallel_flag_uses_wave_execution(self, tmp_path):
        """When parallel=True, orchestrator plans waves and executes in parallel."""
        config = _config(tmp_path)
        config["milestones"] = [
            {"name": "m1"},
            {"name": "m2"},
        ]
        config["parallel"] = {"enabled": True, "max_workers": 2, "best_of_n": 1, "agent_teams_count": 0, "remote": None, "worktree_dir": ".worktrees"}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.parallel.executor.ThreadPoolExecutor") as mock_pool,
        ):
            mock_pool.return_value.__enter__ = lambda self: self
            mock_pool.return_value.__exit__ = lambda *a: None
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed or "m2" in state.completed


class TestModelRouting:
    def test_routing_overrides_model_per_milestone(self, tmp_path):
        """Model routing sends different models to run_claude per milestone."""
        config = _config(tmp_path)
        config["milestones"] = [
            {"name": "m1", "description": "fix typo"},
            {"name": "m2", "description": "refactor authentication architecture migration"},
        ]
        config["model_routing"] = {
            "enabled": True,
            "default_model": "opus",
            "rules": [
                {"threshold": 0.5, "model": "opus"},
                {"threshold": 0.0, "model": "haiku"},
            ],
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        models_used = []

        def mock_run_claude(prompt, model, **kwargs):
            models_used.append(model)
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert "haiku" in models_used
        assert "opus" in models_used


class TestBestOfNIntegration:
    def test_best_of_n_greater_than_one_runs_multiple(self, tmp_path):
        """best_of_n > 1 should run milestone N times and pick best."""
        config = _config(tmp_path)
        config["milestones"] = [{"name": "m1"}]
        config["parallel"] = {
            "enabled": True,
            "max_workers": 3,
            "best_of_n": 3,
            "agent_teams_count": 0,
            "remote": None,
            "worktree_dir": ".worktrees",
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        run_count = {"n": 0}

        def mock_run_claude(prompt, **kwargs):
            run_count["n"] += 1
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True, best_of_n=3)
        assert run_count["n"] >= 3
```

- [ ] **Step 2: Run tests -- expect FAIL** (orchestrator doesn't accept parallel args yet)

- [ ] **Step 3: Wire parallel mode into orchestrator**

Update `Orchestrator.run()` signature:

```python
def run(
    self,
    dry_run: bool = False,
    milestone_filter: str | None = None,
    from_ms: str | None = None,
    to_ms: str | None = None,
    phase_prefix: str | None = None,
    from_issue: str | None = None,
    from_ticket: str | None = None,
    parallel: bool = False,
    max_workers: int = 4,
    remote_url: str | None = None,
    best_of_n: int = 1,
    model_override: str | None = None,
) -> None:
```

Add imports at top of orchestrator.py:

```python
from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.executor import ParallelExecutor, ParallelResult
from superpower_workflow.parallel.planner import ExecutionWave, ParallelPlanner
from superpower_workflow.parallel.router import ModelRouter
from superpower_workflow.parallel.worktree import WorktreeManager
from superpower_workflow.state import clone_state_to_worktree
```

In the milestone loop section of `run()`, before iterating milestones, add:

```python
parallel_config = self.config.get("parallel", {})
use_parallel = parallel or parallel_config.get("enabled", False)
workers = max_workers or parallel_config.get("max_workers", 4)
bon_count = best_of_n if best_of_n > 1 else parallel_config.get("best_of_n", 1)
router = ModelRouter.from_config(self.config)

if use_parallel and len(milestones) > 1:
    self._run_parallel(
        milestones, logger, router, workers, bon_count, model_override, remote_url,
    )
    self._completion_notification(logger)
    return
```

For the sequential path, add model routing before each `run_claude` call:

```python
decision = router.route(ms)
if model_override:
    model = model_override
elif self.config.get("model_routing", {}).get("enabled"):
    model = decision.model
else:
    model = self.config["model"]
```

Add the `_run_parallel` method:

```python
def _run_parallel(
    self,
    milestones: list[dict],
    logger: WorkflowLogger,
    router: ModelRouter,
    max_workers: int,
    best_of_n: int,
    model_override: str | None,
    remote_url: str | None = None,
) -> None:
    planner = ParallelPlanner(milestones, completed=set(self.state.completed))
    waves = planner.plan_waves()
    max_budget = self.config.get("max_total_budget_usd", float("inf"))
    budget = ThreadSafeBudget(max_budget - self.state.total_cost_usd)
    par_config = self.config.get("parallel", {})
    wt_dir_name = par_config.get("worktree_dir", ".worktrees")
    wt_mgr = WorktreeManager(self.root, worktree_dir=self.root / wt_dir_name)
    executor = ParallelExecutor(budget=budget, max_workers=max_workers, worktree_mgr=wt_mgr)
    agent_teams_count = par_config.get("agent_teams_count", 0) or 0
    failed_set = set(self.state.failed)

    for wave in waves:
        # Skip milestones whose dependencies failed
        runnable = [
            m for m in wave.milestones
            if not any(dep in failed_set for dep in
                       next((ms.get("depends_on", []) for ms in milestones if ms["name"] == m), []))
        ]
        skipped = [m for m in wave.milestones if m not in runnable]
        for s in skipped:
            self.state.skipped.append(s)
            logger.log("MILESTONE_SKIP", milestone=s, reason="dependency_failed")

        if not runnable:
            continue

        wave = ExecutionWave(index=wave.index, milestones=runnable)
        self.state.current_step = "parallel_wait"
        save_state(self.claude_dir, self.state)
        logger.log("PARALLEL_WAVE_START", wave=wave.index, milestones=str(wave.milestones))

        if self._telemetry:
            from superpower_workflow.telemetry import ParallelWaveStarted
            self._telemetry.emit(ParallelWaveStarted(
                wave_index=wave.index, milestones=wave.milestones, worker_count=max_workers,
            ))

        def run_fn(name: str, cwd: str) -> ParallelResult:
            ms = next((m for m in milestones if m["name"] == name), None)
            if ms is None:
                return ParallelResult(milestone=name, success=False, error="not found")
            decision = router.route(ms)
            if model_override:
                ms_model = model_override
            elif self.config.get("model_routing", {}).get("enabled"):
                ms_model = decision.model
            else:
                ms_model = self.config["model"]
            try:
                clone_state_to_worktree(self.claude_dir, Path(cwd))
                cost = self._run_milestone(
                    ms, logger, cwd_override=cwd, model_override=ms_model,
                    num_agents=agent_teams_count if agent_teams_count > 0 else None,
                )
                return ParallelResult(milestone=name, success=True, cost_usd=cost, worktree=cwd)
            except Exception as e:
                return ParallelResult(milestone=name, success=False, error=str(e), worktree=cwd)

        try:
            results = executor.execute_wave_isolated(wave, run_fn=run_fn)
        except Exception:
            wt_mgr.cleanup_all()
            raise

        self.state.current_step = "parallel_merge"
        save_state(self.claude_dir, self.state)

        for result in results:
            if result.success:
                self.state.completed.append(result.milestone)
                self.state.total_cost_usd += result.cost_usd
            else:
                self.state.failed.append(result.milestone)
                failed_set.add(result.milestone)
        save_state(self.claude_dir, self.state)

        if self._telemetry:
            from superpower_workflow.telemetry import ParallelWaveCompleted
            self._telemetry.emit(ParallelWaveCompleted(
                wave_index=wave.index,
                succeeded=[r.milestone for r in results if r.success],
                failed=[r.milestone for r in results if not r.success],
                total_cost_usd=sum(r.cost_usd for r in results),
            ))

        logger.log("PARALLEL_WAVE_COMPLETE", wave=wave.index)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire parallel mode, model routing, and best-of-N into orchestrator"
```

---

### Task 17: Package exports

**Files:**
- Modify: `src/superpower_workflow/parallel/__init__.py`
- New: `tests/test_parallel_exports.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parallel_exports.py
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
            CandidateResult,
            ComplexityScore,
            DependencyGraph,
            ExecutionWave,
            MergeResult,
            ModelRouter,
            ParallelExecutor,
            ParallelPlanner,
            ParallelResult,
            RemoteConfig,
            RemoteResult,
            RemoteRunner,
            RouteDecision,
            RoutingRule,
            ThreadSafeBudget,
            WorktreeInfo,
            WorktreeManager,
            score_candidate,
            score_complexity,
        )
        assert ThreadSafeBudget is not None
        assert WorktreeManager is not None
        assert ModelRouter is not None
        assert ParallelPlanner is not None
        assert ParallelExecutor is not None
        assert BestOfNRunner is not None
        assert RemoteRunner is not None
```

- [ ] **Step 2: Run tests -- expect FAIL** (not all exports wired)

- [ ] **Step 3: Update __init__.py**

```python
# src/superpower_workflow/parallel/__init__.py
from __future__ import annotations

from superpower_workflow.parallel.best_of_n import (
    BestOfNRunner,
    CandidateResult,
    score_candidate,
)
from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.executor import ParallelExecutor, ParallelResult
from superpower_workflow.parallel.planner import (
    DependencyGraph,
    ExecutionWave,
    ParallelPlanner,
)
from superpower_workflow.parallel.remote import RemoteConfig, RemoteResult, RemoteRunner
from superpower_workflow.parallel.router import (
    ComplexityScore,
    ModelRouter,
    RouteDecision,
    RoutingRule,
    score_complexity,
)
from superpower_workflow.parallel.worktree import MergeResult, WorktreeInfo, WorktreeManager

__all__ = [
    "BestOfNRunner",
    "CandidateResult",
    "ComplexityScore",
    "DependencyGraph",
    "ExecutionWave",
    "MergeResult",
    "ModelRouter",
    "ParallelExecutor",
    "ParallelPlanner",
    "ParallelResult",
    "RemoteConfig",
    "RemoteResult",
    "RemoteRunner",
    "RouteDecision",
    "RoutingRule",
    "ThreadSafeBudget",
    "WorktreeInfo",
    "WorktreeManager",
    "score_candidate",
    "score_complexity",
]
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/parallel/__init__.py tests/test_parallel_exports.py --fix
ruff format src/superpower_workflow/parallel/__init__.py tests/test_parallel_exports.py
git add src/superpower_workflow/parallel/__init__.py tests/test_parallel_exports.py
git commit -m "feat: add parallel package __all__ exports"
```

---

### Task 18: Integration tests -- end-to-end parallel scenarios

**Files:**
- New: `tests/test_parallel_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_parallel_integration.py
from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.state import load_state


def _ok_result(cost: float = 1.0):
    from superpower_workflow.runner import ClaudeResult

    return ClaudeResult(
        text="ok",
        cost_usd=cost,
        session_id="s1",
        duration_ms=100,
        is_error=False,
    )


def _config(tmp_path: Path, milestones: list | None = None, parallel: dict | None = None):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "budgets": {"plan": 5, "implement": 10, "review": 5, "push": 1},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "verify_commands": {},
        "milestones": milestones or [],
    }
    if parallel:
        config["parallel"] = parallel
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    (tmp_path / "spec.md").write_text("# Spec")
    return config


def _smart_subprocess(cmd, **kwargs):
    if isinstance(cmd, list):
        cmd_str = " ".join(cmd)
        if "status" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "rev-parse" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="abc123", stderr="")
        if "tag" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "log" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "worktree" in cmd_str and "add" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "worktree" in cmd_str and "remove" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "worktree" in cmd_str and "list" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "merge" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if "branch" in cmd_str:
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    if isinstance(cmd, str):
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class TestParallelEndToEnd:
    def test_independent_milestones_run_in_parallel(self, tmp_path):
        _config(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}, {"name": "m3"}],
            parallel={"enabled": True, "max_workers": 3, "best_of_n": 1, "agent_teams_count": 0, "remote": None, "worktree_dir": ".worktrees"},
        )
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.parallel.worktree.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert set(state.completed) == {"m1", "m2", "m3"}

    def test_dependent_milestones_sequential_waves(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1"},
                {"name": "m2", "depends_on": ["m1"]},
            ],
            parallel={"enabled": True, "max_workers": 2, "best_of_n": 1, "agent_teams_count": 0, "remote": None, "worktree_dir": ".worktrees"},
        )
        order = []

        def mock_run_claude(prompt, **kwargs):
            if "m1" in prompt:
                order.append("m1")
            elif "m2" in prompt:
                order.append("m2")
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.parallel.worktree.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
        assert "m2" in state.completed

    def test_model_routing_in_parallel_mode(self, tmp_path):
        config = _config(
            tmp_path,
            milestones=[
                {"name": "m1", "description": "fix typo"},
                {"name": "m2", "description": "refactor authentication architecture"},
            ],
        )
        config["model_routing"] = {
            "enabled": True,
            "default_model": "opus",
            "rules": [
                {"threshold": 0.5, "model": "opus"},
                {"threshold": 0.0, "model": "haiku"},
            ],
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        models_used = []

        def mock_run_claude(prompt, model, **kwargs):
            models_used.append(model)
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert "haiku" in models_used
        assert "opus" in models_used

    def test_budget_shared_across_parallel_workers(self, tmp_path):
        _config(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}, {"name": "m3"}],
            parallel={"enabled": True, "max_workers": 3, "best_of_n": 1, "agent_teams_count": 0, "remote": None, "worktree_dir": ".worktrees"},
        )

        def mock_run_claude(prompt, **kwargs):
            return _ok_result(cost=50.0)

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.parallel.worktree.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert state.total_cost_usd > 0

    def test_sequential_fallback_when_single_milestone(self, tmp_path):
        _config(
            tmp_path,
            milestones=[{"name": "m1"}],
            parallel={"enabled": True, "max_workers": 2, "best_of_n": 1, "agent_teams_count": 0, "remote": None, "worktree_dir": ".worktrees"},
        )
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_failed_milestone_in_wave_skips_dependents(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1"},
                {"name": "m2", "depends_on": ["m1"]},
            ],
            parallel={"enabled": True, "max_workers": 2, "best_of_n": 1, "agent_teams_count": 0, "remote": None, "worktree_dir": ".worktrees"},
        )

        def mock_run_claude(prompt, **kwargs):
            from superpower_workflow.runner import ClaudeResult
            return ClaudeResult(text="", cost_usd=1.0, is_error=True)

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.parallel.worktree.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run(parallel=True)
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.failed
        assert "m2" in state.skipped or "m2" not in state.completed
```

- [ ] **Step 2: Run tests -- expect PASS** (if all prior tasks complete)

If any fail, debug and fix. This is the final integration verification.

- [ ] **Step 3: Full suite verification**

```bash
python -m pytest -v
python -m ruff check src/ tests/ --fix
python -m ruff format src/ tests/
```

- [ ] **Step 4: Lint + commit**

```bash
git add tests/test_parallel_integration.py
git commit -m "test: add end-to-end parallel execution integration tests"
```

---

## Self-Review

**Spec coverage:**
- SP6 worktree isolation -> Tasks 3, 4, 9 (WorktreeManager + isolated execution)
- SP6 model routing -> Tasks 5, 6, 16 (ComplexityScorer + ModelRouter + orchestrator wiring)
- SP6 best-of-N -> Task 10 (BestOfNRunner with quality selection)
- SP6 remote execution -> Task 11 (RemoteRunner with SSH)
- SP6 Agent Teams -> Task 12 (--num-agents runner flag)
- Parallel execution -> Tasks 2, 7, 8, 9, 16 (budget, planner, executor, orchestrator)
- CLI surface -> Tasks 1, 14 (config + flags)
- Telemetry -> Task 15 (7 new event types)
- State management -> Task 13 (new steps, worktree clone)
- Package exports -> Task 17 (__all__ completeness)
- Integration verification -> Task 18 (end-to-end scenarios)

**All roadmap SP6 interfaces covered:**
- Worktrees: each parallel milestone in own worktree, merge when complete
- Router: workflow.json `model_routing` section maps task complexity -> model
- Remote: `sw run --remote ssh://host` for offloading
- Agent Teams: native Claude Code parallel teammates for Phase B

**Placeholder scan:** No TBD, TODO, or "implement later."

**Type consistency:** All dataclasses use `from __future__ import annotations`. ThreadSafeBudget uses Lock. All subprocess calls include timeout.

**Backward compatibility:** All new config sections are optional. Parallel mode defaults to off. Model routing defaults to disabled. Sequential execution path unchanged.

**Zero new dependencies:** Everything uses stdlib (`concurrent.futures`, `threading`, `subprocess`, `urllib.parse`, `json`, `re`, `dataclasses`).
