# SP1: Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add code-enforced quality verification (lint, SAST, coverage, dep scan, loop detection, git trailers) with orchestrator checkpoints after Phase B and Phase C.

**Architecture:** Hybrid — skills instruct Claude, orchestrator independently verifies using real tools. New `_verify_quality_gates` and `_check_coverage` methods on Orchestrator. Loop detection added to convergence hook. Quality gate config is optional (backward compatible).

**Tech Stack:** Python 3.11+, subprocess (runs project tools), json (coverage parsing), re (fuzzy match), pytest, ruff.

**Spec reference:** `docs/superpowers/specs/2026-05-24-sp1-quality-gates.md` (v1.0).

**Working directory:** `superpower-workflow/` (the repo root).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/state.py` | Edit | Add `previous_gap_summaries` to PhaseState |
| `src/superpower_workflow/hooks/convergence_gate.py` | Edit | Add loop detection (`_is_stuck`) |
| `src/superpower_workflow/prompts.py` | Edit | Add quality gate + trailer instructions |
| `src/superpower_workflow/orchestrator.py` | Edit | Add `_verify_quality_gates`, `_check_coverage`, `_check_trailers`, quality gate checkpoints, new state values |
| `skills/ultrathink-gap-analysis/SKILL.md` | Edit | Reference quality gates |
| `tests/test_state.py` | Edit | Test previous_gap_summaries |
| `tests/test_convergence_gate.py` | Edit | Test loop detection |
| `tests/test_prompts.py` | Edit | Test new prompt content |
| `tests/test_orchestrator.py` | Edit | Test quality gates, coverage, trailers |

---

### Task 1: Add previous_gap_summaries to PhaseState

**Files:**
- Modify: `src/superpower_workflow/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_state.py
def test_phase_state_gap_summaries(tmp_path):
    from superpower_workflow.state import PhaseState, save_phase_state, load_phase_state
    cd = tmp_path / ".claude"
    cd.mkdir()
    phase = PhaseState(
        phase="ultrathink", iteration=2, max_iterations=5,
        previous_important_gaps=4,
        previous_gap_summaries=["[ultrathink] Store.put missing error", "[ultrathink] No tests for edge case"],
    )
    save_phase_state(cd, phase)
    loaded = load_phase_state(cd)
    assert loaded.previous_gap_summaries == ["[ultrathink] Store.put missing error", "[ultrathink] No tests for edge case"]
```

- [ ] **Step 2: Run test — expect FAIL** (field doesn't exist yet)

- [ ] **Step 3: Add field to PhaseState**

In `state.py`, add to PhaseState dataclass:
```python
@dataclass
class PhaseState:
    phase: str
    iteration: int = 0
    max_iterations: int = 5
    previous_important_gaps: int | None = None
    previous_gap_summaries: list[str] = field(default_factory=list)
```

Add `from dataclasses import dataclass, field` if not already imported.

- [ ] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/ruff check src/superpower_workflow/state.py tests/test_state.py --fix
.venv/Scripts/ruff format src/superpower_workflow/state.py tests/test_state.py
git add src/superpower_workflow/state.py tests/test_state.py
git commit -m "feat: add previous_gap_summaries to PhaseState for loop detection"
```

---

### Task 2: Add loop detection to convergence hook

**Files:**
- Modify: `src/superpower_workflow/hooks/convergence_gate.py`
- Modify: `tests/test_convergence_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_convergence_gate.py
import json
from pathlib import Path
from superpower_workflow.hooks.convergence_gate import compute_exit_code, _is_stuck


def test_is_stuck_detects_repeated_gaps():
    current = ["[ultrathink] Store.put missing error at store.py:45", "[ultrathink] No validation"]
    previous = ["[ultrathink] Store.put missing error at store.py:47", "[ultrathink] No validation"]
    assert _is_stuck(current, previous) is True


def test_is_stuck_allows_new_gaps():
    current = ["[ultrathink] New gap A", "[ultrathink] New gap B"]
    previous = ["[ultrathink] Old gap X", "[ultrathink] Old gap Y"]
    assert _is_stuck(current, previous) is False


def test_is_stuck_handles_empty():
    assert _is_stuck([], ["gap"]) is False
    assert _is_stuck(["gap"], []) is False


def test_stuck_loop_allows_stop(tmp_path):
    cd = tmp_path / ".claude"
    cd.mkdir()
    summaries = ["[ultrathink] Same gap A", "[ultrathink] Same gap B"]
    (cd / ".workflow-phase.json").write_text(json.dumps({
        "phase": "ultrathink", "iteration": 2, "max_iterations": 5,
        "previous_important_gaps": 3,
        "previous_gap_summaries": summaries,
    }))
    (cd / ".gap-report.json").write_text(json.dumps({
        "critical_gaps": 0, "important_gaps": 3, "tests_green": True, "lint_clean": True,
        "gap_summaries": summaries,
    }))
    assert compute_exit_code(cd) == 0  # stuck → allow stop
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement _is_stuck and integrate into compute_exit_code**

Add to `convergence_gate.py`:

```python
import re

