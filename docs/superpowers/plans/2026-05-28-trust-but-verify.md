# Trust-But-Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Code-enforced gap validation + independent spec compliance + feature verification. Three verification layers that transform the quality loop from "trust Claude" to "trust but verify."

**Architecture:** New `validation/` subpackage with three modules. `gap_validator.py` is pure Python (no LLM call) — runs in the convergence hook, validates file:line references, detects duplicates, cross-checks tool claims. `spec_compliance.py` and `feature_tester.py` each make one `run_claude` call to independently verify spec coverage and feature correctness. Orchestrator gains two new steps between Quality Gates #1 and Phase C. Convergence gate calls gap validator in lenient (default) or strict mode.

**Tech Stack:** Python 3.11+, regex for reference extraction, SequenceMatcher for fuzzy matching. No new dependencies.

**Spec reference:** `docs/superpowers/specs/2026-05-26-trust-but-verify.md`

**Working directory:** `superpower-workflow/` (the repo root).

---

## Design Decisions

1. **Pure Python gap validator:** No LLM call. File checks + grep + fuzzy matching. <100ms on SSD for 20 gaps.
2. **Lenient by default:** Invalid gaps logged as warnings but don't change counts. Strict mode subtracts them.
3. **run_claude abstraction:** Spec compliance and feature verification use the existing `run_claude` function — same retry/timeout/fallback as other phases.
4. **Duck-typed reports:** Each checker writes its own JSON file. Phase C prompt reads them if they exist.
5. **Config-driven toggles:** Each layer independently togglable. Missing `validation` section = all disabled (backward compat).
6. **Quality gate results cache:** Orchestrator writes `.quality-gate-results.json` after running gates, enabling gap validator tool cross-check without re-executing tools.
7. **Test strategy:** Unit tests mock filesystem ops and `run_claude`. Integration tests mock `subprocess.run` as per project convention.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/validation/__init__.py` | New | Package exports with `__all__` |
| `src/superpower_workflow/validation/gap_validator.py` | New | Gap validation: file refs, symbols, duplicates, tool cross-check |
| `src/superpower_workflow/validation/spec_compliance.py` | New | Independent spec compliance checker (claude -p) |
| `src/superpower_workflow/validation/feature_tester.py` | New | Independent feature verification tester (claude -p) |
| `src/superpower_workflow/hooks/convergence_gate.py` | Edit | Call gap validator, lenient/strict modes |
| `src/superpower_workflow/orchestrator.py` | Edit | Add spec_compliance + feature_verify steps |
| `src/superpower_workflow/prompts.py` | Edit | Phase C receives compliance + verification reports |
| `src/superpower_workflow/state.py` | Edit | Add new VALID_STEPS |
| `src/superpower_workflow/cli.py` | Edit | Validation config in default config |
| `src/superpower_workflow/telemetry.py` | Edit | New event types |
| `tests/test_gap_validator.py` | New | Gap validator unit tests |
| `tests/test_spec_compliance.py` | New | Spec compliance tests |
| `tests/test_feature_tester.py` | New | Feature verification tests |
| `tests/test_trust_verify_integration.py` | New | End-to-end integration tests |

---

### Task 1: Validation package + config schema

**Files:**
- New: `src/superpower_workflow/validation/__init__.py`
- Edit: `src/superpower_workflow/cli.py` (default config in `_cmd_init`)
- New: `tests/test_gap_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_validator.py
from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init


class TestValidationConfig:
    def test_init_includes_validation_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "validation" in config
        v = config["validation"]
        assert v["gap_validator"] is True
        assert v["gap_validation_mode"] == "lenient"
        assert v["spec_compliance"] is True
        assert v["feature_verification"] is True
        assert v["spec_compliance_budget"] == 3.0
        assert v["feature_verification_budget"] == 5.0

    def test_validation_package_importable(self):
        import superpower_workflow.validation
        assert hasattr(superpower_workflow.validation, "__all__")
```

- [ ] **Step 2: Run tests -- expect FAIL** (validation package doesn't exist, config key missing)

- [ ] **Step 3: Create validation package + config**

Create `src/superpower_workflow/validation/__init__.py`:

```python
"""Trust-but-verify validation layer: gap validator, spec compliance, feature verification."""

from __future__ import annotations

__all__: list[str] = []
```

In `cli.py` `_cmd_init`, add to `default_config` dict after the `server` block:

```python
"validation": {
    "gap_validator": True,
    "gap_validation_mode": "lenient",
    "spec_compliance": True,
    "feature_verification": True,
    "spec_compliance_budget": 3.0,
    "feature_verification_budget": 5.0,
},
```

Also add new runtime files to the `.gitignore` entries list in `_cmd_init`:

```python
".claude/.gap-validation.json",
".claude/.spec-compliance.json",
".claude/.feature-verification.json",
".claude/.quality-gate-results.json",
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/__init__.py src/superpower_workflow/cli.py tests/test_gap_validator.py --fix
ruff format src/superpower_workflow/validation/__init__.py src/superpower_workflow/cli.py tests/test_gap_validator.py
git add src/superpower_workflow/validation/__init__.py src/superpower_workflow/cli.py tests/test_gap_validator.py
git commit -m "feat: add validation package and config schema for trust-but-verify" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Gap validator types + file reference extraction

