# SP1: Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add code-enforced quality verification (lint, SAST, coverage, dep scan, loop detection, git trailers) with orchestrator checkpoints after Phase B and Phase C.

**Architecture:** Hybrid — skills instruct Claude, orchestrator independently verifies using real tools. New `_verify_quality_gates`, `_check_coverage`, `_check_trailers` methods on Orchestrator. Loop detection added to convergence hook. Quality gate config is optional (backward compatible).

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
| `tests/test_state.py` | Edit | Test `previous_gap_summaries` |
| `tests/test_convergence_gate.py` | Edit | Test loop detection |
| `tests/test_prompts.py` | Edit | Test new prompt content |
| `tests/test_orchestrator.py` | Edit | Test quality gates, coverage, trailers, checkpoints |

---

### Task 1: Add previous_gap_summaries to PhaseState

**Files:**
- Modify: `src/superpower_workflow/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_state.py — add to class TestPhaseState

def test_phase_state_gap_summaries_roundtrip(self, tmp_claude_dir):
    """PhaseState saves and loads previous_gap_summaries correctly."""
    phase = PhaseState(
        phase="ultrathink",
        iteration=2,
        max_iterations=5,
        previous_important_gaps=4,
        previous_gap_summaries=[
            "[ultrathink] Store.put missing error",
            "[ultrathink] No tests for edge case",
        ],
    )
    save_phase_state(tmp_claude_dir, phase)
    loaded = load_phase_state(tmp_claude_dir)
    assert loaded is not None
    assert loaded.previous_gap_summaries == [
        "[ultrathink] Store.put missing error",
        "[ultrathink] No tests for edge case",
    ]


def test_phase_state_gap_summaries_default_empty(self, tmp_claude_dir):
    """PhaseState defaults previous_gap_summaries to empty list."""
    phase = PhaseState(phase="review", iteration=0)
    save_phase_state(tmp_claude_dir, phase)
    loaded = load_phase_state(tmp_claude_dir)
    assert loaded is not None
    assert loaded.previous_gap_summaries == []
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

`field` is already imported from `dataclasses`.

- [ ] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/state.py tests/test_state.py --fix
ruff format src/superpower_workflow/state.py tests/test_state.py
git add src/superpower_workflow/state.py tests/test_state.py
git commit -m "feat: add previous_gap_summaries to PhaseState for loop detection"
```

---

### Task 2: Add _is_stuck loop detection function

**Files:**
- Modify: `src/superpower_workflow/hooks/convergence_gate.py`
- Modify: `tests/test_convergence_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_convergence_gate.py — add import and new class
from superpower_workflow.hooks.convergence_gate import _is_stuck


class TestIsStuck:
    """Test _is_stuck loop detection function."""

    def test_detects_repeated_gaps_with_different_line_numbers(self):
        current = [
            "[ultrathink] Store.put missing error at store.py:45",
            "[ultrathink] No validation",
        ]
        previous = [
            "[ultrathink] Store.put missing error at store.py:47",
            "[ultrathink] No validation",
        ]
        assert _is_stuck(current, previous) is True

    def test_allows_new_gaps(self):
        current = ["[ultrathink] New gap A", "[ultrathink] New gap B"]
        previous = ["[ultrathink] Old gap X", "[ultrathink] Old gap Y"]
        assert _is_stuck(current, previous) is False

    def test_handles_empty_current(self):
        assert _is_stuck([], ["some gap"]) is False

    def test_handles_empty_previous(self):
        assert _is_stuck(["some gap"], []) is False

    def test_handles_both_empty(self):
        assert _is_stuck([], []) is False

    def test_strips_path_prefixes(self):
        current = ["[ultrathink] Missing handler in src/handlers/auth.py"]
        previous = ["[ultrathink] Missing handler in handlers/auth.py"]
        assert _is_stuck(current, previous) is True

    def test_partial_overlap_below_threshold(self):
        current = ["gap A", "gap B", "gap C", "gap D", "gap E"]
        previous = ["gap A", "gap B", "gap C", "gap X", "gap Y"]
        # 3/5 = 60% overlap, below 80% threshold
        assert _is_stuck(current, previous) is False
```

