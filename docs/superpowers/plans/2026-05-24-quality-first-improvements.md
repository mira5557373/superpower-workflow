# Quality-First Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve superpower-workflow output from "working code" to "production-deployable code" via enhanced skills, richer context, and a new production-readiness review skill.

**Architecture:** Skill files (markdown) control Claude's behavior during gap analysis and review. context.py (Python) provides git-based codebase awareness. prompts.py wires skills + context into each phase. Orchestrator passes milestone data to context and refreshes before Phase C.

**Tech Stack:** Python 3.11+, subprocess (git commands), pathlib, json, pytest, ruff.

**Spec reference:** `docs/superpowers/specs/2026-05-24-quality-first-improvements.md` (v1.0).

**Working directory:** `superpower-workflow/` (the repo root).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `skills/ultrathink-gap-analysis/SKILL.md` | Rewrite | Core procedure (<200 words), references link |
| `skills/ultrathink-gap-analysis/references/heuristics.md` | Create | Plan + code heuristics, severity calibration, quality standards, anti-patterns |
| `skills/production-readiness-review/SKILL.md` | Create | Artifact detection, profile checklists, severity, dedup, post-fix verify |
| `skills/post-impl-review/SKILL.md` | Edit | Add sub-steps 3.5-3.9 |
| `src/superpower_workflow/context.py` | Rewrite | Git-based module paths, exports, test counts, dependency detail |
| `src/superpower_workflow/prompts.py` | Edit | Phase A/B/C enhancements |
| `src/superpower_workflow/orchestrator.py` | Edit | Pass milestone data to context, refresh before Phase C |
| `tests/test_context.py` | Rewrite | Test new context parameters and output |
| `tests/test_prompts.py` | Update | Verify new prompt content |
| `install.py` | Edit | Add production-readiness-review to COPIES |

---

### Task 1: Rewrite ultrathink-gap-analysis skill (split into SKILL.md + references/)

**Files:**
- Rewrite: `skills/ultrathink-gap-analysis/SKILL.md`
- Create: `skills/ultrathink-gap-analysis/references/heuristics.md`

- [ ] **Step 1: Create references directory**

```bash
mkdir -p skills/ultrathink-gap-analysis/references
```

- [ ] **Step 2: Write the core SKILL.md (<200 words)**

```markdown
---
name: ultrathink-gap-analysis
description: Use when reviewing a plan, spec, or implementation for gaps — performs adversarial gap analysis with categorized severity, fixes mechanical issues, and writes a convergence-tracked gap report
---

# Ultrathink Gap Analysis

## Procedure

1. **Read context:** Read CLAUDE.md. Read __init__.py and main module of each dependency.
2. **Detect mode:** .md target = plan review. Code files = implementation review.
3. **Read config:** Check .claude/workflow.json for verify_commands and convergence settings.
4. **Size check:** >500 lines combined → dispatch reviewer via Agent tool.
5. **Read prior report:** If .claude/.gap-report.json exists, note already-fixed gaps.
6. **Enumerate gaps:** Minimum scales with artifact size: min(20, max(10, total_lines / 20)). First pass = broad (all categories). Later passes = focused (categories with remaining gaps).
7. **Categorize + fix:** Fix in priority order: 🔴 first, then 🟡, then 🔵. Flag 🔴-architectural (don't auto-fix).
8. **Write gap report:** .claude/.gap-report.json with gap_summaries tagged [ultrathink].
9. **Verify:** (implementation mode) Run test + lint. Must be green.

For detailed heuristics, severity calibration, quality standards, and anti-patterns, read references/heuristics.md.

## Convergence

critical_gaps == 0 AND (important_gaps <= 3 OR important_gaps <= previous * 0.5) OR max iterations reached.
```

- [ ] **Step 3: Write references/heuristics.md (full checklists)**

This file contains all heuristics from spec §2.2-2.6. Write the complete file with:

**Plan Review Heuristics:**
- Architecture checks (file paths, import consistency, circular deps, codebase patterns)
- Completeness checks (spec coverage, error/edge cases, integration points)
- Testability checks (test code per task, behavior vs implementation, edge cases)
- Task quality checks (single responsibility, acceptance criteria, dependency order)