def _is_stuck(current_summaries: list[str], previous_summaries: list[str]) -> bool:
    if not previous_summaries or not current_summaries:
        return False

    def normalize(s: str) -> str:
        s = re.sub(r":\d+", "", s)
        s = re.sub(r"\S+/", "", s)
        return s.strip().lower()

    current_normalized = {normalize(s) for s in current_summaries}
    previous_normalized = {normalize(s) for s in previous_summaries}
    overlap = current_normalized & previous_normalized
    if len(current_normalized) == 0:
        return False
    return len(overlap) / len(current_normalized) > 0.8
```

In `compute_exit_code`, after reading the gap report and before the convergence check, add:

```python
current_summaries = report.get("gap_summaries", [])
prev_summaries = phase.get("previous_gap_summaries", [])
if _is_stuck(current_summaries, prev_summaries):
    return 0  # stuck loop, allow stop
```

In `_increment_iteration`, also store current summaries:

```python
def _increment_iteration(phase_path, phase, current_important=None, current_summaries=None):
    phase["iteration"] = phase.get("iteration", 0) + 1
    if current_important is not None:
        phase["previous_important_gaps"] = current_important
    if current_summaries is not None:
        phase["previous_gap_summaries"] = current_summaries
    ...
```

Update the `_increment_iteration` call to pass `current_summaries`.

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
git add src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py
git commit -m "feat: add loop detection to convergence hook via fuzzy gap matching"
```

---

### Task 3: Add quality gate instructions to prompts

**Files:**
- Modify: `src/superpower_workflow/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_prompts.py
def test_system_prompt_includes_trailer_instruction():
    from superpower_workflow.prompts import system_prompt
    p = system_prompt()
    assert "Generated-By" in p

def test_phase_b_prompt_includes_quality_gate_instruction():
    from superpower_workflow.prompts import phase_b_prompt
    p = phase_b_prompt(name="m1", context_summary="", plan_path="plan.md")
    assert "lint" in p.lower() or "HARD gate" in p or "Do NOT commit" in p
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Update prompts**

In `system_prompt()`, add:
```python
"Include a Generated-By trailer on every commit: git commit --trailer \"Generated-By: <your-model-name>\""
```

In `phase_b_prompt()`, add after the production mindset line:
```python
f"\nAfter each task, before committing: run lint, fix issues. Do NOT commit code that fails lint or tests."
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
git add src/superpower_workflow/prompts.py tests/test_prompts.py
git commit -m "feat: add quality gate and git trailer instructions to prompts"
```

---

### Task 4: Implement _verify_quality_gates on Orchestrator

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_orchestrator.py
import json
from subprocess import CompletedProcess
from unittest.mock import patch
from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.logger import WorkflowLogger


def test_quality_gates_pass_when_all_commands_succeed(tmp_path):
    _config_with_gates(tmp_path)
    success = CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("superpower_workflow.orchestrator.subprocess.run", return_value=success):
        orch = Orchestrator(tmp_path)
        logger = WorkflowLogger(tmp_path / ".claude", "test")
        passed, failures = orch._verify_quality_gates(logger)
        logger.close()
    assert passed is True
    assert failures == []


def test_quality_gates_fail_on_lint_error(tmp_path):
    _config_with_gates(tmp_path)
    def mock_run(cmd, **kwargs):
        if "lint" in str(cmd):
            return CompletedProcess(args=[], returncode=1, stdout="E501 line too long", stderr="")
        return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=mock_run):
        orch = Orchestrator(tmp_path)
        logger = WorkflowLogger(tmp_path / ".claude", "test")
        passed, failures = orch._verify_quality_gates(logger)
        logger.close()
    assert passed is False
    assert any("lint" in f for f in failures)


def test_quality_gates_skip_when_not_configured(tmp_path):
    _config(tmp_path)  # no quality_gates section
    with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess):
        orch = Orchestrator(tmp_path)
        logger = WorkflowLogger(tmp_path / ".claude", "test")
        passed, failures = orch._verify_quality_gates(logger)
        logger.close()
    assert passed is True


def _config_with_gates(tmp_path):
    config = _config(tmp_path)
    config["quality_gates"] = {
        "lint": "ruff check .",
        "sast": None,
        "dep_scan": None,
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config
```

Use the existing `_config` helper from the test file. Add `_config_with_gates` that extends it.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement _verify_quality_gates**