- [ ] **Step 2: Run tests — expect FAIL** (function doesn't exist)

- [ ] **Step 3: Implement _is_stuck**

Add to `convergence_gate.py`:

```python
import re


def _is_stuck(current_summaries: list[str], previous_summaries: list[str]) -> bool:
    """Detect stuck convergence loops via fuzzy gap matching."""
    if not previous_summaries or not current_summaries:
        return False

    def normalize(s: str) -> str:
        s = re.sub(r":\d+", "", s)
        s = re.sub(r"\S+/", "", s)
        return s.strip().lower()

    current_normalized = {normalize(s) for s in current_summaries}
    previous_normalized = {normalize(s) for s in previous_summaries}
    if len(current_normalized) == 0:
        return False
    overlap = current_normalized & previous_normalized
    return len(overlap) / len(current_normalized) > 0.8
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py --fix
ruff format src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py
git add src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py
git commit -m "feat: add _is_stuck loop detection function"
```

---

### Task 3: Integrate loop detection into convergence gate

**Files:**
- Modify: `src/superpower_workflow/hooks/convergence_gate.py`
- Modify: `tests/test_convergence_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_convergence_gate.py — add new class


class TestLoopDetectionIntegration:
    """Test loop detection wired into compute_exit_code."""

    def test_stuck_loop_allows_stop(self, tmp_claude_dir):
        """Repeated gaps across iterations -> exit 0 (allow stop)."""
        summaries = ["[ultrathink] Same gap A", "[ultrathink] Same gap B"]
        _write(
            tmp_claude_dir,
            phase={
                "phase": "ultrathink",
                "iteration": 2,
                "max_iterations": 5,
                "previous_important_gaps": 3,
                "previous_gap_summaries": summaries,
            },
            gap_report={
                "critical_gaps": 0,
                "important_gaps": 3,
                "tests_green": True,
                "lint_clean": True,
                "gap_summaries": summaries,
            },
        )
        assert compute_exit_code(tmp_claude_dir) == 0

    def test_not_stuck_continues_iteration(self, tmp_claude_dir):
        """Different gaps across iterations -> exit 2 (block stop)."""
        _write(
            tmp_claude_dir,
            phase={
                "phase": "ultrathink",
                "iteration": 1,
                "max_iterations": 5,
                "previous_important_gaps": 5,
                "previous_gap_summaries": [
                    "[ultrathink] Old gap X",
                    "[ultrathink] Old gap Y",
                ],
            },
            gap_report={
                "critical_gaps": 0,
                "important_gaps": 4,
                "tests_green": True,
                "lint_clean": True,
                "gap_summaries": [
                    "[ultrathink] New gap A",
                    "[ultrathink] New gap B",
                ],
            },
        )
        assert compute_exit_code(tmp_claude_dir) == 2

    def test_increment_stores_current_summaries(self, tmp_claude_dir):
        """After blocking, phase file stores current gap_summaries as previous."""
        _write(
            tmp_claude_dir,
            phase={
                "phase": "ultrathink",
                "iteration": 0,
                "max_iterations": 5,
            },
            gap_report={
                "critical_gaps": 0,
                "important_gaps": 5,
                "tests_green": True,
                "lint_clean": True,
                "gap_summaries": ["[ultrathink] Gap A", "[ultrathink] Gap B"],
            },
        )
        compute_exit_code(tmp_claude_dir)
        updated = json.loads(
            (tmp_claude_dir / ".workflow-phase.json").read_text()
        )
        assert updated["previous_gap_summaries"] == [
            "[ultrathink] Gap A",
            "[ultrathink] Gap B",
        ]
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Integrate into compute_exit_code**

In `compute_exit_code`, after reading the gap report and **before** the convergence check, add loop detection:

```python
# After: gap_report = json.loads(gap_path.read_text())
# Add:
current_summaries = gap_report.get("gap_summaries", [])
prev_summaries = phase.get("previous_gap_summaries", [])
if _is_stuck(current_summaries, prev_summaries):
    return 0
```

Update `_increment_iteration` to accept and store summaries (backward-compatible default):

```python
def _increment_iteration(
    phase_path: Path,
    phase: dict,
    current_important: int | None = None,
    current_summaries: list[str] | None = None,
) -> None:
    """Increment iteration counter and optionally update gap tracking."""
    phase["iteration"] = phase.get("iteration", 0) + 1
    if current_important is not None:
        phase["previous_important_gaps"] = current_important
    if current_summaries is not None:
        phase["previous_gap_summaries"] = current_summaries
    tmp = phase_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(phase, indent=2))
    os.replace(str(tmp), str(phase_path))
