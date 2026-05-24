# SP1: Quality Gates — Design Spec

**Date:** 2026-05-24
**Spec version:** 1.0
**Status:** Approved for implementation planning
**Roadmap:** SP1 of 7 → v0.2.0
**Goal:** Code-enforced quality verification at every stage — defense in depth where skills instruct Claude and the orchestrator independently verifies.

> Validated through 2 ultrathink passes (45 gaps found, all critical/important resolved).

---

## 1. Overview

Six quality features that shift output from "Claude says it's good" to "orchestrator verified it's good":

1. **Self-review pipeline** — lint + SAST + secret scan enforced by orchestrator after Phase B and C
2. **Coverage-target test generation** — iterative test writing until branch coverage threshold met
3. **Loop detection** — fuzzy-match convergence summaries to detect stuck loops
4. **Backpressure gates** — hard verification checkpoint between phases
5. **Git trailers** — AI attribution on every commit
6. **Dependency vulnerability scan** — real CVE scanning via pip-audit/npm audit

**Architecture:** Hybrid — skills INSTRUCT Claude what to do during generation. Orchestrator VERIFIES results after each phase using real tools (not AI judgment). If verification fails, orchestrator re-invokes Claude with specific failure details.

---

## 2. Execution Flow (revised)

```
Phase A: Plan + Ultrathink (convergence loop)
  ↓
Capture SHA + rollback tag
  ↓
Phase B: Implement (subagent-driven-dev)
  ↓
QUALITY GATES CHECKPOINT #1
  Run: lint, SAST, secret scan, coverage, dep scan
  If fail → claude -p "Fix: {specific failures}" (one-shot, no convergence)
  state: current_step = "quality_check_b"
  ↓
Phase C: Review + Fix (convergence loop)
  ↓
QUALITY GATES CHECKPOINT #2
  Run: same gates (Phase C fixes must also pass)
  If fail → claude -p "Fix: {specific failures}" (one-shot)
  state: current_step = "quality_check_c"
  ↓
Phase D: Push + Tag
```

Quality gate failures are NOT phase errors. They're a separate category: the claude -p call succeeded, but the output doesn't meet quality standards. The fix invocation is one-shot (no `.workflow-phase.json`, no convergence hook).

---

## 3. Configuration

New optional `quality_gates` section in workflow.json:

```json
{
  "quality_gates": {
    "lint": ".venv\\Scripts\\ruff check .",
    "sast": "python -m bandit -r src/ -q",
    "secret_scan": null,
    "dep_scan": "python -m pip_audit",
    "coverage_command": "python -m pytest --cov=src --cov-branch --cov-report=json -q",
    "coverage_threshold": 80,
    "coverage_max_attempts": 3,
    "coverage_report_path": "coverage.json",
    "require_git_trailers": true
  }
}
```

All fields optional. Missing section = no quality gates (backward compatible). Missing individual field = skip that gate. Tools are user-configured per project (Python: bandit, TS: eslint --security, Rust: cargo audit).

---

## 4. Self-Review Pipeline

### Skill layer (Phase B prompt addition)
```
After implementing each task, before committing:
1. Run lint on changed files. Fix any issues.
2. Run SAST scan if configured. Fix security findings.
   If a finding is a false positive, add inline suppression with justification.
3. Check for secrets/credentials in your code. Remove them.
These are HARD gates — do NOT commit code that fails any check.
```

### Orchestrator layer (_verify_quality_gates)

New method on Orchestrator:

```python
def _verify_quality_gates(self, logger: WorkflowLogger) -> tuple[bool, list[str]]:
    """Run all configured quality gates. Returns (all_passed, failure_details)."""
    gates = self.config.get("quality_gates", {})
    failures = []
    
    for gate_name in ("lint", "sast", "secret_scan", "dep_scan"):
        cmd = gates.get(gate_name)
        if not cmd:
            continue
        result = subprocess.run(cmd, shell=True, capture_output=True, 
                                text=True, cwd=self.cwd, timeout=300)
        if result.returncode != 0:
            failures.append(f"{gate_name}: {result.stdout[:500]}")
            logger.log("QUALITY_GATE_FAILED", gate=gate_name)
        else:
            logger.log("QUALITY_GATE_PASSED", gate=gate_name)
    
    return len(failures) == 0, failures
```

### Fix invocation on failure

```python
if not passed:
    fix_prompt = (
        f"Quality gates failed after Phase B for {name}:\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\nFix ALL issues. Commit the fix."
    )
    run_claude(fix_prompt, model=model, effort="high", budget=10, ...)
    # Re-verify after fix
    passed, failures = self._verify_quality_gates(logger)
    if not passed:
        logger.log("QUALITY_GATES_STILL_FAILING", failures=str(failures))
```

No `.workflow-phase.json` created. No convergence hook. One-shot fix.

---

## 5. Coverage-Target Test Generation

### Skill layer (Phase B prompt addition)
```
After implementing each task, run coverage: {coverage_command}
If branch coverage is below {coverage_threshold}%, write additional tests targeting
uncovered lines. Iterate until threshold met or 3 attempts exhausted.
```

### Orchestrator layer