**Code Review Heuristics:**
- Correctness (error paths, type mismatches, off-by-one, async cancellation)
- Security (path traversal, injection, secrets, unvalidated input, SSRF, hard guardrails)
- Testing (public functions tested, error paths tested, meaningful assertions, independence)
- Design (single responsibility, interfaces, consistency, imports resolve)
- Performance (N+1, unbounded collections, blocking I/O, resource leaks, connection limits)
- Concurrency (race conditions, deadlocks, async/await, cancellation, pool exhaustion)

**Severity Calibration** (plan + code tables from spec §2.4)

**Gap Quality Standards** (GOOD/BAD examples from spec §2.5)

**Anti-Patterns** (NEVER flag list from spec §2.6)

- [ ] **Step 4: Commit**

```bash
git add skills/ultrathink-gap-analysis/
git commit -m "feat: rewrite ultrathink skill with mode-specific heuristics and severity calibration"
```

---

### Task 2: Create production-readiness-review skill

**Files:**
- Create: `skills/production-readiness-review/SKILL.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p skills/production-readiness-review
```

- [ ] **Step 2: Write SKILL.md**

Write the complete skill file containing:

```markdown
---
name: production-readiness-review
description: Use after post-impl-review passes — checks security, performance, observability, error resilience, data integrity, deployment readiness, and documentation for production-deployable code
---

# Production Readiness Review

## When to use
After post-impl-review converges. Final quality gate before push.

## Artifact Type Detection
Look for: HTTP endpoint files (FastAPI/Flask routes) → service. argparse/click → CLI. Neither → library. Mixed → apply both profiles.

## Checklists

### COMMON (all profiles)
[Full checklist from spec §3.2 COMMON section]

### SERVICE (additional)
[Full checklist from spec §3.2 SERVICE section]

### CLI (additional)
[Full checklist from spec §3.2 CLI section]

## Severity
[From spec §3.3]

## Dedup Rule
If a gap was already flagged by a prior skill (check gap_summaries for same file:line), don't re-count it. Tag new gaps [production].

## Post-Fix Verification
After fixing production issues, re-run the full test suite before writing gap report.
```

- [ ] **Step 3: Commit**

```bash
git add skills/production-readiness-review/
git commit -m "feat: add production-readiness-review skill with library/service/CLI profiles"
```

---

### Task 3: Enhance post-impl-review skill

**Files:**
- Modify: `skills/post-impl-review/SKILL.md`

- [ ] **Step 1: Add sub-steps 3.5-3.9**

After the existing step 3, add:

```markdown
3.5. **Test assertion quality:**
     Weak (flag): `assert True`, `assert result`, `assert x is not None`, `assert len(x)`
     Strong (pass): `assert result == expected_value`, `assert x.name == "foo"`

3.6. **Cross-module consistency:**
     - Same exception hierarchy (project-specific base exception subclasses)
     - Same import ordering (ruff-enforced but verify)
     - Same test structure (matching existing pattern)

3.7. **Full test suite:**
     Run ALL tests, not just for changed files. Flag regressions in existing tests.

3.8. **Package hygiene:**
     - `__init__.py` exports public API only
     - No circular imports — test: `python -c "import package_name"`
     - All pyproject.toml dependencies actually imported
     - Type hints on all public function signatures (exception: decorators/metaclasses)

3.9. **Commit strategy:**
     Single commit unless >10 files changed. If >10: group by category.
```

- [ ] **Step 2: Commit**

```bash
git add skills/post-impl-review/SKILL.md
git commit -m "feat: enhance post-impl-review with assertion quality and package hygiene checks"
```

---

### Task 4: Rewrite context.py with git-based intelligence