```

Update the `_increment_iteration` call at the bottom of `compute_exit_code` to pass summaries:

```python
_increment_iteration(
    phase_path, phase,
    current_important=important_gaps,
    current_summaries=current_summaries,
)
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py --fix
ruff format src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py
git add src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py
git commit -m "feat: integrate loop detection into convergence gate"
```

---

### Task 4: Add quality gate and git trailer instructions to prompts

**Files:**
- Modify: `src/superpower_workflow/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_prompts.py — add


def test_system_prompt_includes_trailer_instruction():
    p = system_prompt()
    assert "Generated-By" in p
    assert "git commit --trailer" in p


def test_phase_b_prompt_includes_quality_gate_instruction():
    p = phase_b_prompt(name="m1", context_summary="", plan_path="plan.md")
    assert "lint" in p.lower()
    assert "Do NOT commit" in p
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Update prompts**

In `system_prompt()`, append to the return string:
```python
'\nInclude a Generated-By trailer on every commit: '
'git commit --trailer "Generated-By: <your-model-name>"'
```

In `phase_b_prompt()`, append after the production mindset paragraph:
```python
f"\nAfter each task, before committing: run lint on changed files, fix issues. "
f"Do NOT commit code that fails lint or tests. These are HARD gates."
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/prompts.py tests/test_prompts.py --fix
ruff format src/superpower_workflow/prompts.py tests/test_prompts.py
git add src/superpower_workflow/prompts.py tests/test_prompts.py
git commit -m "feat: add quality gate and git trailer instructions to prompts"
```

---

### Task 5: Implement _verify_quality_gates on Orchestrator

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add imports at top of `tests/test_orchestrator.py`:
```python
import subprocess as subprocess_mod
from superpower_workflow.logger import WorkflowLogger
```

Add test helper:
```python
def _config_with_gates(tmp_path, gates=None):
    """Create config with quality_gates section."""
    config = _config(tmp_path)
    config["quality_gates"] = gates or {
        "lint": "ruff check .",
        "sast": None,
        "dep_scan": None,
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config
```