```python
def _check_coverage(self, logger) -> bool:
    gates = self.config.get("quality_gates", {})
    cmd = gates.get("coverage_command")
    threshold = gates.get("coverage_threshold", 0)
    max_attempts = gates.get("coverage_max_attempts", 3)
    report_path = gates.get("coverage_report_path", "coverage.json")
    
    if not cmd or threshold == 0:
        return True
    
    for attempt in range(max_attempts):
        subprocess.run(cmd, shell=True, capture_output=True, cwd=self.cwd)
        coverage = self._parse_coverage(report_path)
        if coverage >= threshold:
            logger.log("COVERAGE_PASSED", coverage=coverage, threshold=threshold)
            return True
        logger.log("COVERAGE_BELOW", coverage=coverage, threshold=threshold, attempt=attempt+1)
        run_claude(
            f"Branch coverage is {coverage}% (threshold: {threshold}%). "
            f"Write additional tests for uncovered code. Attempt {attempt+1}/{max_attempts}.",
            model=model, effort="high", budget=10, cwd=self.cwd, ...
        )
    return False
```

Uses `--cov-branch` for branch coverage. Parses `coverage.json` for the percentage. Capped at 3 attempts.

---

## 6. Loop Detection

### In convergence_gate.py

Store `previous_gap_summaries` in `.workflow-phase.json`:

```json
{
  "phase": "ultrathink",
  "iteration": 3,
  "max_iterations": 5,
  "previous_important_gaps": 4,
  "previous_gap_summaries": ["[ultrathink] Store.put missing error...", "..."]
}
```

Detection logic:
```python
def _is_stuck(current_summaries, previous_summaries):
    if not previous_summaries or not current_summaries:
        return False
    # Normalize: strip line numbers and file paths to basenames
    def normalize(s):
        s = re.sub(r':\d+', '', s)      # strip :45
        s = re.sub(r'\S+/', '', s)       # strip path/ prefixes
        return s.strip().lower()
    
    current_normalized = {normalize(s) for s in current_summaries}
    previous_normalized = {normalize(s) for s in previous_summaries}
    overlap = current_normalized & previous_normalized
    
    if len(current_normalized) == 0:
        return False
    return len(overlap) / len(current_normalized) > 0.8
```

If stuck: allow stop, log `CONVERGENCE_STUCK` warning.

---

## 7. Backpressure Gates

**Skill layer:** Already in Phase B prompt: "Do NOT commit code that fails tests or lint."

**Orchestrator layer:** The quality gate checkpoint (#1 and #2) IS the backpressure. It runs after Phase B and after Phase C. If gates fail, the milestone doesn't proceed to the next phase.

**TDD compatibility:** Backpressure applies at the END of each task (after green step), not after every commit. The TDD red→green→commit cycle within a task is unaffected. The orchestrator only checks at phase boundaries.

---

## 8. Git Trailers

### Skill layer (system prompt addition)
```
Include a Git trailer on every commit: Generated-By: <your-model-name>
Use git commit --trailer "Generated-By: <model>" syntax.
```

### Orchestrator layer (verification only)

After each phase, verify trailers exist:
```python
if gates.get("require_git_trailers"):
    result = subprocess.run(
        ["git", "log", "--format=%b", f"{plan_sha}..HEAD"],
        capture_output=True, text=True, cwd=self.cwd,
    )
    commits_without = [...]  # parse
    if commits_without:
        logger.log("TRAILER_MISSING", count=len(commits_without))
```

Warn only — don't amend (amending changes hashes for all subsequent commits).

---

## 9. Dependency Vulnerability Scan

### Orchestrator layer

Part of `_verify_quality_gates()`. Runs the configured tool:
- Python: `python -m pip_audit`
- TypeScript: `npm audit --audit-level=high`
- Rust: `cargo audit`

**Fix behavior:**
- If CVE has a patched version in same major: auto-bump
- If CVE requires major version bump: flag as 🔴-architectural
- If no fix available: flag as 🔴-architectural with note

Dep scan runs in BOTH quality gate checkpoints (after Phase B and after Phase C).

---

## 10. State & Resume

### New current_step values

```
null | "plan" | "implement" | "quality_check_b" | "review" | "quality_check_c" | "push"
```

Resume behavior:
- `quality_check_b` → re-run quality gates (not Phase B)
- `quality_check_c` → re-run quality gates (not Phase C)

---

## 11. Files Changed

| File | Change |
|---|---|
| `src/superpower_workflow/orchestrator.py` | Add `_verify_quality_gates`, `_check_coverage`, quality gate checkpoints, new state values |
| `src/superpower_workflow/hooks/convergence_gate.py` | Add loop detection (fuzzy match, `previous_gap_summaries`) |
| `src/superpower_workflow/state.py` | Add `previous_gap_summaries` to PhaseState |
| `src/superpower_workflow/prompts.py` | Add quality gate instructions to Phase B prompt, trailer to system prompt |
| `skills/ultrathink-gap-analysis/SKILL.md` | Reference quality gates in procedure |
| `tests/test_orchestrator.py` | Tests for quality gates, coverage check, fix invocation |
| `tests/test_convergence_gate.py` | Tests for loop detection |
| `tests/test_prompts.py` | Tests for new prompt content |

---

## 12. Appendix

### Design Validation
- **Pass 1:** 25 gaps (tool compatibility, TDD conflict, trailer mechanics, config design, dep scan edge cases)
- **Pass 2:** 20 gaps (flow structure, error distinction, resume states, cross-phase gates, cost impact)
- **Total: 45 gaps** — all critical and important resolved
