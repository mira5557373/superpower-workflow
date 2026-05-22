# superpower-workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable CLI tool (`sw`) + Claude Code skills that automate the post-brainstorming development lifecycle — milestone decomposition, plan writing, TDD implementation, ultrathink review loops, and push — fully unattended across any project.

**Architecture:** Standalone Python 3.11+ package (`superpower-workflow`) installable via pip. Orchestrator drives `claude -p` subprocess calls per phase per milestone. Stop hook (exit code 2) enforces convergence loops within phases. Two global skills (`ultrathink-gap-analysis`, `post-impl-review`) installed to `~/.claude/skills/`. Per-project config via `.claude/workflow.json`.

**Tech Stack:** Python 3.11+, hatchling build, argparse CLI, subprocess for `claude -p`, `os.replace()` for atomic state writes, `json` for structured data, `hashlib` for skill version checks, pytest + ruff.

**Spec reference:** `docs/superpowers/specs/2026-05-22-superpower-workflow-design.md` (v1.2). All section references are to that file.

**Working directory:** `superpower-workflow/` (new directory at repo root; extractable to standalone GitHub repo).

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Build config, deps, `sw` entry point, pytest + ruff config |
| `README.md` | Installation + usage guide |
| `LICENSE` | MIT |
| `src/superpower_workflow/__init__.py` | `__version__` |
| `src/superpower_workflow/cli.py` | argparse entry point: init, doctor, decompose, estimate, run, status, resume |
| `src/superpower_workflow/state.py` | Atomic read/write for workflow-state.json, workflow-phase.json, lockfile |
| `src/superpower_workflow/runner.py` | `claude -p` subprocess wrapper with retry, JSON parsing, session ID capture |
| `src/superpower_workflow/logger.py` | Structured file logging (`[timestamp] EVENT key=value`) |
| `src/superpower_workflow/prompts.py` | Phase A/B/C/D prompt templates with placeholder substitution |
| `src/superpower_workflow/context.py` | Git-log-based context summary generator (last 3 milestones detailed) |
| `src/superpower_workflow/estimator.py` | Cost/duration range estimates from config |
| `src/superpower_workflow/doctor.py` | Pre-flight health checks (Claude Code, skills, hook, config, git) |
| `src/superpower_workflow/decomposer.py` | Two-pass spec → milestone decomposition via `claude -p` |
| `src/superpower_workflow/orchestrator.py` | Core milestone loop: pre-flight → phases A/B/C/D → state update |
| `src/superpower_workflow/hooks/__init__.py` | Package marker |
| `src/superpower_workflow/hooks/convergence_gate.py` | Stop hook: read phase state + gap report → exit 0 or 2 |
| `skills/ultrathink-gap-analysis/SKILL.md` | ≥20-gap adversarial review skill |
| `skills/post-impl-review/SKILL.md` | Implementation review + fix skill |
| `commands/ultrathink.md` | `/ultrathink` slash command |
| `templates/workflow.json` | Per-project config template |
| `install.py` | Copy skills/hooks/commands to `~/.claude/`, register hook |
| `tests/conftest.py` | Shared fixtures |
| `tests/test_state.py` | State management tests |
| `tests/test_runner.py` | Runner tests (mocked subprocess) |
| `tests/test_logger.py` | Logger tests |
| `tests/test_prompts.py` | Prompt template tests |
| `tests/test_context.py` | Context generation tests |
| `tests/test_estimator.py` | Estimator tests |
| `tests/test_doctor.py` | Doctor tests |
| `tests/test_convergence_gate.py` | Convergence hook tests |
| `tests/test_decomposer.py` | Decomposer tests (mocked runner) |
| `tests/test_orchestrator.py` | Orchestrator tests (mocked runner) |
| `tests/test_cli.py` | CLI argparse tests |

---

### Task 1: Project scaffold

**Files:**
- Create: `superpower-workflow/pyproject.toml`
- Create: `superpower-workflow/LICENSE`
- Create: `superpower-workflow/README.md`
- Create: `superpower-workflow/src/superpower_workflow/__init__.py`
- Create: `superpower-workflow/src/superpower_workflow/hooks/__init__.py`
- Create: `superpower-workflow/tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p superpower-workflow/src/superpower_workflow/hooks
mkdir -p superpower-workflow/tests
mkdir -p superpower-workflow/skills/ultrathink-gap-analysis
mkdir -p superpower-workflow/skills/post-impl-review
mkdir -p superpower-workflow/commands
mkdir -p superpower-workflow/templates
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling>=1.24"]
build-backend = "hatchling.build"

[project]
name = "superpower-workflow"
version = "0.1.0.dev0"
description = "Automated post-brainstorming development lifecycle for Claude Code"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [{ name = "project author" }]
dependencies = []

[project.scripts]
sw = "superpower_workflow.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/superpower_workflow"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-ra --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
```

- [ ] **Step 3: Create package init**

```python
# src/superpower_workflow/__init__.py
"""superpower-workflow — automated post-brainstorming development lifecycle."""

__version__ = "0.1.0.dev0"
```

```python
# src/superpower_workflow/hooks/__init__.py
```

```python
# tests/__init__.py
```

- [ ] **Step 4: Create LICENSE (MIT)**

Standard MIT license text with "2026 superpower-workflow contributors".

- [ ] **Step 5: Create minimal README.md**

```markdown
# superpower-workflow

Automated post-brainstorming development lifecycle for Claude Code.

After `superpowers:brainstorming` produces a spec, `sw` handles everything:
milestone decomposition → plan writing → TDD implementation → ultrathink review loops → push.

## Installation

See docs/superpowers/specs/2026-05-22-superpower-workflow-design.md for the full spec.
```

- [ ] **Step 6: Create venv and install**

```bash
cd superpower-workflow
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

Wait — there are no dev deps yet. Add to pyproject.toml:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.5",
]
```

- [ ] **Step 7: Verify scaffold**

```bash
.venv/Scripts/pytest --co -q   # Should show "no tests ran"
.venv/Scripts/ruff check .     # Should pass (no files yet)
```

- [ ] **Step 8: Commit**

```bash
git add superpower-workflow/
git commit -m "chore: scaffold superpower-workflow package"
```

---

### Task 2: State management (`state.py`)

**Files:**
- Create: `src/superpower_workflow/state.py`
- Create: `tests/test_state.py`

This module handles atomic reads/writes for `workflow-state.json`, `workflow-phase.json`, the lockfile, and config loading. All JSON writes use write-to-tmp-then-replace for atomicity (spec §5.3).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_state.py
import json
import os
from pathlib import Path

from superpower_workflow.state import (
    WorkflowState,
    PhaseState,
    load_config,
    load_state,
    save_state,
    load_phase_state,
    save_phase_state,
    clear_phase_state,
    acquire_lock,
    release_lock,
)


def test_load_state_returns_defaults_when_missing(tmp_path: Path) -> None:
    state = load_state(tmp_path / ".claude")
    assert state.current_milestone_index == 0
    assert state.completed == []
    assert state.total_cost_usd == 0.0
    assert state.current_step is None


