# Trust-But-Verify System — Design Spec

**Date:** 2026-05-26
**Spec version:** 1.0
**Status:** Approved for implementation
**Goal:** Code-enforced gap validation + independent spec compliance + feature verification. Transform the quality loop from "trust Claude" to "trust but verify."

> Validated through ultrathink (25 gaps found, all resolved).

---

## 1. Overview

Three NEW verification layers added to the existing pipeline:

| Layer | Type | What it catches | Cost |
|---|---|---|---|
| **Gap Validator** | Code-enforced (Python) | Hallucinated file:line, fake symbols, duplicate padding | $0 (local) |
| **Spec Compliance Checker** | Independent claude -p | Missing features, spec drift after implementation | ~$2-3/milestone |
| **Feature Verification Tester** | Independent claude -p + runs code | Features that exist but don't work (integration bugs) | ~$3-5/milestone |

These complement the existing superpowers per-task review (first line of defense). Our layers are the SECOND and THIRD lines — catching cross-task and cross-milestone issues.

---

## 2. Revised Milestone Flow

```
Phase A: Plan + Ultrathink
  → Gap Validator verifies gaps (in convergence hook)
  → Convergence decision on VALIDATED gaps
  ↓
Phase B: Implement (subagent-driven-dev with per-task review)
  ↓
Quality Gates Checkpoint #1
  ↓
Spec Compliance Check (independent claude -p)        ← NEW
  → Reads original spec + all implemented code
  → Reports: implemented vs missing requirements
  ↓
Feature Verification (independent claude -p + runs)   ← NEW
  → Generates + runs verification tests for spec features
  → Reports: working vs broken features
  ↓
Phase C: Review + Fix (receives compliance + verification reports)
  → Gap Validator verifies review gaps (in convergence hook)
  → Convergence decision on VALIDATED gaps
  ↓
Quality Gates Checkpoint #2
  ↓
Phase D: Push
```

---

## 3. Gap Validator

### 3.1 Where it runs

Inside the convergence hook (`convergence_gate.py`), AFTER reading `.gap-report.json` and BEFORE making the convergence decision.

### 3.2 What it checks

For each gap in `gap_summaries`:

1. **File reference extraction** — regex for `filename.py:N`, `filename.py line N`, or just `filename.py`. Flexible parsing for free-form text.
2. **File existence** — verify the referenced file exists relative to project root
3. **Line range** — verify the line number is within the file's actual line count
4. **Symbol existence** — extract function/class names, grep the codebase
5. **Duplicate detection** — fuzzy-match against OTHER gaps in the SAME pass. >50% similarity within one pass = padding
6. **Tool cross-check** — if gap mentions lint/test/coverage, check cached quality gate results (`.claude/.quality-gate-results.json`)

### 3.3 Gap states

Three states per gap:
- **valid** — file:line exists, symbol found, no duplicate. Confidence 0.8-1.0
- **invalid** — file doesn't exist, line out of range, symbol not found. Confidence 0.0-0.3
- **unverifiable** — no file reference in gap text (e.g., "the architecture could be cleaner"). Accepted (benefit of the doubt). Confidence 0.5

### 3.4 Output

`.claude/.gap-validation.json`:
```json
{
  "total_gaps": 20,
  "valid_gaps": 15,
  "invalid_gaps": 3,
  "unverifiable_gaps": 2,
  "duplicate_gaps": 1,
  "validations": [
    {
      "gap": "[ultrathink] Store.put at store.py:45...",
      "state": "valid",
      "confidence": 0.95,
      "checks": {"file_exists": true, "line_in_range": true, "symbol_found": true}
    },
    {
      "gap": "[ultrathink] FooBarBaz not tested",
      "state": "invalid",
      "confidence": 0.1,
      "checks": {"symbol_found": false},
      "reason": "FooBarBaz not found in codebase"
    }
  ]
}
```

### 3.5 Convergence hook integration

After reading gap report, validator runs. In **lenient** mode (default): invalid gaps are logged as warnings, counts unchanged. In **strict** mode: invalid gaps subtracted from counts. Configurable via `validation.gap_validation_mode` in workflow.json.

### 3.6 Performance

20 gaps × (file check + line check + grep) = ~60 filesystem ops. <100ms on SSD. Acceptable for a hook.

Tool cross-check reads cached `.quality-gate-results.json` (written by quality gates checkpoint). No tool re-execution.

### 3.7 Telemetry

New event: `GapValidation(total, valid, invalid, unverifiable, duplicate)` emitted after each convergence check.

---

## 4. Spec Compliance Checker

### 4.1 Where it runs

After Quality Gates Checkpoint #1 (post-Phase-B), before Feature Verification. Orchestrator invokes `run_claude` with a compliance-checking prompt.

### 4.2 What it does

