# Quality-First Improvements — Design Spec

**Date:** 2026-05-24
**Spec version:** 1.0
**Status:** Approved for implementation planning
**Goal:** Production-deployable code quality from every `sw run`

> Validated through 4 ultrathink passes (82 gaps found, all critical/important resolved).

---

## 1. Overview

Five improvements to superpower-workflow that shift output quality from "working code" to "production-deployable code." Based on real-world data: 35 milestones, $665, zero failures.

**Components changed:**
1. `ultrathink-gap-analysis` skill — rewrite with mode-specific heuristics + production checks
2. `production-readiness-review` skill — NEW, security/performance/observability/deployment
3. `context.py` — rewrite with git-based module paths, exports, test counts
4. `prompts.py` — enhanced Phase A/B/C prompts
5. `post-impl-review` skill — enhanced with assertion quality, consistency, package hygiene checks

**Constraint:** Quality and production readiness over cost and speed. No reduction in thoroughness.

---

## 2. Enhanced ultrathink-gap-analysis Skill

**Structure:** Split into `SKILL.md` (core procedure, <200 words) + `references/heuristics.md` (full checklists, loaded on demand).

### 2.1 Procedure Refinements

- Before analyzing: "Read CLAUDE.md. Read `__init__.py` and main module of each dependency."
- Gap minimum scales: `min(20, max(10, lines / 20))` — 10 for small, 20+ for large
- First pass = broad (all categories). Later passes = focused (categories with remaining gaps)
- Fix in priority order: 🔴 first, then 🟡, then 🔵
- Gap report includes `gap_summaries: list[str]` — each tagged `[ultrathink]`, `[post-impl]`, or `[production]`

### 2.2 Plan Review Heuristics

**Architecture:** File paths exist? Import paths consistent across tasks? Circular dependencies? Follows codebase patterns?

**Completeness:** Every spec feature has a task? Error/edge cases covered? Integration points with prior milestones?

**Testability:** Every task has test code? Tests verify behavior not implementation? Edge cases tested?

**Task quality:** Single responsibility per task? Acceptance criteria clear? Correct dependency order?

### 2.3 Code Review Heuristics

**Correctness:** All error paths handled? Type mismatches? Off-by-one? Async cancellation?

**Security:** Path traversal? Injection? Secrets in code/logs? Unvalidated input? SSRF? Spec hard guardrails?

**Testing:** Every public function tested? Error paths tested? Assertions meaningful (not `assert True`, `assert result`, `assert x is not None`)? Tests independent?

**Design:** Single responsibility per module? Interfaces well-defined? Consistent with existing codebase? Imports resolve?

**Performance:** N+1 queries? Unbounded collections? Blocking I/O on async? Resource leaks? Missing connection limits?

**Concurrency:** Race conditions? Deadlocks? Proper async/await? Task cancellation? Pool exhaustion?

### 2.4 Severity Calibration

**For plans:**
- 🔴 = references nonexistent module, violates spec guardrail, missing entire feature, impossible task order
- 🟡 = missing edge case (happy path covered), unclear criteria (intent understandable), oversized task
- 🟢 = belongs in later milestone, optimization not needed yet
- 🔵 = wording, formatting

**For code:**
- 🔴 = runtime crash, security vulnerability, spec guardrail violation, test that doesn't verify behavior
- 🟡 = missing error handling for possible failure, untested edge case, design smell, inconsistent with codebase
- 🟢 = optimization, refactoring, deferred feature
- 🔵 = naming, comment, import ordering

### 2.5 Gap Quality Standards

GOOD: "SqliteStore.put() at store.py:45 doesn't handle sqlite3.IntegrityError on duplicate key with different SHA."

BAD: "Error handling could be improved throughout."

**Rule: If you can't name a specific file, line, function, or scenario — it's not a gap. Delete it.**

### 2.6 Anti-Patterns (NEVER flag)

- "Could benefit from more comprehensive testing"
- "Consider adding input validation" (without specifying what input)
- "May have performance implications" (without evidence)
- "Documentation could be enhanced"
- Any gap starting with "Consider..." or "May..." or "Could..."

---

## 3. New production-readiness-review Skill

### 3.1 Artifact Type Detection