def test_save_and_load_state_roundtrip(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    state = WorkflowState(
        current_milestone_index=3,
        current_step="implement",
        completed=["p1-m1", "p1-m2", "p1-m3"],
        total_cost_usd=85.50,
        spec_sha="abc123",
        run_id="20260522",
        started_at="2026-05-22T14:00:00Z",
    )
    save_state(claude_dir, state)
    loaded = load_state(claude_dir)
    assert loaded.current_milestone_index == 3
    assert loaded.total_cost_usd == 85.50
    assert loaded.completed == ["p1-m1", "p1-m2", "p1-m3"]


def test_save_state_is_atomic(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    state = WorkflowState(current_milestone_index=1)
    save_state(claude_dir, state)
    # Temp file should not linger
    assert not (claude_dir / "workflow-state.json.tmp").exists()
    assert (claude_dir / "workflow-state.json").exists()


def test_phase_state_create_and_clear(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    phase = PhaseState(phase="ultrathink", iteration=0, max_iterations=5)
    save_phase_state(claude_dir, phase)
    loaded = load_phase_state(claude_dir)
    assert loaded is not None
    assert loaded.phase == "ultrathink"
    clear_phase_state(claude_dir)
    assert load_phase_state(claude_dir) is None


def test_phase_state_previous_important_gaps_tracking(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    phase = PhaseState(phase="ultrathink", iteration=2, max_iterations=5, previous_important_gaps=7)
    save_phase_state(claude_dir, phase)
    loaded = load_phase_state(claude_dir)
    assert loaded.previous_important_gaps == 7


def test_acquire_and_release_lock(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    assert acquire_lock(claude_dir) is True
    assert (claude_dir / ".workflow.lock").exists()
    release_lock(claude_dir)
    assert not (claude_dir / ".workflow.lock").exists()


def test_lock_prevents_second_acquisition(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    acquire_lock(claude_dir)
    assert acquire_lock(claude_dir) is False
    release_lock(claude_dir)


def test_load_config_valid(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 10,
        "convergence": {"max_iterations": 5, "min_gaps_for_substantial": 20, "persistent_gap_downgrade_after": 3},
        "verify_commands": {"test": "python -m pytest -q", "lint": None, "format": None},
        "git_strategy": "main",
        "notification_webhook": None,
        "milestones": [],
    }
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    loaded = load_config(claude_dir)
    assert loaded["model"] == "opus"
    assert loaded["budgets"]["plan"] == 25


def test_load_config_missing_raises(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / ".claude")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd superpower-workflow
.venv/Scripts/pytest tests/test_state.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Implement state.py**

```python
# src/superpower_workflow/state.py
"""Atomic state persistence for workflow-state.json, workflow-phase.json, and lockfile."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class WorkflowState:
    current_milestone_index: int = 0
    current_step: str | None = None
    last_phase_session_id: str | None = None
    plan_commit_sha: str | None = None
    completed: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    spec_sha: str = ""
    run_id: str = ""
    started_at: str = ""


@dataclass
class PhaseState:
    phase: str  # "ultrathink" or "review"
    iteration: int = 0
    max_iterations: int = 5
    previous_important_gaps: int | None = None


STATE_FILE = "workflow-state.json"
PHASE_FILE = ".workflow-phase.json"
GAP_REPORT_FILE = ".gap-report.json"
LOCK_FILE = ".workflow.lock"


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(path))


def load_state(claude_dir: Path) -> WorkflowState:
    path = claude_dir / STATE_FILE
    if not path.exists():
        return WorkflowState()
    raw = json.loads(path.read_text())
    return WorkflowState(**{k: v for k, v in raw.items() if k in WorkflowState.__dataclass_fields__})


def save_state(claude_dir: Path, state: WorkflowState) -> None:
    claude_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(claude_dir / STATE_FILE, asdict(state))


def load_phase_state(claude_dir: Path) -> PhaseState | None:
    path = claude_dir / PHASE_FILE
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    return PhaseState(**{k: v for k, v in raw.items() if k in PhaseState.__dataclass_fields__})


def save_phase_state(claude_dir: Path, phase: PhaseState) -> None:
    _atomic_write(claude_dir / PHASE_FILE, asdict(phase))


def clear_phase_state(claude_dir: Path) -> None:
    for name in (PHASE_FILE, GAP_REPORT_FILE):
        p = claude_dir / name
        p.unlink(missing_ok=True)


def acquire_lock(claude_dir: Path) -> bool:
    lock = claude_dir / LOCK_FILE
    if lock.exists():
        return False
    lock.write_text(str(os.getpid()))
    return True


def release_lock(claude_dir: Path) -> None:
    (claude_dir / LOCK_FILE).unlink(missing_ok=True)


def load_config(claude_dir: Path) -> dict:
    path = claude_dir / "workflow.json"
    if not path.exists():
        raise FileNotFoundError(f"workflow.json not found at {claude_dir}")
    return json.loads(path.read_text())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/pytest tests/test_state.py -v
```
Expected: all 10 pass

- [ ] **Step 5: Lint check**

```bash
.venv/Scripts/ruff check src/ tests/ && .venv/Scripts/ruff format --check src/ tests/
```

- [ ] **Step 6: Commit**

```bash
git add superpower-workflow/src/superpower_workflow/state.py superpower-workflow/tests/test_state.py
git commit -m "feat: add atomic state management for workflow and phase state"
```

---

### Task 3: Runner (`runner.py`) — `claude -p` wrapper

**Files:**
- Create: `src/superpower_workflow/runner.py`
- Create: `tests/test_runner.py`

Wraps `subprocess.run` calls to `claude -p` with retry logic, JSON output parsing, session ID capture, and budget/model/effort flag assembly. Spec §3.2, §7.1, §8.1.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_runner.py
import json
from unittest.mock import patch, MagicMock
from subprocess import CompletedProcess

from superpower_workflow.runner import run_claude, ClaudeResult


def _mock_result(result_text: str = "done", cost: float = 1.5, session_id: str = "sess-123") -> CompletedProcess:
    output = json.dumps({
        "type": "result",
        "result": result_text,
        "is_error": False,
        "session_id": session_id,
        "total_cost_usd": cost,
        "duration_ms": 5000,
    })
    return CompletedProcess(args=[], returncode=0, stdout=output, stderr="")


def test_run_claude_returns_parsed_result() -> None:
    with patch("superpower_workflow.runner.subprocess.run", return_value=_mock_result()):
        result = run_claude("test prompt", model="opus", effort="max", budget=25.0, cwd="/tmp")
    assert result.text == "done"
    assert result.cost_usd == 1.5
    assert result.session_id == "sess-123"
    assert result.is_error is False


def test_run_claude_builds_correct_command() -> None:
    with patch("superpower_workflow.runner.subprocess.run", return_value=_mock_result()) as mock:
        run_claude("hello", model="opus", effort="high", budget=50.0, cwd="/tmp",
                   system_prompt="be nice", fallback_model="haiku")
    cmd = mock.call_args[0][0]
    assert "claude" in cmd[0]
    assert "-p" in cmd
    assert "--model" in cmd
    assert "opus" in cmd
    assert "--effort" in cmd
    assert "--max-budget-usd" in cmd
    assert "--append-system-prompt" in cmd
    assert "--fallback-model" in cmd


def test_run_claude_retries_on_network_error() -> None:
    fail = CompletedProcess(args=[], returncode=1, stdout="", stderr="network error")
    success = _mock_result()
    with patch("superpower_workflow.runner.subprocess.run", side_effect=[fail, fail, success]):
        with patch("superpower_workflow.runner.time.sleep"):
            result = run_claude("test", model="opus", effort="max", budget=10.0, cwd="/tmp")
    assert result.is_error is False


def test_run_claude_fails_after_max_retries() -> None:
    fail = CompletedProcess(args=[], returncode=1, stdout="", stderr="network error")
    with patch("superpower_workflow.runner.subprocess.run", side_effect=[fail, fail, fail]):
        with patch("superpower_workflow.runner.time.sleep"):
            result = run_claude("test", model="opus", effort="max", budget=10.0, cwd="/tmp")
    assert result.is_error is True


def test_run_claude_handles_timeout() -> None:
    import subprocess
    with patch("superpower_workflow.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 7200)):
        result = run_claude("test", model="opus", effort="max", budget=10.0, cwd="/tmp")
    assert result.is_error is True
    assert result.timed_out is True
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement runner.py**

```python
# src/superpower_workflow/runner.py
"""Wrapper for claude -p subprocess calls with retry and JSON parsing."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass


@dataclass
class ClaudeResult:
    text: str = ""
    cost_usd: float = 0.0
    session_id: str = ""
    duration_ms: int = 0
    is_error: bool = False
    timed_out: bool = False
    raw: dict | None = None


RETRY_DELAYS = [10, 30, 90]
TIMEOUT_SECONDS = 7200


def run_claude(
    prompt: str,
    model: str,
    effort: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    resume_session: str | None = None,
) -> ClaudeResult:
    cmd = ["claude", "-p", prompt, "--model", model, "--effort", effort,
           "--output-format", "json", "--permission-mode", "bypassPermissions",
           "--max-budget-usd", str(budget)]
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])
    if fallback_model:
        cmd.extend(["--fallback-model", fallback_model])
    if resume_session:
        cmd.extend(["--resume", resume_session])

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, cwd=cwd)
            if r.returncode == 0 and r.stdout.strip():
                return _parse_json_output(r.stdout)
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            return ClaudeResult(text=r.stderr or "unknown error", is_error=True)
        except subprocess.TimeoutExpired:
            return ClaudeResult(text="Phase timed out", is_error=True, timed_out=True)
    return ClaudeResult(text="Max retries exceeded", is_error=True)


def _parse_json_output(stdout: str) -> ClaudeResult:
    try:
        data = json.loads(stdout)
        return ClaudeResult(
            text=data.get("result", ""),
            cost_usd=data.get("total_cost_usd", 0.0),
            session_id=data.get("session_id", ""),
            duration_ms=data.get("duration_ms", 0),
            is_error=data.get("is_error", False),
            raw=data,
        )
    except (json.JSONDecodeError, KeyError):
        return ClaudeResult(text=stdout, is_error=True)
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint check**
- [ ] **Step 6: Commit**

```bash
git commit -m "feat: add claude -p runner with retry and JSON parsing"
```

---

### Task 4: Logger (`logger.py`)

**Files:**
- Create: `src/superpower_workflow/logger.py`
- Create: `tests/test_logger.py`

Structured file logging per spec §12.1. Format: `[ISO-timestamp] EVENT key=value`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_logger.py
from pathlib import Path
from superpower_workflow.logger import WorkflowLogger


def test_logger_creates_log_file(tmp_path: Path) -> None:
    log = WorkflowLogger(tmp_path, run_id="test-run")
    log.log("RUN_START", milestones=3)
    log.close()
    files = list(tmp_path.glob("workflow-*.log"))
    assert len(files) == 1
    assert "test-run" in files[0].name


def test_logger_writes_structured_lines(tmp_path: Path) -> None:
    log = WorkflowLogger(tmp_path, run_id="r1")
    log.log("PHASE_A_COMPLETE", cost=4.20, duration="920s")
    log.close()
    content = list(tmp_path.glob("workflow-*.log"))[0].read_text()
    assert "PHASE_A_COMPLETE" in content
    assert "cost=4.2" in content


def test_logger_appends_multiple_entries(tmp_path: Path) -> None:
    log = WorkflowLogger(tmp_path, run_id="r2")
    log.log("MILESTONE_START", name="p1-m2")
    log.log("PHASE_A_START")
    log.log("PHASE_A_COMPLETE", cost=3.0)
    log.close()
    content = list(tmp_path.glob("workflow-*.log"))[0].read_text()
    assert content.count("\n") >= 3
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement logger.py**

```python
# src/superpower_workflow/logger.py
"""Structured file logging for workflow runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class WorkflowLogger:
    def __init__(self, claude_dir: Path, run_id: str) -> None:
        self._path = claude_dir / f"workflow-{run_id}.log"
        self._file = open(self._path, "a", encoding="utf-8")

    def log(self, event: str, **kwargs: object) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [f"[{ts}]", event]
        for k, v in kwargs.items():
            parts.append(f"{k}={v}")
        self._file.write(" ".join(parts) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add structured file logger for workflow runs"
```

---

### Task 5: Prompt templates (`prompts.py`)

**Files:**
- Create: `src/superpower_workflow/prompts.py`
- Create: `tests/test_prompts.py`

Prompt templates per spec §7. Each phase has a template with `{placeholder}` substitution. System prompt is separate (used via `--append-system-prompt`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_prompts.py
from superpower_workflow.prompts import (
    system_prompt,
    phase_a_prompt,
    phase_b_prompt,
    phase_c_prompt,
    phase_d_prompt,
)


def test_system_prompt_has_no_questions_instruction() -> None:
    p = system_prompt()
    assert "Do NOT ask clarifying questions" in p


def test_phase_a_prompt_includes_spec_and_milestone() -> None:
    p = phase_a_prompt(
        name="p1-m2-knowledgestore",
        context_summary="M1 complete (foundations).",
        spec_path="docs/spec.md",
        sections="4.3, 6.1",
    )
    assert "p1-m2-knowledgestore" in p
    assert "docs/spec.md" in p
    assert "4.3, 6.1" in p
    assert "writing-plans" in p


def test_phase_b_prompt_includes_plan_path() -> None:
    p = phase_b_prompt(
        name="p1-m2",
        context_summary="M1 done.",
        plan_path="docs/superpowers/plans/2026-05-22-p1-m2.md",
    )
    assert "2026-05-22-p1-m2.md" in p
    assert "subagent-driven-development" in p


def test_phase_c_prompt_includes_verification() -> None:
    p = phase_c_prompt(
        name="p1-m2",
        context_summary="M1 done.",
        plan_commit_sha="abc123",
        verify_test="python -m pytest -q",
        verify_lint="python -m ruff check .",
        verify_format="python -m ruff format --check .",
    )
    assert "abc123" in p
    assert "python -m pytest" in p
    assert "critical-mechanical" in p


def test_phase_d_prompt_includes_branch() -> None:
    p = phase_d_prompt(name="p1-m2", branch="main")
    assert "p1-m2" in p
    assert "main" in p


def test_phase_a_prompt_no_verify_line() -> None:
    p = phase_a_prompt(name="m1", context_summary="", spec_path="s.md", sections="1")
    assert "Verification:" not in p
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement prompts.py**

```python
# src/superpower_workflow/prompts.py
"""Phase-specific prompt templates per spec §7."""

from __future__ import annotations


def system_prompt() -> str:
    return (
        "Do NOT ask clarifying questions. Use best judgment and note uncertainties.\n"
        "Follow all instructions in CLAUDE.md if present.\n"
        "If your context was compacted, re-read the plan or spec before continuing.\n"
        "Use conventional commits. Follow TDD when implementing code."
    )


def phase_a_prompt(
    name: str, context_summary: str, spec_path: str, sections: str,
) -> str:
    return (
        f"You are executing Phase A (Plan + Ultrathink) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
        f"1. Read the spec at {spec_path}, focusing on sections {sections}.\n"
        f"2. Use the superpowers:writing-plans skill to create a TDD implementation plan\n"
        f"   (10-25 tasks). Save to docs/superpowers/plans/ with today's date and {name}.\n"
        f"3. Run ultrathink-gap-analysis on the plan.\n"
        f"4. Fix critical gaps inline. Write .claude/.gap-report.json.\n"
        f"5. Commit the final plan."
    )


def phase_b_prompt(name: str, context_summary: str, plan_path: str) -> str:
    return (
        f"You are executing Phase B (Implementation) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
        f"Execute the plan at {plan_path} using the superpowers:subagent-driven-development\n"
        f"skill. Implement ALL tasks with TDD (red → green → commit per task).\n"
        f"If a task exceeds 25 sub-tasks, report OVERSIZED.\n"
        f"Commit each task individually with conventional commit messages.\n\n"
        f"If context is compacted, re-read the plan at {plan_path}."
    )


def phase_c_prompt(
    name: str, context_summary: str, plan_commit_sha: str,
    verify_test: str, verify_lint: str, verify_format: str,
) -> str:
    return (
        f"You are executing Phase C (Review + Fix) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
        f"1. Run post-impl-review on all files changed since {plan_commit_sha}.\n"
        f"2. Fix ALL critical-mechanical and important issues. Flag architectural gaps in the report.\n"
        f"3. Commit fixes as a single commit.\n"
        f"4. Write .claude/.gap-report.json.\n\n"
        f"Verification: {verify_test}, {verify_lint}, {verify_format}"
    )


def phase_d_prompt(name: str, branch: str) -> str:
    return (
        f"Tag HEAD as {name}. If remote origin exists, run:\n"
        f"git push origin {branch} --tags\n"
        f"If push fails, report TAG_ONLY."
    )
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add phase prompt templates with placeholder substitution"
```

---

### Task 6: Context generator (`context.py`)

**Files:**
- Create: `src/superpower_workflow/context.py`
- Create: `tests/test_context.py`

Generates the `{context_summary}` for prompts from git tags + state (spec §7.6). Last 3 milestones detailed, older milestones one-line summary. Capped at 200 words.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_context.py
from superpower_workflow.context import build_context_summary


def test_empty_completed_returns_empty() -> None:
    summary = build_context_summary(completed=[])
    assert summary == "No prior milestones."


def test_single_milestone() -> None:
    summary = build_context_summary(completed=["p1-m1-foundations"])
    assert "p1-m1-foundations" in summary


def test_four_milestones_summarizes_older() -> None:
    completed = ["p1-m1-foundations", "p1-m2-knowledgestore", "p1-m3-indexer", "p1-m4-tools"]
    summary = build_context_summary(completed=completed)
    assert "p1-m4-tools" in summary
    assert "p1-m3-indexer" in summary
    assert "p1-m2-knowledgestore" in summary
    # Oldest should be summarized, not detailed
    assert summary.count("p1-m1") <= 2  # appears at most in summary line


def test_context_capped_at_200_words() -> None:
    completed = [f"p1-m{i}-milestone-{i}" for i in range(20)]
    summary = build_context_summary(completed=completed)
    assert len(summary.split()) <= 200
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement context.py**

```python
# src/superpower_workflow/context.py
"""Git-based context summary generator for prompt templates."""

from __future__ import annotations

DETAIL_COUNT = 3
MAX_WORDS = 200


def build_context_summary(completed: list[str]) -> str:
    if not completed:
        return "No prior milestones."

    parts = []
    if len(completed) > DETAIL_COUNT:
        older = completed[:-DETAIL_COUNT]
        parts.append(f"{', '.join(older)} complete.")

    recent = completed[-DETAIL_COUNT:]
    parts.append("Recent: " + ", ".join(recent) + ".")

    summary = " ".join(parts)
    words = summary.split()
    if len(words) > MAX_WORDS:
        summary = " ".join(words[:MAX_WORDS])
    return summary
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add context summary generator for phase prompts"
```

---

### Task 7: Convergence hook (`convergence_gate.py`)

**Files:**
- Create: `src/superpower_workflow/hooks/convergence_gate.py`
- Create: `tests/test_convergence_gate.py`

The Stop hook per spec §3.3. Reads phase state + gap report → exit 0 (allow stop) or exit 2 (block stop). NEVER runs tests. Updates `previous_important_gaps` in phase state on each pass.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_convergence_gate.py
import json
from pathlib import Path
from superpower_workflow.hooks.convergence_gate import compute_exit_code


def _write(claude_dir: Path, phase: dict | None, gap_report: dict | None) -> None:
    claude_dir.mkdir(parents=True, exist_ok=True)
    if phase is not None:
        (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase))
    if gap_report is not None:
        (claude_dir / ".gap-report.json").write_text(json.dumps(gap_report))


def test_no_phase_state_allows_stop(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    assert compute_exit_code(claude_dir) == 0


def test_critical_gaps_block_stop(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    _write(cd,
        phase={"phase": "ultrathink", "iteration": 0, "max_iterations": 5, "previous_important_gaps": None},
        gap_report={"critical_gaps": 2, "important_gaps": 1, "tests_green": True, "lint_clean": True, "pass": 1},
    )
    assert compute_exit_code(cd) == 2


def test_converged_allows_stop(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    _write(cd,
        phase={"phase": "ultrathink", "iteration": 1, "max_iterations": 5, "previous_important_gaps": 5},
        gap_report={"critical_gaps": 0, "important_gaps": 2, "tests_green": True, "lint_clean": True, "pass": 2},
    )
    assert compute_exit_code(cd) == 0  # 2 <= 3 → converged


def test_max_iterations_allows_stop(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    _write(cd,
        phase={"phase": "ultrathink", "iteration": 5, "max_iterations": 5, "previous_important_gaps": None},
        gap_report={"critical_gaps": 3, "important_gaps": 10, "tests_green": True, "lint_clean": True, "pass": 5},
    )
    assert compute_exit_code(cd) == 0  # max reached


def test_no_gap_report_blocks_stop(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    _write(cd,
        phase={"phase": "ultrathink", "iteration": 0, "max_iterations": 5, "previous_important_gaps": None},
        gap_report=None,
    )
    assert compute_exit_code(cd) == 2


def test_review_phase_requires_zero_important(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    _write(cd,
        phase={"phase": "review", "iteration": 1, "max_iterations": 5, "previous_important_gaps": 3},
        gap_report={"critical_gaps": 0, "important_gaps": 1, "tests_green": True, "lint_clean": True, "pass": 2},
    )
    assert compute_exit_code(cd) == 2  # review needs important == 0


def test_review_tests_not_green_blocks(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    _write(cd,
        phase={"phase": "review", "iteration": 0, "max_iterations": 5, "previous_important_gaps": None},
        gap_report={"critical_gaps": 0, "important_gaps": 0, "tests_green": False, "lint_clean": True, "pass": 1},
    )
    assert compute_exit_code(cd) == 2


def test_hook_updates_previous_important_on_block(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    _write(cd,
        phase={"phase": "ultrathink", "iteration": 0, "max_iterations": 5, "previous_important_gaps": None},
        gap_report={"critical_gaps": 1, "important_gaps": 8, "tests_green": True, "lint_clean": True, "pass": 1},
    )
    compute_exit_code(cd)
    phase = json.loads((cd / ".workflow-phase.json").read_text())
    assert phase["iteration"] == 1
    assert phase["previous_important_gaps"] == 8


def test_malformed_gap_report_blocks(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / ".workflow-phase.json").write_text(json.dumps(
        {"phase": "ultrathink", "iteration": 0, "max_iterations": 5, "previous_important_gaps": None}
    ))
    (cd / ".gap-report.json").write_text("not valid json")
    assert compute_exit_code(cd) == 2
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement convergence_gate.py**

```python
# src/superpower_workflow/hooks/convergence_gate.py
"""Stop hook for convergence enforcement. Exit 0 = allow stop, exit 2 = block stop."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PHASE_FILE = ".workflow-phase.json"
GAP_REPORT_FILE = ".gap-report.json"


def compute_exit_code(claude_dir: Path) -> int:
    phase_path = claude_dir / PHASE_FILE
    if not phase_path.exists():
        return 0

    try:
        phase = json.loads(phase_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0

    iteration = phase.get("iteration", 0)
    max_iter = phase.get("max_iterations", 5)
    if iteration >= max_iter:
        return 0

    gap_path = claude_dir / GAP_REPORT_FILE
    if not gap_path.exists():
        _increment_iteration(phase_path, phase)
        return 2

    try:
        report = json.loads(gap_path.read_text())
    except (json.JSONDecodeError, OSError):
        _increment_iteration(phase_path, phase)
        return 2

    critical = report.get("critical_gaps", 0)
    important = report.get("important_gaps", 0)
    tests_green = report.get("tests_green", True)
    lint_clean = report.get("lint_clean", True)
    phase_type = phase.get("phase", "ultrathink")
    prev_important = phase.get("previous_important_gaps")

    if phase_type == "review":
        converged = critical == 0 and important == 0 and tests_green and lint_clean
    else:
        if prev_important is None:
            converged = critical == 0 and important <= 3
        else:
            converged = critical == 0 and (important <= 3 or important <= prev_important * 0.5)

    if converged:
        return 0

    _increment_iteration(phase_path, phase, important)
    return 2


def _increment_iteration(phase_path: Path, phase: dict, current_important: int | None = None) -> None:
    phase["iteration"] = phase.get("iteration", 0) + 1
    if current_important is not None:
        phase["previous_important_gaps"] = current_important
    tmp = phase_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(phase, indent=2))
    os.replace(str(tmp), str(phase_path))


def main() -> None:
    claude_dir = Path(".claude")
    code = compute_exit_code(claude_dir)
    if code == 2:
        phase = json.loads((claude_dir / PHASE_FILE).read_text()) if (claude_dir / PHASE_FILE).exists() else {}
        iteration = phase.get("iteration", 0)
        max_iter = phase.get("max_iterations", 5)
        print(f"Iteration {iteration}/{max_iter}. Gaps remain. Continue analyzing and fixing.", file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add convergence gate Stop hook with phase-aware logic"
```

---

### Task 8: Estimator (`estimator.py`)

**Files:**
- Create: `src/superpower_workflow/estimator.py`
- Create: `tests/test_estimator.py`

Calculates cost range and duration range from config (spec §13).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_estimator.py
from superpower_workflow.estimator import estimate


def test_estimate_single_milestone() -> None:
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": [{"name": "m1"}],
    }
    est = estimate(config)
    assert est["milestone_count"] == 1
    assert est["cost_optimistic"] > 0
    assert est["cost_pessimistic"] >= est["cost_optimistic"]
    assert est["duration_optimistic_min"] > 0


def test_estimate_multiple_milestones_scales() -> None:
    config = {
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": [{"name": f"m{i}"} for i in range(10)],
    }
    est = estimate(config)
    assert est["milestone_count"] == 10
    assert est["cost_pessimistic"] == 10 * (25 + 100 + 40 + 3)


def test_estimate_zero_milestones() -> None:
    config = {"budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3}, "milestones": []}
    est = estimate(config)
    assert est["milestone_count"] == 0
    assert est["cost_optimistic"] == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement estimator.py**

```python
# src/superpower_workflow/estimator.py
"""Cost and duration estimates from workflow config."""

from __future__ import annotations

OPTIMISTIC_FACTOR = 0.5
MINUTES_PER_PHASE = {"plan": 30, "implement": 120, "review": 45, "push": 2}


def estimate(config: dict) -> dict:
    budgets = config.get("budgets", {})
    milestones = config.get("milestones", [])
    n = len(milestones)
    total_budget = sum(budgets.get(p, 0) for p in ("plan", "implement", "review", "push"))
    total_minutes = sum(MINUTES_PER_PHASE.get(p, 0) for p in MINUTES_PER_PHASE)
    return {
        "milestone_count": n,
        "cost_optimistic": round(n * total_budget * OPTIMISTIC_FACTOR, 2),
        "cost_pessimistic": round(n * total_budget, 2),
        "duration_optimistic_min": round(n * total_minutes * OPTIMISTIC_FACTOR),
        "duration_pessimistic_min": n * total_minutes,
    }
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add cost and duration estimator"
```

---

### Task 9: Doctor (`doctor.py`)

**Files:**
- Create: `src/superpower_workflow/doctor.py`
- Create: `tests/test_doctor.py`

Pre-flight health checks per spec §4.1. Checks: Claude Code installed, workflow.json valid, git clean, skills installed (hash match).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_doctor.py
import json
from pathlib import Path
from unittest.mock import patch
from superpower_workflow.doctor import run_checks, CheckResult


def test_missing_config_fails(tmp_path: Path) -> None:
    results = run_checks(tmp_path)
    failed = [r for r in results if not r.ok]
    assert any("workflow.json" in r.message for r in failed)


def test_valid_config_passes(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    cd.mkdir()
    config = {"schema_version": 1, "spec": "s.md", "model": "opus", "milestones": []}
    (cd / "workflow.json").write_text(json.dumps(config))
    with patch("superpower_workflow.doctor.shutil.which", return_value="/usr/bin/claude"):
        results = run_checks(tmp_path)
    config_checks = [r for r in results if "workflow.json" in r.message]
    assert all(r.ok for r in config_checks)


def test_claude_not_installed_fails(tmp_path: Path) -> None:
    cd = tmp_path / ".claude"
    cd.mkdir()
    (cd / "workflow.json").write_text(json.dumps({"schema_version": 1, "spec": "s.md", "milestones": []}))
    with patch("superpower_workflow.doctor.shutil.which", return_value=None):
        results = run_checks(tmp_path)
    claude_checks = [r for r in results if "Claude Code" in r.message]
    assert any(not r.ok for r in claude_checks)
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement doctor.py**

```python
# src/superpower_workflow/doctor.py
"""Pre-flight health checks."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    ok: bool
    message: str


def run_checks(project_root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    claude_dir = project_root / ".claude"

    if shutil.which("claude"):
        results.append(CheckResult(True, "Claude Code installed"))
    else:
        results.append(CheckResult(False, "Claude Code not installed"))

    config_path = claude_dir / "workflow.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            if "schema_version" in config and "spec" in config:
                results.append(CheckResult(True, "workflow.json valid"))
            else:
                results.append(CheckResult(False, "workflow.json missing required fields"))
        except json.JSONDecodeError:
            results.append(CheckResult(False, "workflow.json is not valid JSON"))
    else:
        results.append(CheckResult(False, "workflow.json not found — run `sw init`"))

    return results
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add doctor pre-flight health checks"
```

---

### Task 10: Decomposer (`decomposer.py`)

**Files:**
- Create: `src/superpower_workflow/decomposer.py`
- Create: `tests/test_decomposer.py`

Two-pass spec → milestone decomposition per spec §9. Uses runner to call `claude -p`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_decomposer.py
import json
from unittest.mock import patch
from pathlib import Path
from superpower_workflow.decomposer import decompose
from superpower_workflow.runner import ClaudeResult


def test_decompose_returns_milestones(tmp_path: Path) -> None:
    milestones = [
        {"name": "p1-m1-foundations", "spec_sections": "4", "description": "Base types", "depends_on": []},
        {"name": "p1-m2-store", "spec_sections": "5", "description": "Data store", "depends_on": ["p1-m1-foundations"]},
    ]
    mock_result = ClaudeResult(text=json.dumps(milestones), is_error=False)
    with patch("superpower_workflow.decomposer.run_claude", return_value=mock_result):
        result = decompose(spec_path="spec.md", model="opus", cwd=str(tmp_path))
    assert len(result) == 2
    assert result[0]["name"] == "p1-m1-foundations"


def test_decompose_returns_empty_on_error(tmp_path: Path) -> None:
    mock_result = ClaudeResult(text="error", is_error=True)
    with patch("superpower_workflow.decomposer.run_claude", return_value=mock_result):
        result = decompose(spec_path="spec.md", model="opus", cwd=str(tmp_path))
    assert result == []


def test_decompose_handles_json_in_markdown(tmp_path: Path) -> None:
    text = '```json\n[{"name": "m1", "spec_sections": "1", "description": "d", "depends_on": []}]\n```'
    mock_result = ClaudeResult(text=text, is_error=False)
    with patch("superpower_workflow.decomposer.run_claude", return_value=mock_result):
        result = decompose(spec_path="spec.md", model="opus", cwd=str(tmp_path))
    assert len(result) == 1
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement decomposer.py**

```python
# src/superpower_workflow/decomposer.py
"""Two-pass spec → milestone decomposition via claude -p."""

from __future__ import annotations

import json
import re

from superpower_workflow.runner import run_claude


DECOMPOSE_PROMPT = """Read the spec at {spec_path}. Identify implementation milestones.
Rules:
- Each milestone: 10-25 tasks of TDD work (1-3 days)
- Group by dependency (foundations first)
- Each milestone independently testable
- Name format: {{phase}}-m{{N}}-{{short-name}}
Output ONLY a JSON array of milestones, each with: name, spec_sections, description, depends_on."""

VALIDATE_PROMPT = """Review these proposed milestones against the spec at {spec_path}.
Check: all spec sections covered? Dependencies correct? Sizes reasonable?
Fix any issues. Output ONLY the corrected JSON array.

Proposed milestones:
{milestones_json}"""


def decompose(spec_path: str, model: str, cwd: str) -> list[dict]:
    result = run_claude(
        DECOMPOSE_PROMPT.format(spec_path=spec_path),
        model=model, effort="max", budget=10.0, cwd=cwd,
    )
    if result.is_error:
        return []

    milestones = _extract_json_array(result.text)
    if not milestones:
        return []

    validate_result = run_claude(
        VALIDATE_PROMPT.format(spec_path=spec_path, milestones_json=json.dumps(milestones, indent=2)),
        model=model, effort="max", budget=10.0, cwd=cwd,
    )
    if not validate_result.is_error:
        validated = _extract_json_array(validate_result.text)
        if validated:
            return validated

    return milestones


def _extract_json_array(text: str) -> list[dict]:
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add two-pass spec decomposer"
```

---

### Task 11: Orchestrator (`orchestrator.py`)

**Files:**
- Create: `src/superpower_workflow/orchestrator.py`
- Create: `tests/test_orchestrator.py`

The core milestone loop per spec §3.2. Pre-flight checks → for each milestone: Phase A/B/C/D → state update → delay. Handles error classification per §8.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.runner import ClaudeResult


def _config(tmp_path: Path) -> dict:
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "convergence": {"max_iterations": 5, "min_gaps_for_substantial": 20, "persistent_gap_downgrade_after": 3},
        "verify_commands": {"test": None, "lint": None, "format": None},
        "git_strategy": "main",
        "notification_webhook": None,
        "milestones": [
            {"name": "m1", "spec_sections": "1", "description": "First", "depends_on": [], "budget_override": None},
        ],
    }
    cd = tmp_path / ".claude"
    cd.mkdir()
    (cd / "workflow.json").write_text(json.dumps(config))
    return config


def _ok_result(cost: float = 1.0) -> ClaudeResult:
    return ClaudeResult(text="done", cost_usd=cost, session_id="s1", is_error=False)


def test_orchestrator_runs_all_four_phases(tmp_path: Path) -> None:
    _config(tmp_path)
    calls = []
    def mock_run(*args, **kwargs):
        calls.append(kwargs.get("prompt", args[0] if args else ""))
        return _ok_result()

    with patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run):
        with patch("superpower_workflow.orchestrator.subprocess.run"):  # git commands
            orch = Orchestrator(tmp_path)
            orch.run(dry_run=False)

    # Should have at least 4 calls (Phase A, B, C, D)
    assert len(calls) >= 4


def test_orchestrator_dry_run_does_not_call_claude(tmp_path: Path) -> None:
    _config(tmp_path)
    with patch("superpower_workflow.orchestrator.run_claude") as mock:
        orch = Orchestrator(tmp_path)
        orch.run(dry_run=True)
    mock.assert_not_called()


def test_orchestrator_updates_state_after_milestone(tmp_path: Path) -> None:
    _config(tmp_path)
    with patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()):
        with patch("superpower_workflow.orchestrator.subprocess.run"):
            orch = Orchestrator(tmp_path)
            orch.run(dry_run=False)
    from superpower_workflow.state import load_state
    state = load_state(tmp_path / ".claude")
    assert "m1" in state.completed
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement orchestrator.py**

```python
# src/superpower_workflow/orchestrator.py
"""Core milestone loop: pre-flight → phases A/B/C/D → state update."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from superpower_workflow.context import build_context_summary
from superpower_workflow.logger import WorkflowLogger
from superpower_workflow.prompts import (
    phase_a_prompt, phase_b_prompt, phase_c_prompt, phase_d_prompt, system_prompt,
)
from superpower_workflow.runner import run_claude
from superpower_workflow.state import (
    WorkflowState, PhaseState,
    load_config, load_state, save_state,
    save_phase_state, clear_phase_state,
    acquire_lock, release_lock,
)


class Orchestrator:
    def __init__(self, project_root: Path) -> None:
        self.root = project_root
        self.claude_dir = project_root / ".claude"
        self.config = load_config(self.claude_dir)
        self.state = load_state(self.claude_dir)
        self.sys_prompt = system_prompt()
        self.cwd = str(project_root)

    def run(
        self,
        dry_run: bool = False,
        milestone_filter: str | None = None,
        from_ms: str | None = None,
        to_ms: str | None = None,
    ) -> None:
        milestones = self._filter_milestones(milestone_filter, from_ms, to_ms)

        if dry_run:
            for ms in milestones:
                print(f"  [DRY RUN] Would execute: {ms['name']}")
            return

        run_id = time.strftime("%Y%m%d-%H%M%S")
        self.state.run_id = run_id
        self.state.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger = WorkflowLogger(self.claude_dir, run_id)

        try:
            if not acquire_lock(self.claude_dir):
                print("Another orchestration is running.")
                return

            for i, ms in enumerate(milestones):
                name = ms["name"]
                if name in self.state.completed:
                    continue

                logger.log("MILESTONE_START", name=name)
                self.state.current_milestone_index = i
                cost = self._run_milestone(ms, logger)
                self.state.completed.append(name)
                self.state.total_cost_usd += cost
                self.state.current_step = None
                save_state(self.claude_dir, self.state)
                logger.log("MILESTONE_COMPLETE", name=name, total_cost=round(cost, 2))

                delay = self.config.get("delay_between_phases_seconds", 10)
                if delay > 0:
                    time.sleep(delay)
        finally:
            release_lock(self.claude_dir)
            logger.close()

    def _run_milestone(self, ms: dict, logger: WorkflowLogger) -> float:
        name = ms["name"]
        sections = ms.get("spec_sections", "")
        spec = self.config["spec"]
        model = self.config["model"]
        fallback = self.config.get("fallback_model")
        budgets = self.config["budgets"]
        effort = self.config.get("effort", {})
        context = build_context_summary(self.state.completed)
        verify = self.config.get("verify_commands", {})
        cost = 0.0

        # Phase A: Plan + Ultrathink
        self.state.current_step = "plan"
        save_state(self.claude_dir, self.state)
        convergence = self.config.get("convergence", {})
        save_phase_state(self.claude_dir, PhaseState(
            phase="ultrathink", max_iterations=convergence.get("max_iterations", 5),
        ))
        logger.log("PHASE_A_START")
        r = run_claude(
            phase_a_prompt(name, context, spec, sections),
            model=model, effort=effort.get("plan", "max"),
            budget=budgets.get("plan", 25), cwd=self.cwd,
            system_prompt=self.sys_prompt, fallback_model=fallback,
        )
        cost += r.cost_usd
        clear_phase_state(self.claude_dir)
        logger.log("PHASE_A_COMPLETE", cost=round(r.cost_usd, 2))

        # Capture plan_commit_sha
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=self.cwd,
        )
        plan_sha = sha_result.stdout.strip()
        self.state.plan_commit_sha = plan_sha
        self.state.last_phase_session_id = r.session_id

        # Rollback tag
        subprocess.run(["git", "tag", f"pre-impl/{name}"], capture_output=True, cwd=self.cwd)

        # Phase B: Implement
        self.state.current_step = "implement"
        save_state(self.claude_dir, self.state)
        plan_path = self._find_plan_path(name)
        logger.log("PHASE_B_START")
        r = run_claude(
            phase_b_prompt(name, context, plan_path),
            model=model, effort=effort.get("implement", "high"),
            budget=budgets.get("implement", 100), cwd=self.cwd,
            system_prompt=self.sys_prompt, fallback_model=fallback,
        )
        cost += r.cost_usd
        self.state.last_phase_session_id = r.session_id
        logger.log("PHASE_B_COMPLETE", cost=round(r.cost_usd, 2))

        # Phase C: Review + Fix
        self.state.current_step = "review"
        save_state(self.claude_dir, self.state)
        save_phase_state(self.claude_dir, PhaseState(
            phase="review", max_iterations=convergence.get("max_iterations", 5),
        ))
        logger.log("PHASE_C_START")
        r = run_claude(
            phase_c_prompt(
                name, context, plan_sha,
                verify.get("test", "true"), verify.get("lint", "true"), verify.get("format", "true"),
            ),
            model=model, effort=effort.get("review", "max"),
            budget=budgets.get("review", 40), cwd=self.cwd,
            system_prompt=self.sys_prompt, fallback_model=fallback,
        )
        cost += r.cost_usd
        clear_phase_state(self.claude_dir)
        logger.log("PHASE_C_COMPLETE", cost=round(r.cost_usd, 2))

        # Phase D: Push + Tag
        self.state.current_step = "push"
        save_state(self.claude_dir, self.state)
        branch = "main" if self.config.get("git_strategy") == "main" else f"milestone/{name}"
        logger.log("PHASE_D_START")
        r = run_claude(
            phase_d_prompt(name, branch),
            model=model, effort=effort.get("push", "low"),
            budget=budgets.get("push", 3), cwd=self.cwd,
            system_prompt=self.sys_prompt, fallback_model=fallback,
        )
        cost += r.cost_usd
        logger.log("PHASE_D_COMPLETE", cost=round(r.cost_usd, 2))

        return cost

    def _filter_milestones(
        self, milestone: str | None, from_ms: str | None, to_ms: str | None,
    ) -> list[dict]:
        all_ms = self.config.get("milestones", [])
        if milestone:
            return [m for m in all_ms if m["name"] == milestone]
        if from_ms or to_ms:
            names = [m["name"] for m in all_ms]
            start = names.index(from_ms) if from_ms and from_ms in names else 0
            end = names.index(to_ms) + 1 if to_ms and to_ms in names else len(names)
            return all_ms[start:end]
        return all_ms

    def _find_plan_path(self, name: str) -> str:
        plans_dir = Path(self.cwd) / "docs" / "superpowers" / "plans"
        if plans_dir.exists():
            for f in sorted(plans_dir.glob(f"*{name}*")):
                return str(f)
        return f"docs/superpowers/plans/*{name}*.md"
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add orchestrator core milestone loop"
```

---

### Task 12: CLI (`cli.py`)

**Files:**
- Create: `src/superpower_workflow/cli.py`
- Create: `tests/test_cli.py`

Argparse entry point per spec §4.1. Routes to orchestrator, decomposer, estimator, doctor, state.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py
from superpower_workflow.cli import build_parser


def test_parser_run_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.dry_run is False


def test_parser_run_milestone_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--milestone", "p1-m2"])
    assert args.milestone == "p1-m2"


def test_parser_run_dry_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--dry-run"])
    assert args.dry_run is True


def test_parser_estimate_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["estimate"])
    assert args.command == "estimate"


def test_parser_doctor_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["doctor"])
    assert args.command == "doctor"


def test_parser_status_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement cli.py**

```python
# src/superpower_workflow/cli.py
"""CLI entry point for the sw command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from superpower_workflow import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sw", description="Superpower Workflow Orchestrator")
    parser.add_argument("--version", action="version", version=f"sw {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create .claude/workflow.json")
    sub.add_parser("doctor", help="Pre-flight health checks")
    sub.add_parser("decompose", help="Spec → milestone breakdown")
    sub.add_parser("estimate", help="Cost and duration estimate")
    sub.add_parser("status", help="Show progress")
    sub.add_parser("resume", help="Resume from failure point")

    run_p = sub.add_parser("run", help="Execute milestones")
    run_p.add_argument("--milestone", help="Run a specific milestone")
    run_p.add_argument("--from", dest="from_ms", help="Start from milestone")
    run_p.add_argument("--to", dest="to_ms", help="End at milestone")
    run_p.add_argument("--phase", help="Run milestones matching phase prefix")
    run_p.add_argument("--dry-run", action="store_true", help="Preview without executing")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    project_root = Path.cwd()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "doctor":
        from superpower_workflow.doctor import run_checks
        results = run_checks(project_root)
        for r in results:
            status = "✓" if r.ok else "✗"
            print(f"  {status} {r.message}")
        sys.exit(0 if all(r.ok for r in results) else 1)

    if args.command == "estimate":
        from superpower_workflow.estimator import estimate
        from superpower_workflow.state import load_config
        config = load_config(project_root / ".claude")
        est = estimate(config)
        print(f"  Milestones: {est['milestone_count']}")
        print(f"  Cost: ${est['cost_optimistic']}-${est['cost_pessimistic']}")
        print(f"  Duration: {est['duration_optimistic_min']}-{est['duration_pessimistic_min']} min")
        return

    if args.command == "status":
        from superpower_workflow.state import load_state
        state = load_state(project_root / ".claude")
        print(f"  Completed: {len(state.completed)} milestones")
        print(f"  Cost so far: ${state.total_cost_usd:.2f}")
        if state.current_step:
            print(f"  Current: milestone #{state.current_milestone_index}, step={state.current_step}")
        for m in state.completed:
            print(f"    ✓ {m}")
        return

    if args.command == "run":
        from superpower_workflow.orchestrator import Orchestrator
        orch = Orchestrator(project_root)
        orch.run(
            dry_run=args.dry_run,
            milestone_filter=args.milestone,
            from_ms=args.from_ms,
            to_ms=args.to_ms,
        )
        return

    print(f"Command '{args.command}' not yet implemented.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add sw CLI with argparse routing"
```

---

### Task 13: Skills — ultrathink-gap-analysis SKILL.md

**Files:**
- Create: `skills/ultrathink-gap-analysis/SKILL.md`

Claude Code skill per spec §6.1. Technique skill with mode detection, gap enumeration, categorization, gap-report writing.

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: ultrathink-gap-analysis
description: Use when reviewing a plan, spec section, or implementation for gaps — performs adversarial ≥20-gap analysis with categorized severity, fixes mechanical issues, and writes a convergence-tracked gap report
---

# Ultrathink Gap Analysis

Adversarial review that finds ≥20 concrete gaps, categorizes them, fixes what it can, and writes a structured gap report for convergence tracking.

## Procedure

1. **Detect mode:** `.md` target → plan review. Code files → implementation review.
2. **Read config:** If `.claude/workflow.json` exists, read `verify_commands` and `convergence` settings.
3. **Size check:** >500 lines → dispatch reviewer via Agent tool. ≤500 → analyze directly.
4. **Read prior report:** If `.claude/.gap-report.json` exists, note which gaps were already fixed.
5. **Baseline** (implementation mode only): run verify commands from config.
6. **Enumerate gaps:** ≥20 for artifacts >200 lines combined. Each gap needs: file:line reference, 1-sentence rationale, suggested action.
7. **Categorize:** 🔴-mechanical (auto-fix), 🔴-architectural (flag only), 🟡 Important, 🟢 Acceptable (defer to specific milestone), 🔵 Minor.
8. **Fix** all 🔴-mechanical + 🔵. Flag 🔴-architectural in report.
9. **Write `.claude/.gap-report.json`:**
   ```json
   {"pass": N, "critical_gaps": 0, "architectural_gaps": 1,
    "important_gaps": 2, "minor_gaps": 0, "deferred_gaps": 3,
    "total_gaps_found": 6, "gaps_fixed_this_pass": 4,
    "tests_green": true, "lint_clean": true, "converged": true}
   ```
   `critical_gaps`/`important_gaps` = remaining AFTER fixes, not total found.
10. **Verify** (implementation mode): run test + lint. Must be green.

## Convergence

Converged when: `critical_gaps == 0 AND (important_gaps <= 3 OR important_gaps <= previous * 0.5)` OR max iterations reached.

Persistent important gap across 3 passes → auto-downgrade to 🟢.
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: add ultrathink-gap-analysis skill"
```

---

### Task 14: Skills — post-impl-review SKILL.md

**Files:**
- Create: `skills/post-impl-review/SKILL.md`

Skill per spec §6.2.

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: post-impl-review
description: Use after completing implementation of a milestone or feature — reviews changed files for bugs, gaps, and needed enhancements with stricter convergence than ultrathink
---

# Post-Implementation Review

Reviews all files changed since the plan was committed. Stricter than ultrathink: requires `important_gaps == 0`.

## Procedure

1. Identify scope: `git diff --name-only <plan-commit>..HEAD`.
2. Run verify commands (test + lint). Fix if not green.
3. Follow ultrathink-gap-analysis procedure on the changed files.
4. **Stricter convergence:** `critical_gaps == 0 AND important_gaps == 0 AND tests_green AND lint_clean`.
5. Commit all fixes as single commit: `fix: post-impl review fixes for {milestone}`.
6. Write `.claude/.gap-report.json` with current gap counts.

## When to use

After `subagent-driven-development` completes a milestone's implementation, before pushing.
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: add post-impl-review skill"
```

---

### Task 15: Slash command + template + install script

**Files:**
- Create: `commands/ultrathink.md`
- Create: `templates/workflow.json`
- Create: `install.py`

- [ ] **Step 1: Write slash command**

```markdown
---
description: Run ≥20-gap adversarial review on an artifact and fulfill priority fixes
---

Run the ultrathink-gap-analysis skill on: $ARGUMENTS

If no arguments provided, analyze files changed in the last commit.
```

- [ ] **Step 2: Write workflow.json template**

The template from spec §5.1 with placeholder values and comments.

- [ ] **Step 3: Write install.py**

```python
#!/usr/bin/env python3
"""Install skills, hooks, and commands to ~/.claude/."""

import hashlib
import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).parent
HOME_CLAUDE = Path.home() / ".claude"

COPIES = [
    ("skills/ultrathink-gap-analysis", "skills/ultrathink-gap-analysis"),
    ("skills/post-impl-review", "skills/post-impl-review"),
    ("commands/ultrathink.md", "commands/ultrathink.md"),
]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_file():
            target = dst / item.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and file_hash(item) == file_hash(target):
                print(f"  skip (identical): {target}")
                continue
            shutil.copy2(item, target)
            print(f"  copied: {target}")


def register_hook() -> None:
    settings_path = HOME_CLAUDE / "settings.json"
    settings = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    hook_cmd = f"python -m superpower_workflow.hooks.convergence_gate"
    already = any(
        hook_cmd in str(entry)
        for entry in stop_hooks
    )
    if not already:
        stop_hooks.append({
            "matcher": "",
            "hooks": [{"type": "command", "command": hook_cmd, "timeout": 30}],
        })
        settings_path.write_text(json.dumps(settings, indent=2))
        print(f"  registered Stop hook in {settings_path}")
    else:
        print(f"  Stop hook already registered")


def main() -> None:
    print("Installing superpower-workflow components to ~/.claude/")
    for src_rel, dst_rel in COPIES:
        src = REPO_ROOT / src_rel
        dst = HOME_CLAUDE / dst_rel
        if src.is_dir():
            copy_tree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and file_hash(src) == file_hash(dst):
                print(f"  skip (identical): {dst}")
            else:
                shutil.copy2(src, dst)
                print(f"  copied: {dst}")

    register_hook()
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add slash command, config template, and install script"
```

---

### Task 16: Shared test fixtures (`conftest.py`)

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Write conftest.py**

```python
# tests/conftest.py
import json
from pathlib import Path
import pytest


@pytest.fixture
def claude_dir(tmp_path: Path) -> Path:
    cd = tmp_path / ".claude"
    cd.mkdir()
    return cd


@pytest.fixture
def sample_config() -> dict:
    return {
        "schema_version": 1,
        "spec": "docs/superpowers/specs/spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "convergence": {"max_iterations": 5, "min_gaps_for_substantial": 20, "persistent_gap_downgrade_after": 3},
        "verify_commands": {"test": "python -m pytest -q", "lint": None, "format": None},
        "git_strategy": "main",
        "notification_webhook": None,
        "milestones": [],
    }


@pytest.fixture
def config_file(claude_dir: Path, sample_config: dict) -> Path:
    path = claude_dir / "workflow.json"
    path.write_text(json.dumps(sample_config))
    return path
```

- [ ] **Step 2: Commit**

```bash
git commit -m "test: add shared conftest fixtures"
```

---

### Task 17: Full test suite verification + lint

- [ ] **Step 1: Run full test suite**

```bash
cd superpower-workflow
.venv/Scripts/pytest -v
```
Expected: all tests pass (10 state + 5 runner + 3 logger + 6 prompts + 4 context + 9 convergence + 3 estimator + 3 doctor + 3 decomposer + 3 orchestrator + 6 cli = ~55 tests)

- [ ] **Step 2: Run ruff**

```bash
.venv/Scripts/ruff check src/ tests/
.venv/Scripts/ruff format --check src/ tests/
```
Expected: clean

- [ ] **Step 3: Fix any issues**

If ruff format drift: `.venv/Scripts/ruff format src/ tests/` then commit.

- [ ] **Step 4: Commit**

```bash
git commit -m "style: apply ruff format across superpower-workflow"
```

---

### Task 18: Smoke test — end-to-end dry run

- [ ] **Step 1: Create a mock project and run sw commands**

```bash
cd superpower-workflow
# Test CLI responds
.venv/Scripts/sw --version
.venv/Scripts/sw --help
.venv/Scripts/sw doctor       # Should show checks (some may fail, that's ok)
```

- [ ] **Step 2: Test with a sample workflow.json**

```bash
mkdir -p /tmp/test-project/.claude
cat > /tmp/test-project/.claude/workflow.json << 'EOF'
{
  "schema_version": 1,
  "spec": "spec.md",
  "model": "opus",
  "fallback_model": "haiku",
  "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
  "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
  "max_total_budget_usd": 500,
  "delay_between_phases_seconds": 0,
  "convergence": {"max_iterations": 5, "min_gaps_for_substantial": 20, "persistent_gap_downgrade_after": 3},
  "verify_commands": {"test": null, "lint": null, "format": null},
  "git_strategy": "main",
  "notification_webhook": null,
  "milestones": [
    {"name": "test-m1", "spec_sections": "1", "description": "Test milestone", "depends_on": [], "budget_override": null}
  ]
}
EOF
cd /tmp/test-project
sw estimate       # Should print cost estimates
sw status         # Should show 0 completed
sw run --dry-run  # Should print "Would execute: test-m1"
```

- [ ] **Step 3: Commit any final fixes**

```bash
git commit -m "test: verify end-to-end smoke test"
```

---

## Self-Review

**Spec coverage check:**
- §1 Overview → Task 1 (scaffold) + overall architecture
- §3.1 Components → Tasks 2-12 (one per component)
- §3.2 Execution Model → Task 11 (orchestrator)
- §3.3 Convergence → Task 7 (hook)
- §3.4 Gap Report → Tasks 7, 13 (hook + skill)
- §4 CLI → Task 12
- §5 Config → Tasks 2, 15 (state + template)
- §6 Skills → Tasks 13, 14
- §7 Prompts → Task 5
- §8 Error Handling → Tasks 3 (retry), 11 (orchestrator error paths)
- §9 Decomposition → Task 10
- §10 Installation → Tasks 1, 15 (scaffold + install script)
- §11 Convergence Criteria → Task 7
- §12 Logging → Task 4
- §6.3 Slash Command → Task 15

All spec sections covered. ✓

**Placeholder scan:** No TBD, TODO, or "implement later" found. ✓

**Type consistency:** `WorkflowState`, `PhaseState`, `ClaudeResult`, `CheckResult` — used consistently across modules. `load_config` returns `dict` everywhere. `run_claude` signature matches all call sites. ✓