**Files:**
- Rewrite: `src/superpower_workflow/context.py`
- Rewrite: `tests/test_context.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_context.py
import subprocess
from pathlib import Path
from unittest.mock import patch

from superpower_workflow.context import build_context_summary


def test_empty_completed_returns_no_prior():
    summary = build_context_summary(completed=[], project_root=Path("/tmp"))
    assert summary == "No prior milestones."


def test_single_milestone_shows_name():
    summary = build_context_summary(
        completed=["p1-m1-foundations"], project_root=Path("/tmp"),
    )
    assert "p1-m1-foundations" in summary


def test_dependency_detail_included():
    ms = {"name": "p1-m5-explorer", "depends_on": ["p1-m3-indexer", "p1-m4-tool-surface"]}
    milestones = [
        {"name": "p1-m3-indexer"}, {"name": "p1-m4-tool-surface"}, ms,
    ]
    summary = build_context_summary(
        completed=["p1-m1", "p1-m2", "p1-m3-indexer", "p1-m4-tool-surface"],
        project_root=Path("/tmp"),
        current_milestone=ms,
        milestones=milestones,
    )
    assert "p1-m3-indexer" in summary
    assert "p1-m4-tool-surface" in summary


def test_context_capped_at_400_words():
    completed = [f"p1-m{i}-milestone-{i}" for i in range(25)]
    summary = build_context_summary(completed=completed, project_root=Path("/tmp"))
    assert len(summary.split()) <= 400


def test_older_milestones_summarized():
    completed = ["m1", "m2", "m3", "m4", "m5", "m6"]
    summary = build_context_summary(completed=completed, project_root=Path("/tmp"))
    assert "m6" in summary  # recent — detailed
    assert "m5" in summary  # recent
    assert "m4" in summary  # recent
    # m1-m3 should be summarized (not individually detailed)


def test_test_count_included():
    def mock_iterdir(self):
        return [Path("test_a.py"), Path("test_b.py"), Path("test_c.py")]

    with patch.object(Path, "rglob", return_value=[Path("t1"), Path("t2"), Path("t3")]):
        with patch.object(Path, "exists", return_value=True):
            summary = build_context_summary(
                completed=["m1"], project_root=Path("/tmp"),
            )
    assert "3" in summary or "tests" in summary.lower()


def test_paths_use_forward_slashes():
    summary = build_context_summary(
        completed=["m1"], project_root=Path("/tmp"),
    )
    assert "\\" not in summary


def test_graceful_on_git_failure():
    def failing_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    with patch("superpower_workflow.context.subprocess.run", side_effect=failing_run):
        summary = build_context_summary(
            completed=["m1"], project_root=Path("/tmp"),
        )
    assert "m1" in summary  # still returns name-based fallback


def test_claude_md_pointer():
    summary = build_context_summary(completed=["m1"], project_root=Path("/tmp"))
    assert "CLAUDE.md" in summary
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
.venv/Scripts/pytest tests/test_context.py -v
```

- [ ] **Step 3: Implement context.py**