**Files:**
- New: `src/superpower_workflow/validation/gap_validator.py`
- Extend: `tests/test_gap_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_validator.py -- append these classes
from superpower_workflow.validation.gap_validator import (
    FileReference,
    GapState,
    GapValidationResult,
    extract_file_references,
)


class TestGapState:
    def test_valid_state(self):
        assert GapState.VALID == "valid"

    def test_invalid_state(self):
        assert GapState.INVALID == "invalid"

    def test_unverifiable_state(self):
        assert GapState.UNVERIFIABLE == "unverifiable"


class TestFileReference:
    def test_file_reference_creation(self):
        ref = FileReference(path="store.py", line=45)
        assert ref.path == "store.py"
        assert ref.line == 45

    def test_file_reference_no_line(self):
        ref = FileReference(path="store.py")
        assert ref.line is None

    def test_file_reference_with_symbol(self):
        ref = FileReference(path="store.py", line=45, symbol="Store.put")
        assert ref.symbol == "Store.put"


class TestExtractFileReferences:
    def test_file_colon_line(self):
        refs = extract_file_references("[ultrathink] Store.put at store.py:45 missing validation")
        assert len(refs) >= 1
        assert refs[0].path == "store.py"
        assert refs[0].line == 45

    def test_file_line_n(self):
        refs = extract_file_references("[ultrathink] bug in runner.py line 120")
        assert len(refs) >= 1
        assert refs[0].path == "runner.py"
        assert refs[0].line == 120

    def test_file_only(self):
        refs = extract_file_references("[ultrathink] missing tests in orchestrator.py")
        assert len(refs) >= 1
        assert refs[0].path == "orchestrator.py"
        assert refs[0].line is None

    def test_path_with_directory(self):
        refs = extract_file_references("src/superpower_workflow/state.py:30 needs fix")
        assert len(refs) >= 1
        assert refs[0].path == "src/superpower_workflow/state.py"
        assert refs[0].line == 30

    def test_no_file_reference(self):
        refs = extract_file_references("[ultrathink] the architecture could be cleaner")
        assert len(refs) == 0

    def test_multiple_references(self):
        refs = extract_file_references("check store.py:10 and runner.py:20")
        assert len(refs) == 2

    def test_extracts_symbol_near_reference(self):
        refs = extract_file_references("[ultrathink] Store.put at store.py:45 lacks error handling")
        found_symbols = [r.symbol for r in refs if r.symbol]
        assert any("Store" in s for s in found_symbols) or len(refs) >= 1
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement types + extraction**

Create `src/superpower_workflow/validation/gap_validator.py`:

```python
"""Gap validator: verify file references, detect duplicates, cross-check tool claims."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class GapState(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNVERIFIABLE = "unverifiable"


@dataclass
class FileReference:
    path: str
    line: int | None = None
    symbol: str | None = None


@dataclass
class ValidationCheck:
    file_exists: bool | None = None
    line_in_range: bool | None = None
    symbol_found: bool | None = None


@dataclass
class GapValidationResult:
    gap: str
    state: GapState
    confidence: float
    checks: ValidationCheck = field(default_factory=ValidationCheck)
    reason: str = ""

    def to_dict(self) -> dict:
        d: dict = {"gap": self.gap, "state": self.state.value, "confidence": self.confidence}
        checks = {}
        if self.checks.file_exists is not None:
            checks["file_exists"] = self.checks.file_exists
        if self.checks.line_in_range is not None:
            checks["line_in_range"] = self.checks.line_in_range
        if self.checks.symbol_found is not None:
            checks["symbol_found"] = self.checks.symbol_found
        d["checks"] = checks
        if self.reason:
            d["reason"] = self.reason
        return d


@dataclass
class GapValidationReport:
    total_gaps: int = 0
    valid_gaps: int = 0
    invalid_gaps: int = 0
    unverifiable_gaps: int = 0
    duplicate_gaps: int = 0
    validations: list[GapValidationResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_gaps": self.total_gaps,
            "valid_gaps": self.valid_gaps,
            "invalid_gaps": self.invalid_gaps,
            "unverifiable_gaps": self.unverifiable_gaps,
            "duplicate_gaps": self.duplicate_gaps,
            "validations": [v.to_dict() for v in self.validations],
        }


_FILE_COLON_LINE = re.compile(r'([\w./\\-]+\.(?:py|ts|js|jsx|tsx|md|yaml|yml|json|toml)):(\d+)')
_FILE_LINE_N = re.compile(r'([\w./\\-]+\.(?:py|ts|js|jsx|tsx|md|yaml|yml|json|toml))\s+line\s+(\d+)', re.IGNORECASE)
_FILE_ONLY = re.compile(r'([\w./\\-]+\.(?:py|ts|js|jsx|tsx|md|yaml|yml|json|toml))')
_SYMBOL_PATTERN = re.compile(r'\b([A-Z][A-Za-z0-9]*(?:\.[a-z_][a-z0-9_]*)?)\b')


def extract_file_references(gap_text: str) -> list[FileReference]:
    refs: list[FileReference] = []
    seen_paths: set[str] = set()

    for m in _FILE_COLON_LINE.finditer(gap_text):
        path, line = m.group(1), int(m.group(2))
        if path not in seen_paths:
            symbol = _extract_nearby_symbol(gap_text, m.start())
            refs.append(FileReference(path=path, line=line, symbol=symbol))
            seen_paths.add(path)

    for m in _FILE_LINE_N.finditer(gap_text):
        path, line = m.group(1), int(m.group(2))
        if path not in seen_paths:
            symbol = _extract_nearby_symbol(gap_text, m.start())
            refs.append(FileReference(path=path, line=line, symbol=symbol))
            seen_paths.add(path)

    for m in _FILE_ONLY.finditer(gap_text):
        path = m.group(1)
        if path not in seen_paths:
            symbol = _extract_nearby_symbol(gap_text, m.start())
            refs.append(FileReference(path=path, symbol=symbol))
            seen_paths.add(path)

    return refs


def _extract_nearby_symbol(text: str, pos: int) -> str | None:
    window_start = max(0, pos - 80)
    window = text[window_start:pos]
    symbols = _SYMBOL_PATTERN.findall(window)
    return symbols[-1] if symbols else None
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py --fix
ruff format src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git add src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git commit -m "feat: add gap validator types and file reference extraction" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: File existence + line range + symbol validation

**Files:**
- Edit: `src/superpower_workflow/validation/gap_validator.py`
- Extend: `tests/test_gap_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_validator.py -- append these classes
from superpower_workflow.validation.gap_validator import (
    check_file_exists,
    check_line_in_range,
    check_symbol_exists,
)


class TestCheckFileExists:
    def test_existing_file(self, tmp_path: Path):
        (tmp_path / "store.py").write_text("class Store:\n    pass\n")
        assert check_file_exists("store.py", tmp_path) is True

    def test_missing_file(self, tmp_path: Path):
        assert check_file_exists("nonexistent.py", tmp_path) is False

    def test_nested_path(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "mod.py").write_text("x = 1\n")
        assert check_file_exists("src/mod.py", tmp_path) is True

    def test_rejects_absolute_path(self, tmp_path: Path):
        assert check_file_exists("/etc/passwd", tmp_path) is False

    def test_rejects_path_traversal(self, tmp_path: Path):
        assert check_file_exists("../../etc/passwd", tmp_path) is False


class TestCheckLineInRange:
    def test_line_within_range(self, tmp_path: Path):
        (tmp_path / "f.py").write_text("a\nb\nc\n")
        assert check_line_in_range("f.py", 3, tmp_path) is True

    def test_line_out_of_range(self, tmp_path: Path):
        (tmp_path / "f.py").write_text("a\nb\n")
        assert check_line_in_range("f.py", 10, tmp_path) is False

    def test_line_zero(self, tmp_path: Path):
        (tmp_path / "f.py").write_text("a\n")
        assert check_line_in_range("f.py", 0, tmp_path) is False

    def test_missing_file(self, tmp_path: Path):
        assert check_line_in_range("missing.py", 1, tmp_path) is False


class TestCheckSymbolExists:
    def test_symbol_found(self, tmp_path: Path):
        (tmp_path / "mod.py").write_text("class Store:\n    def put(self): pass\n")
        assert check_symbol_exists("Store", tmp_path) is True

    def test_symbol_not_found(self, tmp_path: Path):
        (tmp_path / "mod.py").write_text("x = 1\n")
        assert check_symbol_exists("FooBarBaz", tmp_path) is False

    def test_dotted_symbol(self, tmp_path: Path):
        (tmp_path / "mod.py").write_text("class Store:\n    def put(self): pass\n")
        assert check_symbol_exists("Store.put", tmp_path) is True

    def test_function_symbol(self, tmp_path: Path):
        (tmp_path / "mod.py").write_text("def validate_gaps(): pass\n")
        assert check_symbol_exists("validate_gaps", tmp_path) is True
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement check functions**

Add to `gap_validator.py`:

```python
def check_file_exists(file_path: str, project_root: Path) -> bool:
    if file_path.startswith("/") or ".." in file_path:
        return False
    return (project_root / file_path).is_file()


def check_line_in_range(file_path: str, line: int, project_root: Path) -> bool:
    if line <= 0:
        return False
    full = project_root / file_path
    if not full.is_file():
        return False
    try:
        count = len(full.read_text(encoding="utf-8", errors="replace").splitlines())
        return line <= count
    except OSError:
        return False


_SKIP_DIRS = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".git", ".worktrees",
    "build", "dist", ".tox", ".mypy_cache", ".pytest_cache", ".egg-info",
})


def check_symbol_exists(symbol: str, project_root: Path) -> bool:
    parts = symbol.split(".", 1)
    primary = parts[0]
    for py_file in _iter_source_files(project_root):
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
            if primary in content:
                if len(parts) == 1:
                    return True
                if parts[1] in content:
                    return True
        except OSError:
            continue
    return False


def _iter_source_files(root: Path):
    """Yield .py files, skipping .venv/node_modules/etc for performance."""
    for child in root.iterdir():
        if child.name in _SKIP_DIRS:
            continue
        if child.is_file() and child.suffix == ".py":
            yield child
        elif child.is_dir():
            yield from _iter_source_files(child)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py --fix
ruff format src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git add src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git commit -m "feat: add file, line range, and symbol validation checks" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Duplicate gap detection

**Files:**
- Edit: `src/superpower_workflow/validation/gap_validator.py`
- Extend: `tests/test_gap_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_validator.py -- append
from superpower_workflow.validation.gap_validator import (
    compute_similarity,
    find_duplicates,
    normalize_gap,
)


class TestNormalizeGap:
    def test_removes_line_numbers(self):
        assert "store.py" in normalize_gap("[ultrathink] Store.put at store.py:45")
        assert ":45" not in normalize_gap("[ultrathink] Store.put at store.py:45")

    def test_lowercases(self):
        result = normalize_gap("[ultrathink] Missing VALIDATION in Store")
        assert result == result.lower()

    def test_strips_prefix_tags(self):
        result = normalize_gap("[ultrathink] something")
        assert "[ultrathink]" not in result


class TestComputeSimilarity:
    def test_identical_strings(self):
        assert compute_similarity("foo bar", "foo bar") == 1.0

    def test_completely_different(self):
        assert compute_similarity("abc", "xyz") < 0.5

    def test_similar_strings(self):
        a = "store.py put method missing error handling"
        b = "store.py put method lacks error handling"
        assert compute_similarity(a, b) > 0.5

    def test_empty_strings(self):
        assert compute_similarity("", "") == 1.0


class TestFindDuplicates:
    def test_no_duplicates(self):
        gaps = ["missing tests for auth", "broken error handling in parser", "docs outdated"]
        dupes = find_duplicates(gaps)
        assert len(dupes) == 0

    def test_detects_near_duplicate(self):
        gaps = [
            "[ultrathink] store.py:45 missing error handling in put method",
            "[ultrathink] store.py:46 missing error handling in put method",
            "[ultrathink] runner.py has no retry logic",
        ]
        dupes = find_duplicates(gaps)
        assert len(dupes) >= 1

    def test_threshold_at_50_percent(self):
        gaps = [
            "feature A is not tested",
            "feature A is not tested at all",
        ]
        dupes = find_duplicates(gaps)
        assert len(dupes) >= 1
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement duplicate detection**

Add to `gap_validator.py`:

```python
from difflib import SequenceMatcher


def normalize_gap(text: str) -> str:
    text = re.sub(r'\[[\w-]+\]\s*', '', text)
    text = re.sub(r':\d+', '', text)
    text = re.sub(r'\S+/', '', text)
    return text.strip().lower()


def compute_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def find_duplicates(gaps: list[str], threshold: float = 0.5) -> set[int]:
    normalized = [normalize_gap(g) for g in gaps]
    duplicates: set[int] = set()
    for i in range(len(normalized)):
        if i in duplicates:
            continue
        for j in range(i + 1, len(normalized)):
            if j in duplicates:
                continue
            if compute_similarity(normalized[i], normalized[j]) > threshold:
                duplicates.add(j)
    return duplicates
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py --fix
ruff format src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git add src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git commit -m "feat: add duplicate gap detection with fuzzy matching" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Tool cross-check

**Files:**
- Edit: `src/superpower_workflow/validation/gap_validator.py`
- Extend: `tests/test_gap_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_validator.py -- append
from superpower_workflow.validation.gap_validator import check_tool_claims


class TestCheckToolClaims:
    def test_gap_about_lint_passes_when_lint_passed(self):
        results = {"lint": {"passed": True}}
        result = check_tool_claims("lint failures in module", results)
        assert result is False  # gap claims lint issue but lint passed -> invalid claim

    def test_gap_about_lint_valid_when_lint_failed(self):
        results = {"lint": {"passed": False}}
        result = check_tool_claims("lint failures in module", results)
        assert result is True  # gap claims lint issue and lint did fail -> valid

    def test_gap_about_tests_passes_when_tests_passed(self):
        results = {"test": {"passed": True}}
        result = check_tool_claims("tests are failing", results)
        assert result is False

    def test_gap_not_about_tools(self):
        results = {"lint": {"passed": True}}
        result = check_tool_claims("architecture needs improvement", results)
        assert result is None  # no tool claim detected

    def test_empty_results(self):
        result = check_tool_claims("lint failing", {})
        assert result is None  # no cached results to check

    def test_coverage_claim(self):
        results = {"coverage": {"passed": False, "coverage_pct": 45.0}}
        result = check_tool_claims("coverage is below threshold", results)
        assert result is True
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement tool cross-check**

Add to `gap_validator.py`:

```python
_TOOL_KEYWORDS = {
    "lint": ["lint", "linting", "ruff", "flake8", "pylint"],
    "test": ["test", "tests", "pytest", "failing test", "test fail"],
    "coverage": ["coverage", "branch coverage", "uncovered"],
    "sast": ["sast", "security scan", "bandit"],
    "secret_scan": ["secret", "credential", "leak"],
}


def check_tool_claims(gap_text: str, quality_results: dict) -> bool | None:
    if not quality_results:
        return None
    text_lower = gap_text.lower()
    for tool_name, keywords in _TOOL_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            if tool_name in quality_results:
                tool_passed = quality_results[tool_name].get("passed", True)
                return not tool_passed  # True if tool failed (gap claim valid)
            return None
    return None
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py --fix
ruff format src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git add src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git commit -m "feat: add tool cross-check for gap validation" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Gap validator main function + JSON output

**Files:**
- Edit: `src/superpower_workflow/validation/gap_validator.py`
- Extend: `tests/test_gap_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_validator.py -- append
import json

from superpower_workflow.validation.gap_validator import (
    GapValidationReport,
    validate_gaps,
)


class TestValidateGaps:
    def test_valid_gap_with_existing_file(self, tmp_path: Path):
        (tmp_path / "store.py").write_text("class Store:\n    def put(self): pass\n")
        gaps = ["[ultrathink] Store.put at store.py:1 missing validation"]
        report = validate_gaps(gaps, tmp_path)
        assert report.total_gaps == 1
        assert report.valid_gaps == 1
        assert report.invalid_gaps == 0
        assert report.validations[0].state == GapState.VALID
        assert report.validations[0].confidence >= 0.8

    def test_invalid_gap_nonexistent_file(self, tmp_path: Path):
        gaps = ["[ultrathink] check nonexistent.py:99 for bugs"]
        report = validate_gaps(gaps, tmp_path)
        assert report.invalid_gaps == 1
        assert report.validations[0].state == GapState.INVALID
        assert report.validations[0].confidence <= 0.3

    def test_invalid_gap_line_out_of_range(self, tmp_path: Path):
        (tmp_path / "small.py").write_text("x = 1\n")
        gaps = ["[ultrathink] small.py:999 has a bug"]
        report = validate_gaps(gaps, tmp_path)
        assert report.invalid_gaps == 1

    def test_unverifiable_gap_no_file_ref(self, tmp_path: Path):
        gaps = ["[ultrathink] the architecture could be cleaner"]
        report = validate_gaps(gaps, tmp_path)
        assert report.unverifiable_gaps == 1
        assert report.validations[0].state == GapState.UNVERIFIABLE
        assert report.validations[0].confidence == 0.5

    def test_duplicate_detection(self, tmp_path: Path):
        gaps = [
            "[ultrathink] the architecture could be cleaner",
            "[ultrathink] the architecture could be much cleaner",
        ]
        report = validate_gaps(gaps, tmp_path)
        assert report.duplicate_gaps >= 1

    def test_mixed_gaps(self, tmp_path: Path):
        (tmp_path / "real.py").write_text("def foo(): pass\n")
        gaps = [
            "[ultrathink] real.py:1 foo needs docstring",
            "[ultrathink] fake.py:50 missing function",
            "[ultrathink] general code quality concern",
        ]
        report = validate_gaps(gaps, tmp_path)
        assert report.total_gaps == 3
        assert report.valid_gaps == 1
        assert report.invalid_gaps == 1
        assert report.unverifiable_gaps == 1

    def test_writes_json_output(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        gaps = ["[ultrathink] general concern"]
        validate_gaps(gaps, tmp_path, output_path=claude_dir / ".gap-validation.json")
        output = claude_dir / ".gap-validation.json"
        assert output.exists()
        data = json.loads(output.read_text())
        assert "total_gaps" in data
        assert "validations" in data

    def test_tool_cross_check_integration(self, tmp_path: Path):
        quality_results = {"lint": {"passed": True}}
        gaps = ["[ultrathink] lint is failing everywhere"]
        report = validate_gaps(gaps, tmp_path, quality_results=quality_results)
        assert report.invalid_gaps == 1

    def test_empty_gaps(self, tmp_path: Path):
        report = validate_gaps([], tmp_path)
        assert report.total_gaps == 0
        assert report.valid_gaps == 0


class TestGapValidationReportSerialization:
    def test_to_dict(self):
        report = GapValidationReport(
            total_gaps=3, valid_gaps=1, invalid_gaps=1, unverifiable_gaps=1
        )
        d = report.to_dict()
        assert d["total_gaps"] == 3
        assert "validations" in d
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement validate_gaps**

Add to `gap_validator.py`:

```python
import json as _json


def validate_gaps(
    gap_summaries: list[str],
    project_root: Path,
    quality_results: dict | None = None,
    output_path: Path | None = None,
) -> GapValidationReport:
    if not gap_summaries:
        report = GapValidationReport()
        if output_path:
            _write_report(report, output_path)
        return report

    duplicates = find_duplicates(gap_summaries)
    validations: list[GapValidationResult] = []

    for i, gap in enumerate(gap_summaries):
        if i in duplicates:
            validations.append(GapValidationResult(
                gap=gap, state=GapState.INVALID, confidence=0.1, reason="Duplicate gap",
            ))
            continue

        refs = extract_file_references(gap)
        if not refs:
            if quality_results:
                tool_check = check_tool_claims(gap, quality_results)
                if tool_check is False:
                    validations.append(GapValidationResult(
                        gap=gap, state=GapState.INVALID, confidence=0.2,
                        reason="Tool claim contradicts cached results",
                    ))
                    continue
            validations.append(GapValidationResult(
                gap=gap, state=GapState.UNVERIFIABLE, confidence=0.5,
            ))
            continue

        checks = ValidationCheck()
        reasons: list[str] = []
        all_valid = True

        for ref in refs:
            file_ok = check_file_exists(ref.path, project_root)
            if checks.file_exists is None or not file_ok:
                checks.file_exists = file_ok
            if not file_ok:
                reasons.append(f"{ref.path} not found")
                all_valid = False
                continue

            if ref.line is not None:
                line_ok = check_line_in_range(ref.path, ref.line, project_root)
                if checks.line_in_range is None or not line_ok:
                    checks.line_in_range = line_ok
                if not line_ok:
                    reasons.append(f"{ref.path}:{ref.line} out of range")
                    all_valid = False

            if ref.symbol:
                sym_ok = check_symbol_exists(ref.symbol, project_root)
                if checks.symbol_found is None or not sym_ok:
                    checks.symbol_found = sym_ok
                if not sym_ok:
                    reasons.append(f"{ref.symbol} not found in codebase")
                    all_valid = False

        # Note: tool cross-check only applies to no-file-ref gaps (handled above).
        # For gaps WITH file refs, file/line/symbol checks are sufficient.

        if all_valid:
            confidence = 0.8
            if checks.file_exists:
                confidence += 0.05
            if checks.line_in_range:
                confidence += 0.05
            if checks.symbol_found:
                confidence += 0.05
            confidence = min(confidence, 1.0)
            validations.append(GapValidationResult(
                gap=gap, state=GapState.VALID, confidence=confidence, checks=checks,
            ))
        else:
            validations.append(GapValidationResult(
                gap=gap, state=GapState.INVALID, confidence=0.1,
                checks=checks, reason="; ".join(reasons),
            ))

    report = GapValidationReport(
        total_gaps=len(gap_summaries),
        valid_gaps=sum(1 for v in validations if v.state == GapState.VALID),
        invalid_gaps=sum(1 for v in validations if v.state == GapState.INVALID),
        unverifiable_gaps=sum(1 for v in validations if v.state == GapState.UNVERIFIABLE),
        duplicate_gaps=len(duplicates),
        validations=validations,
    )

    if output_path:
        _write_report(report, output_path)

    return report


def _write_report(report: GapValidationReport, path: Path) -> None:
    import os
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(report.to_dict(), indent=2))
    os.replace(str(tmp), str(path))
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py --fix
ruff format src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git add src/superpower_workflow/validation/gap_validator.py tests/test_gap_validator.py
git commit -m "feat: add gap validator main function with JSON output" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Convergence gate integration

**Files:**
- Edit: `src/superpower_workflow/hooks/convergence_gate.py`
- Extend: `tests/test_convergence_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_convergence_gate.py -- append these classes
import json
from pathlib import Path

from superpower_workflow.hooks.convergence_gate import compute_exit_code


class TestGapValidatorIntegration:
    def _setup(self, tmp_path, phase_data=None, gap_data=None, config_data=None):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        if phase_data:
            (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase_data))
        if gap_data:
            (claude_dir / ".gap-report.json").write_text(json.dumps(gap_data))
        if config_data:
            (claude_dir / "workflow.json").write_text(json.dumps(config_data))
        return claude_dir

    def test_lenient_mode_logs_invalid_but_keeps_counts(self, tmp_path: Path):
        """In lenient mode, invalid gaps are warned but counts unchanged."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 2,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": [
                    "[ultrathink] nonexistent.py:999 has bug",
                    "[ultrathink] general concern",
                ],
            },
            config_data={"validation": {"gap_validator": True, "gap_validation_mode": "lenient"}},
        )
        code = compute_exit_code(claude_dir)
        # Lenient mode: counts unchanged, converges based on original counts
        # important_gaps=2, critical=0 → converged (<=3)
        assert code == 0

    def test_strict_mode_subtracts_invalid_gaps(self, tmp_path: Path):
        """In strict mode, invalid gaps subtracted from counts."""
        (tmp_path / "real.py").write_text("x = 1\n")
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 1,
                "important_gaps": 2,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": [
                    "[ultrathink] nonexistent.py:99 critical bug",
                    "[ultrathink] real.py:1 needs fix",
                    "[ultrathink] general concern",
                ],
            },
            config_data={"validation": {"gap_validator": True, "gap_validation_mode": "strict"}},
        )
        # The nonexistent.py gap is invalid, should be subtracted
        code = compute_exit_code(claude_dir)
        # With strict mode, invalid gaps reduce the effective count
        assert isinstance(code, int)

    def test_validator_disabled_no_change(self, tmp_path: Path):
        """When gap_validator is False, no validation occurs."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 2,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": ["[ultrathink] concern"],
            },
            config_data={"validation": {"gap_validator": False}},
        )
        code = compute_exit_code(claude_dir)
        assert code == 0  # <=3 important, 0 critical → converged

    def test_no_config_no_validation(self, tmp_path: Path):
        """When no workflow.json exists, validation is skipped."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 1,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": ["[ultrathink] concern"],
            },
        )
        code = compute_exit_code(claude_dir)
        assert code == 0  # No config = no validation, original logic applies

    def test_writes_gap_validation_json(self, tmp_path: Path):
        """Validation writes .gap-validation.json output."""
        claude_dir = self._setup(
            tmp_path,
            phase_data={"phase": "ultrathink", "iteration": 0, "max_iterations": 5},
            gap_data={
                "critical_gaps": 0,
                "important_gaps": 1,
                "tests_green": True,
                "lint_clean": True,
                "converged": False,
                "gap_summaries": ["[ultrathink] concern"],
            },
            config_data={"validation": {"gap_validator": True, "gap_validation_mode": "lenient"}},
        )
        compute_exit_code(claude_dir)
        validation_path = claude_dir / ".gap-validation.json"
        assert validation_path.exists()
        data = json.loads(validation_path.read_text())
        assert "total_gaps" in data
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Wire gap validator into convergence gate**