Add to `Orchestrator` class:

```python
def _verify_quality_gates(self, logger: WorkflowLogger) -> tuple[bool, list[str]]:
    gates = self.config.get("quality_gates", {})
    if not gates:
        return True, []
    failures: list[str] = []
    for gate_name in ("lint", "sast", "secret_scan", "dep_scan"):
        cmd = gates.get(gate_name)
        if not cmd:
            continue
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=self.cwd, timeout=300,
            )
            if result.returncode != 0:
                detail = (result.stdout or result.stderr)[:500]
                failures.append(f"{gate_name}: {detail}")
                logger.log("QUALITY_GATE_FAILED", gate=gate_name)
            else:
                logger.log("QUALITY_GATE_PASSED", gate=gate_name)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            failures.append(f"{gate_name}: {e}")
            logger.log("QUALITY_GATE_ERROR", gate=gate_name, error=str(e))
    return len(failures) == 0, failures
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add _verify_quality_gates method to Orchestrator"
```

---

### Task 5: Add quality gate checkpoints to _run_milestone

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_orchestrator.py
def test_quality_gate_checkpoint_runs_after_phase_b(tmp_path):
    _config_with_gates(tmp_path)
    calls = []
    def mock_run_claude(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("prompt", ""))
        return _ok_result()
    def mock_subprocess(cmd, **kwargs):
        if isinstance(cmd, str) and "lint" in cmd:
            return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        return _smart_subprocess(cmd, **kwargs)
    with (
        patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=mock_subprocess),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()
    # Should have 4 phase calls + no extra fix call (gates passed)
    assert len(calls) >= 4
```

- [ ] **Step 2: Run test — expect FAIL** (no checkpoint in _run_milestone yet)

- [ ] **Step 3: Add checkpoints to _run_milestone**

After Phase B completion (after `logger.log("PHASE_B_COMPLETE", ...)`), add:

```python
# Quality Gates Checkpoint #1
self.state.current_step = "quality_check_b"
save_state(self.claude_dir, self.state)
passed, failures = self._verify_quality_gates(logger)
if not passed:
    fix_prompt = (
        f"Quality gates failed after Phase B for {name}:\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\nFix ALL issues. Commit the fix."
    )
    run_claude(fix_prompt, model=model, effort="high", budget=10.0,
               cwd=self.cwd, system_prompt=self.sys_prompt, fallback_model=fallback)
    cost += 5.0  # estimate for fix pass
    passed, failures = self._verify_quality_gates(logger)
    if not passed:
        logger.log("QUALITY_GATES_STILL_FAILING", failures=str(failures))
```

Add the same pattern after Phase C completion (checkpoint #2).

- [ ] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add quality gate checkpoints after Phase B and Phase C"
```

---

### Task 6: Implement _check_coverage

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
def test_coverage_check_passes_above_threshold(tmp_path):
    _config_with_gates(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    config["quality_gates"]["coverage_command"] = "echo ok"
    config["quality_gates"]["coverage_threshold"] = 80
    config["quality_gates"]["coverage_report_path"] = "coverage.json"
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    # Create a fake coverage.json
    (tmp_path / "coverage.json").write_text(json.dumps({"totals": {"percent_covered_display": "85"}}))
    success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("superpower_workflow.orchestrator.subprocess.run", return_value=success):
        orch = Orchestrator(tmp_path)
        logger = WorkflowLogger(tmp_path / ".claude", "test")
        result = orch._check_coverage(logger)
        logger.close()
    assert result is True


def test_coverage_check_skipped_when_not_configured(tmp_path):
    _config(tmp_path)  # no coverage settings
    with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess):
        orch = Orchestrator(tmp_path)
        logger = WorkflowLogger(tmp_path / ".claude", "test")
        result = orch._check_coverage(logger)
        logger.close()
    assert result is True
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement _check_coverage**

```python
def _check_coverage(self, logger: WorkflowLogger) -> bool:
    gates = self.config.get("quality_gates", {})
    cmd = gates.get("coverage_command")
    threshold = gates.get("coverage_threshold", 0)
    max_attempts = gates.get("coverage_max_attempts", 3)
    report_path = gates.get("coverage_report_path", "coverage.json")
    if not cmd or threshold == 0:
        return True
    for attempt in range(max_attempts):
        subprocess.run(cmd, shell=True, capture_output=True, cwd=self.cwd, timeout=600)
        coverage = self._parse_coverage(report_path)
        if coverage >= threshold:
            logger.log("COVERAGE_PASSED", coverage=coverage, threshold=threshold)
            return True
        logger.log("COVERAGE_BELOW", coverage=coverage, threshold=threshold, attempt=attempt + 1)
        if attempt < max_attempts - 1:
            run_claude(
                f"Branch coverage is {coverage}% (threshold: {threshold}%). "
                f"Write additional tests for uncovered code. Attempt {attempt + 1}/{max_attempts}.",
                model=self.config["model"], effort="high", budget=10.0,
                cwd=self.cwd, system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
            )
    return False

def _parse_coverage(self, report_path: str) -> float:
    path = Path(self.cwd) / report_path
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text())
        return float(data.get("totals", {}).get("percent_covered_display", "0"))
    except (json.JSONDecodeError, ValueError, KeyError):
        return 0.0
```

