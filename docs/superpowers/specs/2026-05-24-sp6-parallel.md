# SP6: Parallel & Multi-Model -- Design Spec

**Date:** 2026-05-24
**Spec version:** 1.0
**Status:** Draft
**Roadmap:** SP6 of 7 -> v0.7.0
**Goal:** Run multiple subagents concurrently with git-level isolation, route tasks to the right model by complexity, and support remote execution for scale.

**Depends on:** SP1 (quality gates run per agent, must work in worktree context).

---

## 1. Overview

Five capabilities:

1. **Git worktree isolation** -- each Phase B subagent runs in its own worktree, merge when done
2. **Multi-model routing** -- route tasks by complexity (simple -> haiku, standard -> sonnet, complex -> opus)
3. **Best-of-N execution** -- for critical tasks, run on N models, diff results, pick better
4. **Remote execution** -- `sw run --remote ssh://host` to execute phases on remote machine
5. **Agent Teams integration** -- use Claude Code native Agent Teams for Phase B parallelism

---

## 2. Git Worktree Isolation

### Setup

Before dispatching Phase B subagents:

```python
def create_worktree(task_name: str, base_sha: str) -> Path:
    wt_path = Path(".worktrees") / task_name
    subprocess.run(
        ["git", "worktree", "add", str(wt_path), base_sha],
        check=True, timeout=30,
    )
    return wt_path
```

### Merge strategy

After subagent completes in worktree:

1. Attempt fast-forward merge: `git merge --ff-only worktree-branch`
2. If fast-forward fails (divergent work), create merge commit: `git merge --no-edit worktree-branch`
3. If merge conflicts, invoke claude -p with conflict markers to resolve
4. Clean up: `git worktree remove .worktrees/{task_name}`

### Ordering

Tasks merge in dependency order (from the plan). Independent tasks merge in completion order. The orchestrator maintains a merge queue to prevent concurrent merges.

### State tracking

Each worktree gets its own `.workflow-phase.json` scoped to its directory. The parent orchestrator tracks all active worktrees in workflow-state.json:

```json
{
  "active_worktrees": [
    {"task": "task-1", "path": ".worktrees/task-1", "status": "running"},
    {"task": "task-2", "path": ".worktrees/task-2", "status": "merging"}
  ]
}
```

---

## 3. Multi-Model Routing

### Config (workflow.json)

```json
{
  "model_routing": {
    "simple_threshold": 5,
    "complex_threshold": 15,
    "models": {
      "simple": "claude-haiku-4",
      "standard": "claude-sonnet-4",
      "complex": "claude-opus-4"
    }
  }
}
```

### Complexity scoring

Task complexity = number of steps in the plan for that task. Determined during Phase A decomposition.

- Steps <= `simple_threshold` -> simple model
- Steps > `simple_threshold` and <= `complex_threshold` -> standard model
- Steps > `complex_threshold` -> complex model

### Router implementation

```python
def select_model(task_step_count: int, config: dict) -> str:
    routing = config.get("model_routing", {})
    if not routing:
        return config.get("model", "claude-sonnet-4")
    simple = routing.get("simple_threshold", 5)
    complex_ = routing.get("complex_threshold", 15)
    models = routing.get("models", {})
    if task_step_count <= simple:
        return models.get("simple", "claude-haiku-4")
    elif task_step_count > complex_:
        return models.get("complex", "claude-opus-4")
    return models.get("standard", "claude-sonnet-4")
```

### Override

Per-milestone override: `"model": "claude-opus-4"` in the milestone spec forces a specific model regardless of routing.

---

## 4. Best-of-N Execution

### Config (per milestone)

```json
{
  "milestones": [{
    "name": "critical-refactor",
    "best_of_n": {
      "n": 2,
      "models": ["claude-sonnet-4", "claude-opus-4"],
      "selection": "quality_score"
    }
  }]
}
```

### Flow

1. Run Phase B for the task on each of the N models (in parallel, each in its own worktree)
2. After all complete, score each result:
   - Lint warning count (lower is better)
   - Test pass rate (higher is better)
   - Coverage delta (higher is better)
   - Quality gate pass/fail from SP1
3. Select the result with the best composite score
4. Merge the winning worktree, discard losers

### Cost control

Best-of-N multiplies cost by N. Config includes `max_cost_multiplier` (default 3x) -- if estimated cost exceeds this, fall back to single execution.

---

## 5. Remote Execution

### CLI

```
sw run --remote ssh://user@host:/path/to/project
```

### Flow

1. `rsync -az --exclude .git ./ user@host:/path/to/project/`
2. `ssh user@host "cd /path/to/project && sw run --local"` (--local skips remote dispatch)
3. Poll for completion via `ssh user@host "sw status --json"`
4. `rsync -az user@host:/path/to/project/ ./` to pull results back
5. Commit any remote changes locally

### Requirements

- SSH key auth configured (no password prompts)
- `sw` installed on remote machine
- `claude` CLI available on remote machine

### Config

```json
{
  "remote": {
    "host": "ssh://user@host",
    "project_path": "/path/to/project",
    "exclude": [".git", "node_modules", ".venv"]
  }
}
```

---

## 6. Agent Teams Integration

### Activation

Set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in the environment before spawning Phase B.

### Flow

Instead of sequential subagent-driven-development, the orchestrator:

1. Decomposes Phase B tasks into independent groups
2. Dispatches each group as a "teammate" via the Agent Teams API
3. Each teammate runs in its own worktree (reuses Section 2)
4. Teammates coordinate via the Agent Teams protocol (shared context, no merge conflicts)

### Fallback

If Agent Teams is not available (env var unset or API unavailable), fall back to sequential execution with worktree isolation.

---

## 7. Files Changed

| File | Change |
|---|---|
| `src/superpower_workflow/parallel/__init__.py` | Package init |
| `src/superpower_workflow/parallel/worktree.py` | Worktree create/merge/cleanup, merge queue |
| `src/superpower_workflow/parallel/router.py` | Model routing by task complexity |
| `src/superpower_workflow/parallel/best_of_n.py` | Best-of-N execution, scoring, selection |
| `src/superpower_workflow/parallel/remote.py` | SSH + rsync remote execution |
| `src/superpower_workflow/orchestrator.py` | Parallel dispatch, worktree lifecycle, Agent Teams |
| `src/superpower_workflow/runner.py` | Accept model parameter from router |
| `src/superpower_workflow/state.py` | active_worktrees tracking |
| `tests/test_parallel.py` | Tests for worktree, router, best-of-N, remote |

---

## 8. Open Questions

- Should merge conflicts trigger a quality gate re-run on the merged result?
- What happens if a remote machine runs out of disk during rsync?
- Should best-of-N scoring weights be user-configurable?
- How should Agent Teams interact with SP1 quality gates (per-teammate or post-merge)?