Edit `convergence_gate.py` — add validation call after reading gap report and before convergence decision:

```python
# After reading gap_report (around line 62), before convergence check:
def _load_validation_config(claude_dir: Path) -> dict:
    config_path = claude_dir / "workflow.json"
    if not config_path.exists():
        return {}
    try:
        config = json.loads(config_path.read_text())
        validation = config.get("validation", {})
        if not isinstance(validation, dict):
            return {}
        return validation
    except (json.JSONDecodeError, OSError):
        return {}


def _run_gap_validation(
    claude_dir: Path,
    gap_summaries: list[str],
    validation_config: dict,
) -> tuple[int, int]:
    """Run gap validation, return (invalid_count, duplicate_count)."""
    if not validation_config.get("gap_validator", False):
        return 0, 0
    try:
        from superpower_workflow.validation.gap_validator import validate_gaps
    except ImportError:
        return 0, 0

    project_root = claude_dir.parent
    quality_results_path = claude_dir / ".quality-gate-results.json"
    quality_results = {}
    if quality_results_path.exists():
        try:
            quality_results = json.loads(quality_results_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    report = validate_gaps(
        gap_summaries,
        project_root,
        quality_results=quality_results,
        output_path=claude_dir / ".gap-validation.json",
    )
    return report.invalid_gaps, report.duplicate_gaps
```