Add `_check_coverage` call in the quality gate checkpoint (after `_verify_quality_gates`).

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add coverage-target verification with iterative test generation"
```

---

### Task 7: Add git trailer verification

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

```python
def test_trailer_check_warns_on_missing(tmp_path):
    _config_with_gates(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    config["quality_gates"]["require_git_trailers"] = True
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

    def mock_subprocess(cmd, **kwargs):
        if isinstance(cmd, list) and "--format=%b" in cmd:
            return CompletedProcess(args=cmd, returncode=0, stdout="no trailer here\n", stderr="")
        return _smart_subprocess(cmd, **kwargs)

    with patch("superpower_workflow.orchestrator.subprocess.run", side_effect=mock_subprocess):
        orch = Orchestrator(tmp_path)
        logger = WorkflowLogger(tmp_path / ".claude", "test")
        orch._check_trailers("abc123", logger)
        logger.close()
    # Should log a warning but not fail
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement _check_trailers**

```python
def _check_trailers(self, since_sha: str, logger: WorkflowLogger) -> None:
    gates = self.config.get("quality_gates", {})
    if not gates.get("require_git_trailers"):
        return
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H %b", f"{since_sha}..HEAD"],
            capture_output=True, text=True, cwd=self.cwd, timeout=10,
        )
        if result.returncode != 0:
            return
        commits = result.stdout.strip().split("\n")
        missing = [c[:8] for c in commits if c.strip() and "Generated-By:" not in c]
        if missing:
            logger.log("TRAILER_MISSING", count=len(missing), commits=str(missing[:5]))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
```

Call `_check_trailers(plan_sha, logger)` after each quality gate checkpoint.

- [ ] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add git trailer verification (warn-only)"
```

---

### Task 8: Update ultrathink skill to reference quality gates

**Files:**
- Modify: `skills/ultrathink-gap-analysis/SKILL.md`

- [ ] **Step 1: Add quality gate reference**

After step 9 (Write gap report), add:

```markdown
10. **Quality gates:** If the project has quality_gates configured in workflow.json,
    the orchestrator will independently verify lint, SAST, coverage, and dep scan
    after this phase. Ensure your fixes don't introduce new lint or security issues.
```

- [ ] **Step 2: Commit**

```bash
git add skills/ultrathink-gap-analysis/SKILL.md
git commit -m "feat: reference quality gates in ultrathink skill"
```

---

### Task 9: Full test suite verification + lint

- [ ] **Step 1: Run full suite**

```bash
.venv/Scripts/pytest -v
```

- [ ] **Step 2: Ruff check + format**

```bash
.venv/Scripts/ruff check src/ tests/ --fix
.venv/Scripts/ruff format src/ tests/
```

- [ ] **Step 3: Commit if any format changes**

```bash
git add -A
git commit -m "style: apply ruff format across SP1 quality gates"
```

---

## Self-Review

**Spec coverage:**
- §2 (execution flow) → Task 5 (checkpoints in _run_milestone)
- §3 (configuration) → Task 4 (quality_gates config reading)
- §4 (self-review pipeline) → Tasks 3, 4, 5 (prompts + _verify_quality_gates + checkpoints)
- §5 (coverage) → Task 6 (_check_coverage)
- §6 (loop detection) → Task 2 (_is_stuck + convergence_gate integration)
- §7 (backpressure) → Task 5 (checkpoints ARE the backpressure)
- §8 (git trailers) → Tasks 3, 7 (prompt instruction + _check_trailers)
- §9 (dep scan) → Task 4 (part of _verify_quality_gates)
- §10 (state & resume) → Tasks 1, 5 (PhaseState field + new current_step values)
- §11 (files changed) → Tasks 1-8 cover all 8 files

All spec sections covered. ✓

**Placeholder scan:** No TBD, TODO, or "implement later." ✓

**Type consistency:** `_verify_quality_gates` returns `tuple[bool, list[str]]` consistently. `_is_stuck` takes `list[str], list[str]` everywhere. `PhaseState.previous_gap_summaries` is `list[str]` in dataclass and in JSON. ✓