```python
# src/superpower_workflow/context.py
"""Git-based context generator for prompt templates."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

DETAIL_COUNT = 3
MAX_WORDS = 400


def build_context_summary(
    completed: list[str],
    project_root: Path,
    current_milestone: dict | None = None,
    milestones: list[dict] | None = None,
) -> str:
    if not completed:
        return "No prior milestones."

    parts = []

    test_count = _count_test_files(project_root)
    if test_count > 0:
        parts.append(f"Completed ({len(completed)} milestones, {test_count} test files):")
    else:
        parts.append(f"Completed ({len(completed)} milestones):")

    if len(completed) > DETAIL_COUNT:
        older = completed[:-DETAIL_COUNT]
        files = _get_milestone_files(project_root, older)
        if files:
            parts.append(f"  {', '.join(older)}: {files}")
        else:
            parts.append(f"  {', '.join(older)} complete.")

    recent = completed[-DETAIL_COUNT:]
    for name in recent:
        files = _get_milestone_files(project_root, [name])
        exports = _get_exports(project_root, name)
        line = f"  {name}"
        if files:
            line += f": {files}"
        if exports:
            line += f"\n    Exports: {exports}"
        parts.append(line)

    if current_milestone and current_milestone.get("depends_on"):
        deps = current_milestone["depends_on"]
        dep_lines = [f"\nFor {current_milestone['name']} (depends on {', '.join(deps)}):"]
        for dep in deps:
            exports = _get_exports(project_root, dep)
            if exports:
                dep_lines.append(f"  {dep} -> {exports}")
            else:
                dep_lines.append(f"  {dep}")
        parts.extend(dep_lines)

    parts.append("\nSee CLAUDE.md for full conventions.")

    summary = "\n".join(parts)
    summary = summary.replace("\\", "/")
    words = summary.split()
    if len(words) > MAX_WORDS:
        summary = " ".join(words[:MAX_WORDS])
    return summary


def _count_test_files(project_root: Path) -> int:
    tests_dir = project_root / "tests"
    if not tests_dir.exists():
        return 0
    try:
        return len(list(tests_dir.rglob("test_*.py")))
    except OSError:
        return 0


def _get_milestone_files(project_root: Path, names: list[str]) -> str:
    for name in reversed(names):
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"pre-impl/{name}^..pre-impl/{name}"],
                capture_output=True, text=True, cwd=str(project_root), timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                files = result.stdout.strip().split("\n")
                py_files = [f.replace("\\", "/") for f in files if f.endswith(".py")]
                if py_files:
                    return _compact_paths(py_files)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    return ""


def _get_exports(project_root: Path, milestone_name: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"pre-impl/{milestone_name}^..pre-impl/{milestone_name}"],
            capture_output=True, text=True, cwd=str(project_root), timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""

        files = result.stdout.strip().split("\n")
        init_files = [f for f in files if f.endswith("__init__.py")]

        exports = []
        for init_file in init_files:
            path = project_root / init_file
            if path.exists():
                content = path.read_text(errors="ignore")
                for match in re.findall(r"from\s+\S+\s+import\s+(.+)", content):
                    names = [n.strip().split(" as ")[0] for n in match.split(",")]
                    exports.extend(n for n in names if n and not n.startswith("_"))

        if not exports:
            for f in files:
                if f.endswith(".py") and not f.endswith("__init__.py") and not f.startswith("tests/"):
                    path = project_root / f
                    if path.exists():
                        content = path.read_text(errors="ignore")
                        for match in re.findall(r"^class\s+(\w+)", content, re.MULTILINE):
                            if not match.startswith("_"):
                                exports.append(match)

        return ", ".join(sorted(set(exports))[:10])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _compact_paths(paths: list[str]) -> str:
    if len(paths) <= 3:
        return ", ".join(paths)
    dirs: dict[str, list[str]] = {}
    for p in paths:
        parts = p.rsplit("/", 1)
        d = parts[0] if len(parts) > 1 else "."
        f = parts[-1].replace(".py", "")
        dirs.setdefault(d, []).append(f)
    segments = []
    for d, files in sorted(dirs.items()):
        if len(files) == 1:
            segments.append(f"{d}/{files[0]}.py")
        else:
            segments.append(f"{d}/{{{','.join(sorted(files))}}}.py")
    return " ".join(segments)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/Scripts/pytest tests/test_context.py -v
```

- [ ] **Step 5: Lint + format**

```bash
.venv/Scripts/ruff check src/superpower_workflow/context.py tests/test_context.py
.venv/Scripts/ruff format src/superpower_workflow/context.py tests/test_context.py
```

- [ ] **Step 6: Commit**

```bash
git add src/superpower_workflow/context.py tests/test_context.py
git commit -m "feat: rewrite context.py with git-based module paths and exports"
```

---

### Task 5: Enhance prompts.py

**Files:**
- Modify: `src/superpower_workflow/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1: Update Phase A prompt**

Add before the numbered steps:
```python
f"Before writing the plan:\n"
f"- Read CLAUDE.md for project conventions and module map\n"
f"- Read the __init__.py and main module of each dependency listed in the context\n"
f"- Understand the interfaces you will build against\n\n"
```

- [ ] **Step 2: Update Phase B prompt**

Add after the implementation instruction:
```python
f"\nWrite code with production deployment in mind: structured logging, error handling,\n"
f"input validation at boundaries. TDD first — after tests pass, add production\n"
f"concerns as a refactoring step within the same task.\n"
```

- [ ] **Step 3: Update Phase C prompt**

Replace the body with the restructured version from spec §5.3:
```python
f"1. Run post-impl-review on all files changed since {plan_commit_sha}.\n"
f"2. Then run production-readiness-review on the same files.\n"
f"3. Fix post-impl issues first (correctness), then production issues (hardening).\n"
f"4. Re-run full test suite after all fixes.\n"
f"5. Commit fixes. Tag each gap [post-impl] or [production] in gap_summaries.\n"
f"6. Write .claude/.gap-report.json.\n\n"
f"Verification: {verify_test}, {verify_lint}, {verify_format}"
```

- [ ] **Step 4: Update gap report schema in Phase A prompt**

Add `gap_summaries` field to the schema shown in the prompt.

- [ ] **Step 5: Update tests**

Add/update tests:
- `test_phase_a_prompt_includes_read_modules_instruction` — "Read CLAUDE.md" and "Read the __init__.py" in output
- `test_phase_b_prompt_includes_production_mindset` — "production deployment" in output
- `test_phase_c_prompt_includes_production_review` — "production-readiness-review" in output
- `test_phase_c_prompt_fix_order` — "post-impl issues first" before "production issues"
- `test_phase_a_prompt_includes_gap_summaries_schema` — "gap_summaries" in output

- [ ] **Step 6: Run tests — expect PASS**

```bash
.venv/Scripts/pytest tests/test_prompts.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/superpower_workflow/prompts.py tests/test_prompts.py
git commit -m "feat: enhance phase prompts with production mindset and module reading instructions"
```

---

### Task 6: Update orchestrator to pass milestone data and refresh context

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`