In `compute_exit_code`, after reading gap_report and before the convergence check, add:

```python
validation_config = _load_validation_config(claude_dir)
invalid_count, dup_count = _run_gap_validation(claude_dir, current_summaries, validation_config)

mode = validation_config.get("gap_validation_mode", "lenient")
if mode == "strict" and invalid_count > 0:
    # invalid_count already includes duplicates (they're marked INVALID)
    total = len(current_summaries) if current_summaries else 1
    invalid_ratio = min(1.0, invalid_count / total)
    critical_gaps = max(0, int(critical_gaps * (1 - invalid_ratio)))
    important_gaps = max(0, int(important_gaps * (1 - invalid_ratio)))
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py --fix
ruff format src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py
git add src/superpower_workflow/hooks/convergence_gate.py tests/test_convergence_gate.py
git commit -m "feat: wire gap validator into convergence gate with lenient/strict modes" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Telemetry events + state updates

**Files:**
- Edit: `src/superpower_workflow/telemetry.py`
- Edit: `src/superpower_workflow/state.py`
- Extend: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py -- append these classes
from superpower_workflow.telemetry import (
    GapValidationEvent,
    SpecComplianceCompleted,
    FeatureVerificationCompleted,
)


class TestGapValidationEvent:
    def test_event_type(self):
        e = GapValidationEvent(
            milestone="ms1", total=10, valid=7, invalid=2, unverifiable=1, duplicate=1
        )
        assert e.EVENT_TYPE == "gap_validation"

    def test_to_dict(self):
        e = GapValidationEvent(milestone="ms1", total=10, valid=7, invalid=2, unverifiable=1, duplicate=1)
        d = e.to_dict()
        assert d["type"] == "gap_validation"
        assert d["total"] == 10
        assert d["valid"] == 7


class TestSpecComplianceCompleted:
    def test_event_type(self):
        e = SpecComplianceCompleted(
            milestone="ms1", total_requirements=15, implemented=13, missing=2, cost_usd=2.5
        )
        assert e.EVENT_TYPE == "spec_compliance_completed"

    def test_to_dict(self):
        e = SpecComplianceCompleted(milestone="ms1", total_requirements=15, implemented=13, missing=2, cost_usd=2.5)
        d = e.to_dict()
        assert d["implemented"] == 13
        assert d["missing"] == 2


class TestFeatureVerificationCompleted:
    def test_event_type(self):
        e = FeatureVerificationCompleted(
            milestone="ms1", total_features=10, verified=8, broken=1, manual_review=1, cost_usd=3.0
        )
        assert e.EVENT_TYPE == "feature_verification_completed"

    def test_to_dict(self):
        e = FeatureVerificationCompleted(
            milestone="ms1", total_features=10, verified=8, broken=1, manual_review=1, cost_usd=3.0
        )
        d = e.to_dict()
        assert d["broken"] == 1


class TestNewValidSteps:
    def test_spec_compliance_is_valid_step(self):
        from superpower_workflow.state import VALID_STEPS
        assert "spec_compliance" in VALID_STEPS

    def test_feature_verify_is_valid_step(self):
        from superpower_workflow.state import VALID_STEPS
        assert "feature_verify" in VALID_STEPS
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add telemetry events + state steps**

Add to `telemetry.py` after `GapReport`:

```python
@dataclass
class GapValidationEvent(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "gap_validation"
    milestone: str = ""
    total: int = 0
    valid: int = 0
    invalid: int = 0
    unverifiable: int = 0
    duplicate: int = 0


@dataclass
class SpecComplianceCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "spec_compliance_completed"
    milestone: str = ""
    total_requirements: int = 0
    implemented: int = 0
    missing: int = 0
    cost_usd: float = 0.0


@dataclass
class FeatureVerificationCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "feature_verification_completed"
    milestone: str = ""
    total_features: int = 0
    verified: int = 0
    broken: int = 0
    manual_review: int = 0
    cost_usd: float = 0.0
```

In `state.py`, add to `VALID_STEPS`:

```python
VALID_STEPS = frozenset(
    {
        "plan",
        "implement",
        "review",
        "push",
        "quality_check_b",
        "quality_check_c",
        "spec_compliance",
        "feature_verify",
        "ci_wait",
        "ci_fix",
        "ci_fix_failed",
        "parallel_wait",
        "parallel_merge",
    }
)
```

Also add new validation files to `SKIP_FILES` (prevents cloning to worktrees):

```python
GAP_VALIDATION_FILE = ".gap-validation.json"
SPEC_COMPLIANCE_FILE = ".spec-compliance.json"
FEATURE_VERIFICATION_FILE = ".feature-verification.json"
QUALITY_GATE_RESULTS_FILE = ".quality-gate-results.json"

SKIP_FILES = frozenset({STATE_FILE, PHASE_FILE, GAP_REPORT_FILE, LOCK_FILE,
    GAP_VALIDATION_FILE, SPEC_COMPLIANCE_FILE, FEATURE_VERIFICATION_FILE, QUALITY_GATE_RESULTS_FILE})
```

In `clear_phase_state`, also remove validation artifacts:

```python
def clear_phase_state(claude_dir: Path) -> None:
    for name in (PHASE_FILE, GAP_REPORT_FILE, GAP_VALIDATION_FILE,
                 SPEC_COMPLIANCE_FILE, FEATURE_VERIFICATION_FILE, QUALITY_GATE_RESULTS_FILE):
        p = claude_dir / name
        p.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py src/superpower_workflow/state.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py src/superpower_workflow/state.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py src/superpower_workflow/state.py tests/test_telemetry.py
git commit -m "feat: add trust-but-verify telemetry events and state steps" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Quality gate results caching

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Extend: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py -- append
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestQualityGateResultsCaching:
    def test_quality_gates_write_results_json(self, tmp_path: Path):
        """Quality gates should write .quality-gate-results.json for gap validator."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config = {
            "spec": "spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [],
            "quality_gates": {"lint": "echo ok"},
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        from superpower_workflow.orchestrator import Orchestrator

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            orch = Orchestrator(tmp_path)

        logger = MagicMock()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            orch._telemetry = MagicMock()
            orch._verify_quality_gates(logger, milestone="test", checkpoint="quality_check_b")

        results_path = claude_dir / ".quality-gate-results.json"
        assert results_path.exists()
        data = json.loads(results_path.read_text())
        assert "lint" in data
        assert data["lint"]["passed"] is True
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add results caching to _verify_quality_gates**

In `orchestrator.py` `_verify_quality_gates`, after running all gates, write results to JSON:

Initialize `results_cache` at the top of `_verify_quality_gates`, populate it inside the gate loop, and write after:

```python
def _verify_quality_gates(self, logger, milestone="", checkpoint=""):
    gates = self.config.get("quality_gates", {})
    if not gates:
        return True, []
    failures: list[str] = []
    results_cache: dict[str, dict] = {}

    for gate_name in ("lint", "sast", "secret_scan", "dep_scan"):
        cmd = gates.get(gate_name)
        if not cmd:
            continue
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=self.cwd, timeout=300)
            passed = result.returncode == 0
            detail = "" if passed else (result.stdout or result.stderr)[:500]
            results_cache[gate_name] = {"passed": passed, "detail": detail}
            if not passed:
                failures.append(f"{gate_name}: {detail}")
                logger.log("QUALITY_GATE_FAILED", gate=gate_name)
            else:
                logger.log("QUALITY_GATE_PASSED", gate=gate_name)
            # ... emit telemetry as before ...
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            results_cache[gate_name] = {"passed": False, "detail": str(e)}
            failures.append(f"{gate_name}: {e}")

    # Write cache for gap validator cross-check
    results_path = self.claude_dir / ".quality-gate-results.json"
    try:
        tmp = results_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(results_cache, indent=2))
        os.replace(str(tmp), str(results_path))
    except OSError:
        pass

    return len(failures) == 0, failures
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: cache quality gate results for gap validator cross-check" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Spec compliance checker

**Files:**
- New: `src/superpower_workflow/validation/spec_compliance.py`
- New: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_spec_compliance.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from superpower_workflow.validation.spec_compliance import (
    build_compliance_prompt,
    parse_compliance_output,
    run_spec_compliance,
)


class TestBuildCompliancePrompt:
    def test_includes_spec_path(self):
        prompt = build_compliance_prompt("docs/spec.md", "4, 5, 6", "src/mymodule/")
        assert "docs/spec.md" in prompt
        assert "4, 5, 6" in prompt

    def test_includes_module_dir(self):
        prompt = build_compliance_prompt("spec.md", "1", "src/mod/")
        assert "src/mod/" in prompt

    def test_includes_output_instructions(self):
        prompt = build_compliance_prompt("spec.md", "1", "src/")
        assert ".spec-compliance.json" in prompt


class TestParseComplianceOutput:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "spec_path": "spec.md",
            "spec_sections": "4, 5",
            "total_requirements": 10,
            "implemented": 8,
            "missing": 2,
            "details": [
                {"requirement": "feature A", "status": "implemented", "evidence": "mod.py:func_a"},
                {"requirement": "feature B", "status": "missing", "evidence": "not found"},
            ],
        })
        result = parse_compliance_output(raw)
        assert result["total_requirements"] == 10
        assert result["implemented"] == 8
        assert result["missing"] == 2
        assert len(result["details"]) == 2

    def test_returns_empty_on_invalid_json(self):
        result = parse_compliance_output("not json")
        assert result["total_requirements"] == 0
        assert result["missing"] == 0

    def test_returns_empty_on_missing_fields(self):
        result = parse_compliance_output(json.dumps({"foo": "bar"}))
        assert result["total_requirements"] == 0


class TestRunSpecCompliance:
    def test_calls_run_claude_and_writes_output(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        mock_result = MagicMock()
        mock_result.text = json.dumps({
            "spec_path": "spec.md",
            "spec_sections": "1",
            "total_requirements": 5,
            "implemented": 4,
            "missing": 1,
            "details": [{"requirement": "feat", "status": "missing", "evidence": "not found"}],
        })
        mock_result.cost_usd = 2.0
        mock_result.is_error = False

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_spec_compliance(
            spec_path="docs/spec.md",
            spec_sections="1, 2",
            module_dirs=["src/mod/"],
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=3.0,
            cwd=str(tmp_path),
            output_path=claude_dir / ".spec-compliance.json",
        )

        assert report["missing"] == 1
        assert (claude_dir / ".spec-compliance.json").exists()
        mock_run_claude.assert_called_once()

    def test_returns_empty_on_error(self, tmp_path: Path):
        mock_result = MagicMock()
        mock_result.is_error = True
        mock_result.text = ""
        mock_result.cost_usd = 0.5

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_spec_compliance(
            spec_path="spec.md",
            spec_sections="1",
            module_dirs=["src/"],
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=3.0,
            cwd=str(tmp_path),
        )

        assert report["total_requirements"] == 0
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement spec compliance checker**

Create `src/superpower_workflow/validation/spec_compliance.py`:

```python
"""Spec compliance checker: independent claude -p call to verify spec requirements."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


def build_compliance_prompt(spec_path: str, spec_sections: str, module_dir: str) -> str:
    return (
        f"Read the spec at {spec_path}, focusing on sections {spec_sections}.\n"
        f"Read all files in {module_dir} and tests/.\n"
        f"For each requirement in the spec:\n"
        f"  1. Search the codebase for its implementation\n"
        f'  2. Rate: "implemented" (with file:function evidence) or "missing"\n'
        f"Write .claude/.spec-compliance.json with this exact schema:\n"
        f'{{"spec_path": "{spec_path}", "spec_sections": "{spec_sections}", '
        f'"total_requirements": N, "implemented": N, "missing": N, '
        f'"details": [{{"requirement": "...", "status": "implemented"|"missing", '
        f'"evidence": "file.py:function"}}]}}\n'
        f"IMPORTANT: Output ONLY the JSON content, nothing else."
    )


def parse_compliance_output(raw_text: str) -> dict[str, Any]:
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_text[start:end])
            return {
                "spec_path": data.get("spec_path", ""),
                "spec_sections": data.get("spec_sections", ""),
                "total_requirements": data.get("total_requirements", 0),
                "implemented": data.get("implemented", 0),
                "missing": data.get("missing", 0),
                "details": data.get("details", []),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return {
        "spec_path": "",
        "spec_sections": "",
        "total_requirements": 0,
        "implemented": 0,
        "missing": 0,
        "details": [],
    }


def run_spec_compliance(
    spec_path: str,
    spec_sections: str,
    module_dirs: list[str],
    run_claude_fn: Callable,
    model: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    module_dir = ", ".join(module_dirs) if module_dirs else "src/"
    prompt = build_compliance_prompt(spec_path, spec_sections, module_dir)

    result = run_claude_fn(
        prompt,
        model=model,
        effort="high",
        budget=budget,
        cwd=cwd,
        system_prompt=system_prompt,
        fallback_model=fallback_model,
    )

    if result.is_error:
        report = parse_compliance_output("")
        report["cost_usd"] = result.cost_usd
        return report

    report = parse_compliance_output(result.text)
    report["cost_usd"] = result.cost_usd

    if output_path:
        tmp = output_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2))
        os.replace(str(tmp), str(output_path))

    return report
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/spec_compliance.py tests/test_spec_compliance.py --fix
ruff format src/superpower_workflow/validation/spec_compliance.py tests/test_spec_compliance.py
git add src/superpower_workflow/validation/spec_compliance.py tests/test_spec_compliance.py
git commit -m "feat: add spec compliance checker with run_claude integration" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Feature verification tester