Add test class:
```python
class TestVerifyQualityGates:
    def test_all_gates_pass(self, tmp_path):
        _config_with_gates(tmp_path)
        success = CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with patch("superpower_workflow.orchestrator.subprocess.run", return_value=success):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is True
        assert failures == []

    def test_lint_failure_collected(self, tmp_path):
        _config_with_gates(tmp_path)

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, str) and "lint" in cmd:
                return CompletedProcess(
                    args=[], returncode=1, stdout="E501 line too long", stderr=""
                )
            return CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch(
            "superpower_workflow.orchestrator.subprocess.run", side_effect=mock_run
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is False
        assert any("lint" in f for f in failures)

    def test_multiple_gates_fail(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={"lint": "ruff check .", "sast": "bandit -r src/", "dep_scan": None},
        )
        fail = CompletedProcess(args=[], returncode=1, stdout="fail", stderr="")
        with patch("superpower_workflow.orchestrator.subprocess.run", return_value=fail):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is False
        assert len(failures) == 2
        assert any("lint" in f for f in failures)
        assert any("sast" in f for f in failures)

    def test_skip_when_not_configured(self, tmp_path):
        _config(tmp_path)
        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=_smart_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is True
        assert failures == []

    def test_timeout_handled_gracefully(self, tmp_path):
        _config_with_gates(tmp_path)

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, str):
                raise subprocess_mod.TimeoutExpired(cmd=cmd, timeout=300)
            return _smart_subprocess(cmd, **kwargs)

        with patch(
            "superpower_workflow.orchestrator.subprocess.run", side_effect=mock_run
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            passed, failures = orch._verify_quality_gates(logger)
            logger.close()
        assert passed is False
        assert any("lint" in f for f in failures)
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement _verify_quality_gates**

Add to `Orchestrator` class in `orchestrator.py`:

```python
def _verify_quality_gates(self, logger: WorkflowLogger) -> tuple[bool, list[str]]:
    """Run all configured quality gates. Returns (all_passed, failure_details)."""
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
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add _verify_quality_gates method to Orchestrator"
```

---

### Task 6: Implement _check_coverage

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


class TestCheckCoverage:
    def test_passes_above_threshold(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_report_path": "coverage.json",
            },
        )
        (tmp_path / "coverage.json").write_text(
            json.dumps({"totals": {"percent_covered_display": "85"}})
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch(
            "superpower_workflow.orchestrator.subprocess.run", return_value=success
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            result = orch._check_coverage(logger)
            logger.close()
        assert result is True

    def test_skipped_when_not_configured(self, tmp_path):
        _config(tmp_path)
        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=_smart_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            result = orch._check_coverage(logger)
            logger.close()
        assert result is True

    def test_returns_false_after_max_attempts(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_max_attempts": 2,
                "coverage_report_path": "coverage.json",
            },
        )
        (tmp_path / "coverage.json").write_text(
            json.dumps({"totals": {"percent_covered_display": "50"}})
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                return_value=success,
            ),
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            result = orch._check_coverage(logger)
            logger.close()
        assert result is False

    def test_missing_report_treated_as_zero(self, tmp_path):
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_max_attempts": 1,
                "coverage_report_path": "nonexistent.json",
            },
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch(
            "superpower_workflow.orchestrator.subprocess.run", return_value=success
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            result = orch._check_coverage(logger)
            logger.close()
        assert result is False
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement _check_coverage and _parse_coverage**

Add to `Orchestrator` class:

```python
def _check_coverage(self, logger: WorkflowLogger) -> bool:
    """Check branch coverage against threshold, iterating with Claude if below."""
    gates = self.config.get("quality_gates", {})
    cmd = gates.get("coverage_command")
    threshold = gates.get("coverage_threshold", 0)
    max_attempts = gates.get("coverage_max_attempts", 3)
    report_path = gates.get("coverage_report_path", "coverage.json")
    if not cmd or threshold == 0:
        return True
    for attempt in range(max_attempts):
        subprocess.run(
            cmd, shell=True, capture_output=True, cwd=self.cwd, timeout=600,
        )
        coverage = self._parse_coverage(report_path)
        if coverage >= threshold:
            logger.log("COVERAGE_PASSED", coverage=coverage, threshold=threshold)
            return True
        logger.log(
            "COVERAGE_BELOW",
            coverage=coverage, threshold=threshold, attempt=attempt + 1,
        )
        if attempt < max_attempts - 1:
            run_claude(
                f"Branch coverage is {coverage}% (threshold: {threshold}%). "
                f"Write additional tests for uncovered code. "
                f"Attempt {attempt + 1}/{max_attempts}.",
                model=self.config["model"],
                effort="high",
                budget=10.0,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
            )
    return False