Before running checks, detect type by file structure:
- HTTP endpoint files (FastAPI/Flask routes) → **service**
- argparse/click → **CLI**
- Neither → **library**
- Mixed → apply both profiles

### 3.2 Checklists by Profile

**COMMON (all profiles):**

Security:
- No secrets/credentials in source code
- No secrets in log output or stack traces
- All external input validated at system boundaries
- SQL uses parameterized queries (no string formatting)
- File paths sanitized (no traversal)

Error resilience:
- Every external call handles or explicitly propagates errors
- Transient failures use retry with backoff
- Error messages are actionable but don't leak internals

Testing:
- No `time.sleep` in tests (use mocks)
- No network calls in unit tests
- Tests are order-independent
- Assertions verify behavior (not just "doesn't crash")

Code quality:
- No TODO/FIXME/HACK in shipped code
- Follows CLAUDE.md conventions
- Consistent with existing codebase patterns

**SERVICE (additional):**
- Health check endpoint returns dependency status
- Structured logging (JSON/key=value) at error boundaries
- CORS configured for web endpoints
- Rate limiting on public endpoints
- Request/response size limits
- Graceful shutdown (SIGTERM → drain → exit)
- Config validated at startup (fail fast)
- Database migrations are reversible
- API error responses use consistent format
- POST create-endpoints are idempotent
- Connection pool limits configured
- Query timeouts set

**CLI (additional):**
- Exit codes follow convention (0=success, 1=error, 2=usage)
- SIGINT/SIGTERM handled gracefully
- Argument validation with clear error messages
- Environment variables documented in --help or README

### 3.3 Severity

- 🔴 Critical: secret in code, SQL injection, missing auth, no error handling on external call, public endpoint without rate limiting
- 🔴 Architectural: needs infrastructure setup (KMS, vault, CDN) — flag only, don't auto-fix, doesn't block convergence
- 🟡 Important: missing structured logging, missing health check, hardcoded config, no graceful shutdown
- 🟢 Acceptable: missing optimization, missing non-critical docs

### 3.4 Dedup Rule

If a gap was already flagged by a prior skill (check `gap_summaries` for same file:line), don't re-count it. Tag new gaps `[production]`.

### 3.5 Post-Fix Verification

After fixing production issues, re-run the full test suite before writing the gap report. Production fixes (adding try/except, changing control flow) can break existing tests.

---

## 4. Enhanced context.py

### 4.1 New Signature

```python
def build_context_summary(
    completed: list[str],
    project_root: Path,
    current_milestone: dict | None = None,
    milestones: list[dict] | None = None,
) -> str:
```

### 4.2 What It Produces

For M8 (Coordinator) with M1-M7 completed:
```
Completed (7 milestones, 380 tests):
  M1-M4: e2e_agent/{enums,types,events,config,policies,exceptions,
    knowledge/,indexer/,tools/}.py
  M5 (explorer): e2e_agent/explorer/{discovery,flow_builder,ranking}.py
    Exports: Explorer, FlowSpec
  M6 (author): e2e_agent/author/{templates,selectors,session}.py
    Exports: AuthorSession, DraftSpec
  M7 (debugger): e2e_agent/debugger/{classifier,repair,loop}.py
    Exports: Debugger, ClassifiedFailure

For p1-m8-coordinator (depends on M5, M6, M7):
  Explorer -> FlowSpec, Author -> DraftSpec, Debugger -> RunReport
  EventBus from events.py, BudgetConfig from types.py

See CLAUDE.md for full conventions.
```

### 4.3 How It Works (all deterministic)

1. **Test count:** `len(list(tests_dir.rglob("test_*.py")))` — count test files, not commits
2. **Files per milestone:** `git diff --name-only <prev-tag>..<tag>` — fall back to `git log --name-only` if no tag
3. **Key exports:** Read `__init__.py`, extract import names. If empty, scan module files for `class`/`def` definitions
4. **Dependency detail:** Read current milestone's `depends_on`, expand with module paths + key exports
5. **Priority ordering:** Dependencies > recent (last 3) > older (1 line each)
6. **Cap:** 400 words, truncate oldest milestones first
7. **Error handling:** Each section (files, exports, tests) wrapped independently — partial results OK
8. **Paths:** Normalized to forward slashes (cross-platform)