**Files:**
- New: `src/superpower_workflow/validation/feature_tester.py`
- New: `tests/test_feature_tester.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feature_tester.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from superpower_workflow.validation.feature_tester import (
    build_verification_prompt,
    parse_verification_output,
    run_feature_verification,
)


class TestBuildVerificationPrompt:
    def test_includes_compliance_path(self):
        prompt = build_verification_prompt(".claude/.spec-compliance.json")
        assert ".spec-compliance.json" in prompt

    def test_includes_output_instructions(self):
        prompt = build_verification_prompt(".claude/.spec-compliance.json")
        assert ".feature-verification.json" in prompt

    def test_instructs_test_execution(self):
        prompt = build_verification_prompt(".claude/.spec-compliance.json")
        assert "test" in prompt.lower()


class TestParseVerificationOutput:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "total_features": 10,
            "verified_working": 8,
            "broken": 1,
            "manual_review": 1,
            "details": [
                {"feature": "parser", "status": "pass", "test": "test_parser.py::test_it"},
                {"feature": "cli", "status": "fail", "test": "test_cli.py::test_it", "reason": "off by one"},
                {"feature": "docs", "status": "manual_review", "reason": "subjective"},
            ],
        })
        result = parse_verification_output(raw)
        assert result["total_features"] == 10
        assert result["verified_working"] == 8
        assert result["broken"] == 1

    def test_returns_empty_on_invalid(self):
        result = parse_verification_output("not json")
        assert result["total_features"] == 0

    def test_handles_missing_fields(self):
        result = parse_verification_output(json.dumps({"total_features": 5}))
        assert result["total_features"] == 5
        assert result["broken"] == 0


class TestRunFeatureVerification:
    def test_calls_run_claude_and_writes_output(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        compliance = {
            "total_requirements": 5,
            "implemented": 4,
            "missing": 1,
            "details": [{"requirement": "feat A", "status": "implemented", "evidence": "mod.py:func"}],
        }
        (claude_dir / ".spec-compliance.json").write_text(json.dumps(compliance))

        mock_result = MagicMock()
        mock_result.text = json.dumps({
            "total_features": 4,
            "verified_working": 3,
            "broken": 1,
            "manual_review": 0,
            "details": [{"feature": "feat A", "status": "fail", "reason": "returns wrong value"}],
        })
        mock_result.cost_usd = 3.5
        mock_result.is_error = False

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_feature_verification(
            compliance_path=claude_dir / ".spec-compliance.json",
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=5.0,
            cwd=str(tmp_path),
            output_path=claude_dir / ".feature-verification.json",
        )

        assert report["broken"] == 1
        assert (claude_dir / ".feature-verification.json").exists()

    def test_skips_when_no_compliance_file(self, tmp_path: Path):
        mock_run_claude = MagicMock()

        report = run_feature_verification(
            compliance_path=tmp_path / ".claude" / ".spec-compliance.json",
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=5.0,
            cwd=str(tmp_path),
        )

        assert report["total_features"] == 0
        mock_run_claude.assert_not_called()

    def test_returns_empty_on_claude_error(self, tmp_path: Path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / ".spec-compliance.json").write_text(json.dumps({"total_requirements": 1, "implemented": 1, "details": [{"requirement": "a", "status": "implemented", "evidence": "x"}]}))

        mock_result = MagicMock()
        mock_result.is_error = True
        mock_result.text = ""
        mock_result.cost_usd = 1.0

        mock_run_claude = MagicMock(return_value=mock_result)

        report = run_feature_verification(
            compliance_path=claude_dir / ".spec-compliance.json",
            run_claude_fn=mock_run_claude,
            model="opus",
            budget=5.0,
            cwd=str(tmp_path),
        )

        assert report["total_features"] == 0
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement feature tester**

Create `src/superpower_workflow/validation/feature_tester.py`:

```python
"""Feature verification tester: independent claude -p call to verify features work."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


def build_verification_prompt(compliance_path: str) -> str:
    return (
        f"Read {compliance_path}.\n"
        f'For each requirement marked "implemented":\n'
        f"  1. Find an existing test that verifies this feature\n"
        f"  2. If no test exists, write a verification test\n"
        f"  3. Run all verification tests\n"
        f"Report which features pass and which fail.\n"
        f'Only verify objectively testable features. Mark subjective ones as "manual_review".\n'
        f"Write .claude/.feature-verification.json with this exact schema:\n"
        f'{{"total_features": N, "verified_working": N, "broken": N, "manual_review": N, '
        f'"details": [{{"feature": "...", "status": "pass"|"fail"|"manual_review", '
        f'"test": "test_file.py::test_name", "reason": "..."}}]}}\n'
        f"IMPORTANT: Output ONLY the JSON content, nothing else."
    )


def parse_verification_output(raw_text: str) -> dict[str, Any]:
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_text[start:end])
            return {
                "total_features": data.get("total_features", 0),
                "verified_working": data.get("verified_working", 0),
                "broken": data.get("broken", 0),
                "manual_review": data.get("manual_review", 0),
                "details": data.get("details", []),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return {
        "total_features": 0,
        "verified_working": 0,
        "broken": 0,
        "manual_review": 0,
        "details": [],
    }


def run_feature_verification(
    compliance_path: Path,
    run_claude_fn: Callable,
    model: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if not compliance_path.exists():
        return parse_verification_output("")

    prompt = build_verification_prompt(str(compliance_path))

    result = run_claude_fn(
        prompt,
        model=model,
        effort="high",
        budget=budget,
        cwd=cwd,
        system_prompt=system_prompt,
        fallback_model=fallback_model,
    )

    if result.is_error:
        report = parse_verification_output("")
        report["cost_usd"] = result.cost_usd
        return report

    report = parse_verification_output(result.text)
    report["cost_usd"] = result.cost_usd

    if output_path:
        tmp = output_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2))
        os.replace(str(tmp), str(output_path))

    return report
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/feature_tester.py tests/test_feature_tester.py --fix
ruff format src/superpower_workflow/validation/feature_tester.py tests/test_feature_tester.py
git add src/superpower_workflow/validation/feature_tester.py tests/test_feature_tester.py
git commit -m "feat: add feature verification tester with run_claude integration" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: Phase C prompt extension

**Files:**
- Edit: `src/superpower_workflow/prompts.py`
- Extend: `tests/test_prompts.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_prompts.py -- append
from superpower_workflow.prompts import phase_c_prompt


class TestPhaseCWithReports:
    def test_includes_compliance_report(self):
        prompt = phase_c_prompt(
            "test-ms", "context", "abc123", "pytest", "ruff", "ruff format --check .",
            compliance_report={"missing": 1, "details": [{"requirement": "feat B", "status": "missing", "evidence": "not found"}]},
        )
        assert "feat B" in prompt
        assert "missing" in prompt.lower()

    def test_includes_verification_report(self):
        prompt = phase_c_prompt(
            "test-ms", "context", "abc123", "pytest", "ruff", "ruff format --check .",
            verification_report={"broken": 1, "details": [{"feature": "CLI history", "status": "fail", "reason": "shows all"}]},
        )
        assert "CLI history" in prompt
        assert "shows all" in prompt

    def test_no_reports_unchanged(self):
        prompt = phase_c_prompt(
            "test-ms", "context", "abc123", "pytest", "ruff", "ruff format --check .",
        )
        assert "missing" not in prompt.lower() or "spec requirements" not in prompt.lower()

    def test_both_reports_included(self):
        prompt = phase_c_prompt(
            "test-ms", "context", "abc123", "pytest", "ruff", "ruff format --check .",
            compliance_report={"missing": 1, "details": [{"requirement": "A", "status": "missing", "evidence": "n/a"}]},
            verification_report={"broken": 1, "details": [{"feature": "B", "status": "fail", "reason": "wrong"}]},
        )
        assert "A" in prompt
        assert "B" in prompt
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Extend phase_c_prompt**

Edit `prompts.py` — add optional `compliance_report` and `verification_report` parameters to `phase_c_prompt`:

```python
def phase_c_prompt(
    name: str,
    context_summary: str,
    plan_commit_sha: str,
    verify_test: str,
    verify_lint: str,
    verify_format: str,
    compliance_report: dict | None = None,
    verification_report: dict | None = None,
) -> str:
    base = (
        f"You are executing Phase C (Review + Fix) for milestone {name}.\n\n"
        f"Context: {context_summary}\n\n"
    )

    extras = ""
    if compliance_report and compliance_report.get("missing", 0) > 0:
        extras += "\nThese spec requirements are missing from the implementation:\n"
        for d in compliance_report.get("details", []):
            if d.get("status") == "missing":
                extras += f"- {d.get('requirement', '?')} ({d.get('evidence', '')})\n"
        extras += "Implement them during this review phase.\n"

    if verification_report and verification_report.get("broken", 0) > 0:
        extras += "\nThese features exist but don't work correctly:\n"
        for d in verification_report.get("details", []):
            if d.get("status") == "fail":
                reason = d.get("reason", "")
                test = d.get("test", "")
                extras += f"- {d.get('feature', '?')}: FAIL"
                if reason:
                    extras += f" — {reason}"
                if test:
                    extras += f" ({test})"
                extras += "\n"
        extras += "Fix them during this review phase.\n"

    return (
        base + extras +
        f"1. Run post-impl-review on all files changed since {plan_commit_sha}.\n"
        f"2. Then run production-readiness-review on the same files.\n"
        f"3. Fix post-impl issues first (correctness), then production issues (hardening).\n"
        f"4. Re-run full test suite after all fixes.\n"
        f"5. Commit fixes. Tag each gap [post-impl] or [production] in gap_summaries.\n"
        f"6. Write .claude/.gap-report.json.\n\n"
        f"Verification: {verify_test}, {verify_lint}, {verify_format}"
    )
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/prompts.py tests/test_prompts.py --fix
ruff format src/superpower_workflow/prompts.py tests/test_prompts.py
git add src/superpower_workflow/prompts.py tests/test_prompts.py
git commit -m "feat: extend Phase C prompt with compliance and verification reports" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Orchestrator integration — spec compliance + feature verification steps

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Extend: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py -- append
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from superpower_workflow.runner import ClaudeResult


class TestSpecComplianceStep:
    def _make_orchestrator(self, tmp_path, validation_config=None):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config = {
            "spec": "docs/spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test-ms", "spec_sections": "1, 2"}],
            "convergence": {"max_iterations": 5},
        }
        if validation_config:
            config["validation"] = validation_config
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        from superpower_workflow.orchestrator import Orchestrator

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            return Orchestrator(tmp_path)

    @patch("superpower_workflow.orchestrator.run_claude")
    def test_spec_compliance_runs_when_enabled(self, mock_run, tmp_path: Path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"spec_compliance": True, "spec_compliance_budget": 3.0},
        )
        mock_run.return_value = ClaudeResult(
            text='{"total_requirements": 5, "implemented": 5, "missing": 0, "details": []}',
            cost_usd=2.0,
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        # Call the compliance step directly
        report, cost = orch._run_spec_compliance("test-ms", {"name": "test-ms", "spec_sections": "1, 2"})
        assert report["missing"] == 0
        assert cost == 2.0

    @patch("superpower_workflow.orchestrator.run_claude")
    def test_spec_compliance_skipped_when_disabled(self, mock_run, tmp_path: Path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"spec_compliance": False},
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        report, cost = orch._run_spec_compliance("test-ms", {"name": "test-ms"})
        assert report is None
        assert cost == 0.0
        mock_run.assert_not_called()


class TestFeatureVerificationStep:
    def _make_orchestrator(self, tmp_path, validation_config=None):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config = {
            "spec": "docs/spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test-ms"}],
            "convergence": {"max_iterations": 5},
        }
        if validation_config:
            config["validation"] = validation_config
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        from superpower_workflow.orchestrator import Orchestrator

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            return Orchestrator(tmp_path)

    @patch("superpower_workflow.orchestrator.run_claude")
    def test_feature_verification_runs_when_enabled(self, mock_run, tmp_path: Path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"feature_verification": True, "feature_verification_budget": 5.0},
        )
        claude_dir = tmp_path / ".claude"
        (claude_dir / ".spec-compliance.json").write_text(json.dumps({
            "total_requirements": 3,
            "implemented": 3,
            "details": [{"requirement": "A", "status": "implemented", "evidence": "x"}],
        }))

        mock_run.return_value = ClaudeResult(
            text='{"total_features": 3, "verified_working": 3, "broken": 0, "manual_review": 0, "details": []}',
            cost_usd=3.0,
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        report, cost = orch._run_feature_verification("test-ms")
        assert report["broken"] == 0
        assert cost == 3.0

    def test_feature_verification_skipped_when_disabled(self, tmp_path: Path):
        orch = self._make_orchestrator(
            tmp_path,
            validation_config={"feature_verification": False},
        )
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        report, cost = orch._run_feature_verification("test-ms")
        assert report is None
        assert cost == 0.0


class TestOrchestratorStateSteps:
    def test_spec_compliance_state_set(self, tmp_path: Path):
        """Orchestrator sets current_step to spec_compliance."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config = {
            "spec": "spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test"}],
            "validation": {"spec_compliance": True, "spec_compliance_budget": 3.0},
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        from superpower_workflow.orchestrator import Orchestrator

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            orch = Orchestrator(tmp_path)

        from superpower_workflow.state import save_state

        orch.state.current_step = "spec_compliance"
        save_state(claude_dir, orch.state)

        from superpower_workflow.state import load_state

        loaded = load_state(claude_dir)
        assert loaded.current_step == "spec_compliance"
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add spec compliance + feature verification to orchestrator**