- [ ] **Step 1: Update context call in _run_milestone**

Replace:
```python
context = build_context_summary(self.state.completed)
```
With:
```python
context = build_context_summary(
    self.state.completed, self.root, ms, self.config.get("milestones", []),
)
```

- [ ] **Step 2: Refresh context before Phase C**

Before the Phase C block, add:
```python
context = build_context_summary(
    self.state.completed, self.root, ms, self.config.get("milestones", []),
)
```

This regenerates context AFTER Phase B, so Phase C sees what was just built.

- [ ] **Step 3: Update import**

Change:
```python
from superpower_workflow.context import build_context_summary
```
No change needed — same function, new parameters have defaults.

- [ ] **Step 4: Run orchestrator tests**

```bash
.venv/Scripts/pytest tests/test_orchestrator.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/superpower_workflow/orchestrator.py
git commit -m "feat: pass milestone data to context generator and refresh before Phase C"
```

---

### Task 7: Update install.py

**Files:**
- Modify: `install.py`

- [ ] **Step 1: Add production-readiness-review to COPIES**

```python
COPIES = [
    ("skills/ultrathink-gap-analysis", "skills/ultrathink-gap-analysis"),
    ("skills/post-impl-review", "skills/post-impl-review"),
    ("skills/production-readiness-review", "skills/production-readiness-review"),
    ("commands/ultrathink.md", "commands/ultrathink.md"),
]
```

- [ ] **Step 2: Commit**

```bash
git add install.py
git commit -m "feat: install production-readiness-review skill alongside existing skills"
```

---

### Task 8: Full test suite verification + lint

- [ ] **Step 1: Run full suite**

```bash
.venv/Scripts/pytest -v
```

Expected: all tests pass (existing + new context tests + updated prompt tests).

- [ ] **Step 2: Ruff check + format**

```bash
.venv/Scripts/ruff check src/ tests/
.venv/Scripts/ruff format --check src/ tests/
```

- [ ] **Step 3: Fix any issues and commit**

```bash
.venv/Scripts/ruff format src/ tests/
git add -A
git commit -m "style: apply ruff format across quality improvements"
```

---

### Task 9: Smoke test — verify skills install correctly

- [ ] **Step 1: Run install.py**

```bash
python install.py
```

Verify output shows:
- ultrathink-gap-analysis SKILL.md + references/heuristics.md copied
- production-readiness-review SKILL.md copied
- post-impl-review SKILL.md copied
- commands/ultrathink.md copied
- Stop hook registered (or already registered)

- [ ] **Step 2: Verify skills exist at target**

```bash
ls ~/.claude/skills/ultrathink-gap-analysis/SKILL.md
ls ~/.claude/skills/ultrathink-gap-analysis/references/heuristics.md
ls ~/.claude/skills/production-readiness-review/SKILL.md
ls ~/.claude/skills/post-impl-review/SKILL.md
```

- [ ] **Step 3: Commit any final fixes**

```bash
git commit -m "test: verify quality-first improvements install correctly"
```

---

## Self-Review

**Spec coverage:**
- §2 (ultrathink enhancement) → Task 1
- §3 (production-readiness skill) → Task 2
- §4 (context.py) → Task 4
- §5 (prompts) → Task 5
- §6 (post-impl-review) → Task 3
- §7.2 files list → Tasks 1-7 cover all 10 files
- Orchestrator integration (§4.4) → Task 6
- Install script (§7.2) → Task 7

All spec sections covered. ✓

**Placeholder scan:** No TBD, TODO, or "implement later." ✓

**Type consistency:** `build_context_summary` signature matches between context.py implementation and orchestrator.py call sites. ✓