One `claude -p` call with:
```
Read the spec at {spec_path}, focusing on sections {spec_sections}.
Read all files in {module_dir}/ and tests/.
For each requirement in the spec:
  1. Search the codebase for its implementation
  2. Rate: "implemented" (with file:function evidence) or "missing"
Write .claude/.spec-compliance.json with the results.
```

### 4.3 Output

`.claude/.spec-compliance.json`:
```json
{
  "spec_path": "docs/superpowers/specs/spec.md",
  "spec_sections": "4, 5, 6",
  "total_requirements": 15,
  "implemented": 13,
  "missing": 2,
  "details": [
    {"requirement": "Division by zero returns clear error", "status": "implemented", "evidence": "operations.py:divide() raises ValueError"},
    {"requirement": "History stats shows most_used_op", "status": "missing", "evidence": "stats() exists but most_used_op not computed"}
  ]
}
```

### 4.4 Integration

If `missing > 0`, the compliance report is included in Phase C's prompt:
```
These spec requirements are missing from the implementation:
- History stats shows most_used_op (stats() exists but most_used_op not computed)
Implement them during this review phase.
```

### 4.5 Cost

~$2-3 per milestone. Budget from `validation.spec_compliance_budget` (default: 3.0).

---

## 5. Feature Verification Tester

### 5.1 Where it runs

After Spec Compliance Check, before Phase C. Orchestrator invokes `run_claude` with a verification prompt.

### 5.2 What it does

One `claude -p` call with:
```
Read .claude/.spec-compliance.json.
For each requirement marked "implemented":
  1. Find an existing test that verifies this feature
  2. If no test exists, write a verification test
  3. Run all verification tests
Report which features pass and which fail.
Write .claude/.feature-verification.json.
Only verify objectively testable features. Mark subjective ones as "manual review needed".
```

### 5.3 Output

`.claude/.feature-verification.json`:
```json
{
  "total_features": 13,
  "verified_working": 11,
  "broken": 1,
  "manual_review": 1,
  "details": [
    {"feature": "Expression parser respects precedence", "status": "pass", "test": "test_parser.py::test_precedence"},
    {"feature": "CLI --history shows last 10", "status": "fail", "test": "test_cli.py::test_history_limit", "reason": "Shows all, not last 10"},
    {"feature": "Clear error messages", "status": "manual_review", "reason": "Subjective — needs human judgment"}
  ]
}
```

### 5.4 Integration

If `broken > 0`, the verification report is included in Phase C's prompt:
```
These features exist but don't work correctly:
- CLI --history shows last 10: FAIL — shows all, not last 10 (test_cli.py::test_history_limit)
Fix them during this review phase.
```

### 5.5 Cost

~$3-5 per milestone. Budget from `validation.feature_verification_budget` (default: 5.0).

---

## 6. Configuration

New optional `validation` section in workflow.json:

```json
{
  "validation": {
    "gap_validator": true,
    "gap_validation_mode": "lenient",
    "spec_compliance": true,
    "feature_verification": true,
    "spec_compliance_budget": 3.0,
    "feature_verification_budget": 5.0
  }
}
```

All fields optional. Missing section = validation disabled (backward compatible). Each check independently toggleable.

---

## 7. State & Resume

New `current_step` values:
```
"spec_compliance" — between quality gates #1 and feature verification
"feature_verify"  — between spec compliance and Phase C
```

Resume from `spec_compliance` → re-run compliance check (not Phase B).
Resume from `feature_verify` → re-run feature verification (not compliance).

---

## 8. Files to Create/Modify

| Action | File |
|---|---|
| Create | `src/superpower_workflow/validation/__init__.py` |
| Create | `src/superpower_workflow/validation/gap_validator.py` |
| Create | `src/superpower_workflow/validation/spec_compliance.py` |
| Create | `src/superpower_workflow/validation/feature_tester.py` |
| Modify | `src/superpower_workflow/hooks/convergence_gate.py` (call gap validator) |
| Modify | `src/superpower_workflow/orchestrator.py` (add compliance + verification steps, new state values) |
| Modify | `src/superpower_workflow/prompts.py` (Phase C receives compliance + verification reports) |
| Modify | `src/superpower_workflow/cli.py` (validation config in sw init defaults) |
| Create | `tests/test_gap_validator.py` |
| Create | `tests/test_spec_compliance.py` |
| Create | `tests/test_feature_tester.py` |

---

## 9. Appendix

### Design Validation
- 25 gaps found via ultrathink: hook performance, free-form parsing, self-review problem, compliance acting upon, resume states, validation states (valid/invalid/unverifiable), cost impact, tool cache reuse, telemetry events
- All critical and important gaps resolved in design
- Existing superpowers per-task review is FIRST line; our 3 layers are SECOND/THIRD lines (no duplication)