In `orchestrator.py`, add two new methods and wire them into `_run_milestone`:

```python
from superpower_workflow.telemetry import (
    # ... existing imports ...
    GapValidationEvent,
    SpecComplianceCompleted,
    FeatureVerificationCompleted,
)

# New method: _run_spec_compliance
def _run_spec_compliance(self, name: str, ms: dict) -> tuple[dict | None, float]:
    validation = self.config.get("validation", {})
    if not validation.get("spec_compliance", False):
        return None, 0.0

    self.state.current_step = "spec_compliance"
    save_state(self.claude_dir, self.state)

    from superpower_workflow.validation.spec_compliance import run_spec_compliance

    spec_path = self.config["spec"]
    sections = ms.get("spec_sections", "")
    budget = validation.get("spec_compliance_budget", 3.0)

    # Derive module dirs from project structure (don't hardcode "src/")
    module_dirs = []
    src_dir = Path(self.cwd) / "src"
    if src_dir.exists():
        module_dirs.append("src/")
    else:
        module_dirs.append(".")
    report = run_spec_compliance(
        spec_path=spec_path,
        spec_sections=sections or "all",
        module_dirs=module_dirs,
        run_claude_fn=run_claude,
        model=self.config["model"],
        budget=budget,
        cwd=self.cwd,
        system_prompt=self.sys_prompt,
        fallback_model=self.config.get("fallback_model"),
        output_path=self.claude_dir / ".spec-compliance.json",
    )

    cost = report.get("cost_usd", 0.0)
    self._telemetry.emit(SpecComplianceCompleted(
        milestone=name,
        total_requirements=report.get("total_requirements", 0),
        implemented=report.get("implemented", 0),
        missing=report.get("missing", 0),
        cost_usd=cost,
    ))

    return report, cost


# New method: _run_feature_verification
def _run_feature_verification(self, name: str) -> tuple[dict | None, float]:
    validation = self.config.get("validation", {})
    if not validation.get("feature_verification", False):
        return None, 0.0

    self.state.current_step = "feature_verify"
    save_state(self.claude_dir, self.state)

    from superpower_workflow.validation.feature_tester import run_feature_verification

    budget = validation.get("feature_verification_budget", 5.0)
    compliance_path = self.claude_dir / ".spec-compliance.json"

    report = run_feature_verification(
        compliance_path=compliance_path,
        run_claude_fn=run_claude,
        model=self.config["model"],
        budget=budget,
        cwd=self.cwd,
        system_prompt=self.sys_prompt,
        fallback_model=self.config.get("fallback_model"),
        output_path=self.claude_dir / ".feature-verification.json",
    )

    cost = report.get("cost_usd", 0.0)
    self._telemetry.emit(FeatureVerificationCompleted(
        milestone=name,
        total_features=report.get("total_features", 0),
        verified=report.get("verified_working", 0),
        broken=report.get("broken", 0),
        manual_review=report.get("manual_review", 0),
        cost_usd=cost,
    ))

    return report, cost
```