### 4.4 Orchestrator Integration

- `build_context_summary` called with full parameters from `orchestrator._run_milestone()`
- Re-generated BEFORE Phase C (to include what Phase B built)

---

## 5. Enhanced Prompts

### 5.1 Phase A (Plan + Ultrathink)

Added before step 1:
```
Before writing the plan:
- Read CLAUDE.md for project conventions and module map
- Read the __init__.py and main module of each dependency listed in the context
- Understand the interfaces you will build against
```

### 5.2 Phase B (Implementation)

Added one line:
```
Write code with production deployment in mind: structured logging, error handling,
input validation at boundaries.
```

Clarification: "TDD first. After tests pass, add production concerns as a refactoring step within the same task."

### 5.3 Phase C (Review + Fix)

Restructured:
```
1. Run post-impl-review (correctness + tests)
2. Then run production-readiness-review (security + deployment + observability)
3. Fix post-impl issues first (correctness), then production issues (hardening)
4. Re-run full test suite after all fixes
5. Commit fixes. Tag each gap [post-impl] or [production] in gap_summaries
6. Write .claude/.gap-report.json
```

### 5.4 Gap Report Schema (updated)

```json
{
  "pass": 2,
  "critical_gaps": 0,
  "architectural_gaps": 1,
  "important_gaps": 0,
  "minor_gaps": 3,
  "deferred_gaps": 2,
  "total_gaps_found": 6,
  "gaps_fixed_this_pass": 4,
  "tests_green": true,
  "lint_clean": true,
  "converged": true,
  "gap_summaries": [
    "[post-impl] SqliteStore.put at store.py:45 missing IntegrityError handling",
    "[production] No structured logging in coordinator error path"
  ]
}
```

---

## 6. Enhanced post-impl-review Skill

### 6.1 New Sub-Steps

**3.5 Test assertion quality:**
- Weak (flag): `assert True`, `assert result`, `assert x is not None`, `assert len(x)`
- Strong (pass): `assert result == expected_value`, `assert x.name == "foo"`

**3.6 Cross-module consistency:**
- Same exception hierarchy (project-specific base exception subclasses)
- Same import ordering (ruff-enforced but verify)
- Same test structure (matching existing pattern — function-based or class-based)

**3.7 Full test suite:**
- Run ALL tests, not just for changed files
- Flag regressions in existing tests

**3.8 Package hygiene:**
- `__init__.py` exports public API only — no internal implementation details
- No circular imports — test: `python -c "import package_name"`
- All pyproject.toml dependencies actually imported somewhere
- Type hints on all public function signatures (exception: decorators/metaclasses)

**3.9 Commit strategy:**
- Single commit unless >10 files changed
- If >10 files: group by category (security, observability, tests)

---

## 7. Appendix

### 7.1 Design Validation

- **Pass 1:** 20 gaps (ultrathink skill heuristics, severity, anti-padding, production checks)
- **Pass 2:** 22 gaps (production skill profiles, artifact detection, severity, checklist gaps)
- **Pass 3:** 20 gaps (context git fallbacks, prompt specificity, test assertions, package hygiene)
- **Pass 4:** 20 gaps (cross-component integration, dedup, skill size, context refresh, backward compat)
- **Total: 82 gaps** — all critical and important resolved in design

### 7.2 Files Changed

| File | Change type |
|---|---|
| `skills/ultrathink-gap-analysis/SKILL.md` | Rewrite (split to SKILL.md + references/) |
| `skills/ultrathink-gap-analysis/references/heuristics.md` | New |
| `skills/production-readiness-review/SKILL.md` | New |
| `skills/post-impl-review/SKILL.md` | Enhanced (add sub-steps 3.5-3.9) |
| `src/superpower_workflow/context.py` | Rewrite (git-based, ~120 lines) |
| `src/superpower_workflow/prompts.py` | Edit (Phase A/B/C enhancements) |
| `src/superpower_workflow/orchestrator.py` | Edit (pass milestone data to context, refresh before Phase C) |
| `tests/test_context.py` | Rewrite (new parameters, new assertions) |
| `tests/test_prompts.py` | Update (verify new prompt content) |
| `install.py` | Update (add production-readiness-review to COPIES) |