def _parse_coverage(self, report_path: str) -> float:
    """Parse coverage.json for branch coverage percentage."""
    path = Path(self.cwd) / report_path
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text())
        return float(data.get("totals", {}).get("percent_covered_display", "0"))
    except (json.JSONDecodeError, ValueError, KeyError):
        return 0.0
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add coverage-target verification with iterative test generation"
```

---

### Task 7: Implement _check_trailers git trailer verification

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


class TestCheckTrailers:
    def test_warns_on_missing_trailers(self, tmp_path):
        _config_with_gates(
            tmp_path, gates={"lint": None, "require_git_trailers": True}
        )

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and any("--format=%H %b" in c for c in cmd):
                return CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="abc12345 no trailer here\n",
                    stderr="",
                )
            return _smart_subprocess(cmd, **kwargs)

        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=mock_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            orch._check_trailers("abc123", logger)
            logger.close()
        log_content = (tmp_path / ".claude" / "workflow-test.log").read_text()
        assert "TRAILER_MISSING" in log_content

    def test_skips_when_not_configured(self, tmp_path):
        _config(tmp_path)
        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=_smart_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            orch._check_trailers("abc123", logger)
            logger.close()
        log_content = (tmp_path / ".claude" / "workflow-test.log").read_text()
        assert "TRAILER" not in log_content

    def test_no_warning_when_trailers_present(self, tmp_path):
        _config_with_gates(
            tmp_path, gates={"lint": None, "require_git_trailers": True}
        )

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and any("--format=%H %b" in c for c in cmd):
                return CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="abc12345 feat: stuff\nGenerated-By: claude\n",
                    stderr="",
                )
            return _smart_subprocess(cmd, **kwargs)

        with patch(
            "superpower_workflow.orchestrator.subprocess.run",
            side_effect=mock_subprocess,
        ):
            orch = Orchestrator(tmp_path)
            logger = WorkflowLogger(tmp_path / ".claude", "test")
            orch._check_trailers("abc123", logger)
            logger.close()
        log_content = (tmp_path / ".claude" / "workflow-test.log").read_text()
        assert "TRAILER_MISSING" not in log_content
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement _check_trailers**

Add to `Orchestrator` class:

```python
def _check_trailers(self, since_sha: str, logger: WorkflowLogger) -> None:
    """Verify git trailers exist on commits since since_sha. Warn-only."""
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
        missing = [
            c[:8] for c in commits
            if c.strip() and "Generated-By:" not in c
        ]
        if missing:
            logger.log(
                "TRAILER_MISSING",
                count=len(missing),
                commits=str(missing[:5]),
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add git trailer verification (warn-only)"
```

---

### Task 8: Add quality gate checkpoint after Phase B

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


class TestQualityGateCheckpointB:
    def test_gates_pass_no_fix_invocation(self, tmp_path):
        """Quality gates pass after Phase B -> no fix prompt sent."""
        _config_with_gates(tmp_path)
        prompts = []

        def mock_run_claude(prompt, **kwargs):
            prompts.append(prompt)
            return _ok_result()

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        fix_prompts = [p for p in prompts if "Quality gates failed" in p]
        assert fix_prompts == []

    def test_fix_invoked_when_gate_fails(self, tmp_path):
        """Quality gates fail after Phase B -> fix prompt with failure details."""
        _config_with_gates(tmp_path)
        prompts = []

        def mock_run_claude(prompt, **kwargs):
            prompts.append(prompt)
            return _ok_result()

        gate_calls = {"n": 0}

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str) and "ruff" in cmd:
                gate_calls["n"] += 1
                if gate_calls["n"] == 1:
                    return CompletedProcess(
                        args=[], returncode=1, stdout="E501 line too long", stderr=""
                    )
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        fix_prompts = [p for p in prompts if "Quality gates failed" in p]
        assert len(fix_prompts) >= 1
        assert "lint" in fix_prompts[0]
        assert "E501" in fix_prompts[0]

    def test_fix_cost_tracked_from_result(self, tmp_path):
        """Fix invocation cost comes from ClaudeResult, not hardcoded."""
        _config_with_gates(tmp_path)
        costs = []

        def mock_run_claude(prompt, **kwargs):
            result = _ok_result(cost=3.5 if "Quality gates failed" in prompt else 1.0)
            costs.append(result.cost_usd)
            return result

        gate_calls = {"n": 0}

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str) and "ruff" in cmd:
                gate_calls["n"] += 1
                if gate_calls["n"] == 1:
                    return CompletedProcess(
                        args=[], returncode=1, stdout="fail", stderr=""
                    )
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert 3.5 in costs
        assert state.total_cost_usd > 4.0
```

- [ ] **Step 2: Run tests — expect FAIL** (no checkpoint in _run_milestone yet)

- [ ] **Step 3: Add checkpoint #1 to _run_milestone**

In `_run_milestone`, after Phase B completion (after `logger.log("PHASE_B_COMPLETE", ...)`), add:

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
    r = run_claude(
        fix_prompt,
        model=model,
        effort="high",
        budget=10.0,
        cwd=self.cwd,
        system_prompt=self.sys_prompt,
        fallback_model=fallback,
    )
    cost += r.cost_usd
    passed, failures = self._verify_quality_gates(logger)
    if not passed:
        logger.log("QUALITY_GATES_STILL_FAILING", failures=str(failures))
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add quality gate checkpoint after Phase B"
```

---

### Task 9: Add quality gate checkpoint after Phase C + coverage + trailers

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


class TestQualityGateCheckpointC:
    def test_checkpoint_c_runs_after_phase_c(self, tmp_path):
        """Checkpoint #2 runs quality gates after Phase C."""
        _config_with_gates(tmp_path)
        gate_calls = {"n": 0}

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str) and "ruff" in cmd:
                gate_calls["n"] += 1
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        # Gates called at both checkpoints (after B and after C)
        assert gate_calls["n"] >= 2

    def test_coverage_check_runs_in_checkpoint(self, tmp_path):
        """Coverage check integrated into quality gate checkpoint."""
        _config_with_gates(
            tmp_path,
            gates={
                "lint": None,
                "coverage_command": "echo ok",
                "coverage_threshold": 80,
                "coverage_report_path": "coverage.json",
            },
        )
        (tmp_path / "coverage.json").write_text(
            json.dumps({"totals": {"percent_covered_display": "90"}})
        )
        success = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                return_value=success,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_backward_compatible_no_quality_gates(self, tmp_path):
        """No quality_gates in config -> full run works as before."""
        _config(tmp_path)
        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add checkpoint #2 + coverage + trailers to _run_milestone**

After Phase C completion (after `logger.log("PHASE_C_COMPLETE", ...)`), add:

```python
# Quality Gates Checkpoint #2
self.state.current_step = "quality_check_c"
save_state(self.claude_dir, self.state)
passed, failures = self._verify_quality_gates(logger)
if not passed:
    fix_prompt = (
        f"Quality gates failed after Phase C for {name}:\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\nFix ALL issues. Commit the fix."
    )
    r = run_claude(
        fix_prompt,
        model=model,
        effort="high",
        budget=10.0,
        cwd=self.cwd,
        system_prompt=self.sys_prompt,
        fallback_model=fallback,
    )
    cost += r.cost_usd
    passed, failures = self._verify_quality_gates(logger)
    if not passed:
        logger.log("QUALITY_GATES_STILL_FAILING", failures=str(failures))

self._check_coverage(logger)
plan_sha = self.state.plan_commit_sha or ""
self._check_trailers(plan_sha, logger)
```

Also add `self._check_coverage(logger)` and `self._check_trailers(plan_sha, logger)` after checkpoint #1 (Task 8 code), so both checkpoints run the full suite.

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add quality gate checkpoint after Phase C with coverage and trailers"
```

---

### Task 10: Update ultrathink skill to reference quality gates

**Files:**
- Modify: `skills/ultrathink-gap-analysis/SKILL.md`

- [ ] **Step 1: Add quality gate reference**

After step 9 (Verify), add:

```markdown
10. **Quality gates:** If the project has `quality_gates` configured in workflow.json,
    the orchestrator will independently verify lint, SAST, coverage, and dep scan
    after this phase. Ensure your fixes don't introduce new lint or security issues.
```

- [ ] **Step 2: Commit**

```bash
git add skills/ultrathink-gap-analysis/SKILL.md
git commit -m "feat: reference quality gates in ultrathink skill"
```

---

### Task 11: Full test suite verification + lint

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
- §2 (execution flow) → Tasks 8, 9 (checkpoints in _run_milestone)
- §3 (configuration) → Task 5 (quality_gates config reading)
- §4 (self-review pipeline) → Tasks 4, 5, 8, 9 (prompts + _verify_quality_gates + checkpoints)
- §5 (coverage) → Task 6 (_check_coverage) + Task 9 (integration)
- §6 (loop detection) → Tasks 2, 3 (_is_stuck + convergence_gate integration)
- §7 (backpressure) → Tasks 8, 9 (checkpoints ARE the backpressure)
- §8 (git trailers) → Tasks 4, 7 (prompt instruction + _check_trailers)
- §9 (dep scan) → Task 5 (part of _verify_quality_gates)
- §10 (state & resume) → Tasks 1, 8, 9 (PhaseState field + new current_step values)
- §11 (files changed) → Tasks 1-10 cover all 8 files

All spec sections covered.

**Placeholder scan:** No TBD, TODO, or "implement later."

**Type consistency:** `_verify_quality_gates` returns `tuple[bool, list[str]]`. `_is_stuck` takes `list[str], list[str]`. `PhaseState.previous_gap_summaries` is `list[str]`. `_increment_iteration` has backward-compatible `current_summaries: list[str] | None = None`.

**Cost tracking:** Fix invocations use `r.cost_usd` from ClaudeResult, not hardcoded estimates.

**Backward compatibility:** No quality_gates section in config → all gates skip, orchestrator runs identically to pre-SP1.