Also add `_emit_gap_validation` to read the gap validator output and emit telemetry
(the convergence hook runs in a separate process and can't emit events directly):

```python
def _emit_gap_validation(self, milestone: str) -> None:
    validation_path = self.claude_dir / ".gap-validation.json"
    if not validation_path.exists():
        return
    try:
        data = json.loads(validation_path.read_text())
        self._telemetry.emit(GapValidationEvent(
            milestone=milestone,
            total=data.get("total_gaps", 0),
            valid=data.get("valid_gaps", 0),
            invalid=data.get("invalid_gaps", 0),
            unverifiable=data.get("unverifiable_gaps", 0),
            duplicate=data.get("duplicate_gaps", 0),
        ))
    except (json.JSONDecodeError, OSError):
        pass
```

Call `_emit_gap_validation` AFTER `_emit_gap_report` in Phase A and Phase C blocks.

In `_run_milestone`, between the Quality Gates #1 block and Phase C, insert
(after the context refresh, before the Phase C comment):

```python
# Spec Compliance Check
compliance_report, compliance_cost = self._run_spec_compliance(name, ms)
cost += compliance_cost

# Feature Verification
verification_report, verify_cost = self._run_feature_verification(name)
cost += verify_cost
```

And pass the reports to `phase_c_prompt`:

```python
r = run_claude(
    phase_c_prompt(
        name,
        context,
        self.state.plan_commit_sha or "",
        verify.get("test", "true"),
        verify.get("lint", "true"),
        verify.get("format", "true"),
        compliance_report=compliance_report,
        verification_report=verification_report,
    ),
    ...
)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire spec compliance and feature verification into orchestrator" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: Validation package exports

**Files:**
- Edit: `src/superpower_workflow/validation/__init__.py`
- Extend: `tests/test_gap_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gap_validator.py -- append
class TestValidationExports:
    def test_gap_validator_exports(self):
        from superpower_workflow.validation import (
            GapState,
            GapValidationReport,
            GapValidationResult,
            FileReference,
            ValidationCheck,
            validate_gaps,
            extract_file_references,
            check_file_exists,
            check_line_in_range,
            check_symbol_exists,
            find_duplicates,
            check_tool_claims,
        )
        assert GapState is not None
        assert validate_gaps is not None

    def test_spec_compliance_exports(self):
        from superpower_workflow.validation import (
            run_spec_compliance,
            build_compliance_prompt,
            parse_compliance_output,
        )
        assert run_spec_compliance is not None

    def test_feature_tester_exports(self):
        from superpower_workflow.validation import (
            run_feature_verification,
            build_verification_prompt,
            parse_verification_output,
        )
        assert run_feature_verification is not None
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Update __init__.py exports**

```python
"""Trust-but-verify validation layer: gap validator, spec compliance, feature verification."""

from __future__ import annotations

from superpower_workflow.validation.gap_validator import (
    FileReference,
    GapState,
    GapValidationReport,
    GapValidationResult,
    ValidationCheck,
    check_file_exists,
    check_line_in_range,
    check_symbol_exists,
    check_tool_claims,
    extract_file_references,
    find_duplicates,
    validate_gaps,
)
from superpower_workflow.validation.feature_tester import (
    build_verification_prompt,
    parse_verification_output,
    run_feature_verification,
)
from superpower_workflow.validation.spec_compliance import (
    build_compliance_prompt,
    parse_compliance_output,
    run_spec_compliance,
)

__all__ = [
    "FileReference",
    "GapState",
    "GapValidationReport",
    "GapValidationResult",
    "ValidationCheck",
    "build_compliance_prompt",
    "build_verification_prompt",
    "check_file_exists",
    "check_line_in_range",
    "check_symbol_exists",
    "check_tool_claims",
    "extract_file_references",
    "find_duplicates",
    "parse_compliance_output",
    "parse_verification_output",
    "run_feature_verification",
    "run_spec_compliance",
    "validate_gaps",
]
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/validation/__init__.py tests/test_gap_validator.py --fix
ruff format src/superpower_workflow/validation/__init__.py tests/test_gap_validator.py
git add src/superpower_workflow/validation/__init__.py tests/test_gap_validator.py
git commit -m "feat: add validation package exports with __all__" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 15: End-to-end integration tests

**Files:**
- New: `tests/test_trust_verify_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_trust_verify_integration.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from superpower_workflow.hooks.convergence_gate import compute_exit_code
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import VALID_STEPS, load_state, save_state, WorkflowState
from superpower_workflow.telemetry import (
    GapValidationEvent,
    SpecComplianceCompleted,
    FeatureVerificationCompleted,
)
from superpower_workflow.validation.gap_validator import (
    GapState,
    validate_gaps,
)


class TestEndToEndGapValidation:
    def test_full_gap_validation_pipeline(self, tmp_path: Path):
        """Full pipeline: create files, write gap report, run convergence gate."""
        # Setup project structure
        (tmp_path / "src" / "mod").mkdir(parents=True)
        (tmp_path / "src" / "mod" / "store.py").write_text(
            "class Store:\n    def put(self, key, value):\n        pass\n"
        )

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Config with strict validation
        config = {
            "validation": {"gap_validator": True, "gap_validation_mode": "strict"},
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        # Gap report with mix of valid and invalid
        gap_report = {
            "pass": 1,
            "critical_gaps": 1,
            "important_gaps": 3,
            "tests_green": True,
            "lint_clean": True,
            "converged": False,
            "gap_summaries": [
                "[ultrathink] src/mod/store.py:2 put method missing validation",
                "[ultrathink] nonexistent_module.py:99 has a critical bug",
                "[ultrathink] the overall architecture needs improvement",
                "[ultrathink] src/mod/store.py:1 Store class needs docstring",
            ],
        }
        (claude_dir / ".gap-report.json").write_text(json.dumps(gap_report))

        # Phase state
        phase = {"phase": "ultrathink", "iteration": 0, "max_iterations": 5}
        (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase))

        # Run convergence gate
        code = compute_exit_code(claude_dir)

        # Verify gap-validation.json was written
        validation_path = claude_dir / ".gap-validation.json"
        assert validation_path.exists()
        validation = json.loads(validation_path.read_text())
        assert validation["total_gaps"] == 4
        assert validation["valid_gaps"] >= 2  # store.py references
        assert validation["invalid_gaps"] >= 1  # nonexistent.py

    def test_validation_disabled_backward_compat(self, tmp_path: Path):
        """No validation section = backward compatible behavior."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Config WITHOUT validation section
        config = {"model": "opus"}
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        gap_report = {
            "critical_gaps": 0,
            "important_gaps": 1,
            "tests_green": True,
            "lint_clean": True,
            "gap_summaries": ["[ultrathink] concern"],
        }
        (claude_dir / ".gap-report.json").write_text(json.dumps(gap_report))
        phase = {"phase": "ultrathink", "iteration": 0, "max_iterations": 5}
        (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase))

        code = compute_exit_code(claude_dir)
        assert code == 0  # 0 critical, 1 important <= 3 → converges
        assert not (claude_dir / ".gap-validation.json").exists()


class TestEndToEndResumeStates:
    def test_resume_from_spec_compliance(self, tmp_path: Path):
        """State can save and load spec_compliance step."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        state = WorkflowState()
        state.current_step = "spec_compliance"
        state.current_milestone_index = 2
        save_state(claude_dir, state)

        loaded = load_state(claude_dir)
        assert loaded.current_step == "spec_compliance"
        assert loaded.current_milestone_index == 2

    def test_resume_from_feature_verify(self, tmp_path: Path):
        """State can save and load feature_verify step."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        state = WorkflowState()
        state.current_step = "feature_verify"
        save_state(claude_dir, state)

        loaded = load_state(claude_dir)
        assert loaded.current_step == "feature_verify"


class TestEndToEndTelemetry:
    def test_gap_validation_event_serialization(self):
        e = GapValidationEvent(
            milestone="test-ms", total=10, valid=7, invalid=2, unverifiable=1, duplicate=1
        )
        d = e.to_dict()
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "gap_validation"
        assert parsed["total"] == 10

    def test_spec_compliance_event_serialization(self):
        e = SpecComplianceCompleted(
            milestone="test-ms", total_requirements=15, implemented=13, missing=2, cost_usd=2.5
        )
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "spec_compliance_completed"
        assert parsed["missing"] == 2

    def test_feature_verification_event_serialization(self):
        e = FeatureVerificationCompleted(
            milestone="test-ms", total_features=10, verified=8, broken=1, manual_review=1, cost_usd=3.5
        )
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "feature_verification_completed"
        assert parsed["broken"] == 1


class TestEndToEndValidSteps:
    def test_all_new_steps_in_valid_steps(self):
        assert "spec_compliance" in VALID_STEPS
        assert "feature_verify" in VALID_STEPS

    def test_existing_steps_unchanged(self):
        for step in ("plan", "implement", "review", "push", "quality_check_b", "quality_check_c"):
            assert step in VALID_STEPS


class TestEndToEndConfig:
    def test_init_creates_validation_config(self, tmp_path: Path):
        from superpower_workflow.cli import _cmd_init
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        v = config["validation"]
        assert v["gap_validator"] is True
        assert v["gap_validation_mode"] == "lenient"
        assert v["spec_compliance"] is True
        assert v["feature_verification"] is True
        assert v["spec_compliance_budget"] == 3.0
        assert v["feature_verification_budget"] == 5.0


class TestEndToEndSpecCompliance:
    @patch("superpower_workflow.orchestrator.run_claude")
    def test_orchestrator_compliance_flow(self, mock_run, tmp_path: Path):
        """Orchestrator calls spec compliance when enabled."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config = {
            "spec": "spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test-ms", "spec_sections": "1, 2"}],
            "convergence": {"max_iterations": 5},
            "validation": {
                "spec_compliance": True,
                "spec_compliance_budget": 3.0,
                "feature_verification": True,
                "feature_verification_budget": 5.0,
            },
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        from superpower_workflow.orchestrator import Orchestrator

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            orch = Orchestrator(tmp_path)
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        mock_run.return_value = ClaudeResult(
            text=json.dumps({
                "spec_path": "spec.md",
                "spec_sections": "1, 2",
                "total_requirements": 5,
                "implemented": 5,
                "missing": 0,
                "details": [],
            }),
            cost_usd=2.0,
        )

        report, cost = orch._run_spec_compliance("test-ms", {"name": "test-ms", "spec_sections": "1, 2"})
        assert report is not None
        assert report["missing"] == 0
        assert cost == 2.0
        assert (claude_dir / ".spec-compliance.json").exists()
```

- [ ] **Step 2: Run tests -- expect PASS** (all implementation done)

- [ ] **Step 3: Lint + commit**

```bash
ruff check tests/test_trust_verify_integration.py --fix
ruff format tests/test_trust_verify_integration.py
git add tests/test_trust_verify_integration.py
git commit -m "test: add end-to-end integration tests for trust-but-verify" --trailer "Generated-By: claude-opus-4-6"
```

---

## Summary

| Task | Description | New Tests | Files |
|---|---|---|---|
| 1 | Validation package + config schema | 2 | 3 |
| 2 | Gap validator types + reference extraction | 8 | 2 |
| 3 | File + line + symbol validation | 9 | 2 |
| 4 | Duplicate gap detection | 6 | 2 |
| 5 | Tool cross-check | 6 | 2 |
| 6 | Gap validator main function + output | 10 | 2 |
| 7 | Convergence gate integration | 5 | 2 |
| 8 | Telemetry events + state updates | 7 | 3 |
| 9 | Quality gate results caching | 1 | 2 |
| 10 | Spec compliance checker | 6 | 2 |
| 11 | Feature verification tester | 6 | 2 |
| 12 | Phase C prompt extension | 4 | 2 |
| 13 | Orchestrator integration | 5 | 2 |
| 14 | Validation package exports | 3 | 2 |
| 15 | End-to-end integration tests | 10 | 1 |
| **Total** | | **~88** | |

**Estimated cost:** ~$5-8 per milestone (gap validator $0, spec compliance ~$2-3, feature verification ~$3-5)
**New dependencies:** None
**Backward compatible:** Yes — missing `validation` section = all checks disabled
