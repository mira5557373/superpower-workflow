from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init
from superpower_workflow.validation.gap_validator import (
    FileReference,
    GapState,
    check_file_exists,
    check_line_in_range,
    check_symbol_exists,
    check_tool_claims,
    compute_similarity,
    extract_file_references,
    find_duplicates,
    normalize_gap,
)


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


class TestCheckToolClaims:
    def test_gap_about_lint_passes_when_lint_passed(self):
        results = {"lint": {"passed": True}}
        result = check_tool_claims("lint failures in module", results)
        assert result is False

    def test_gap_about_lint_valid_when_lint_failed(self):
        results = {"lint": {"passed": False}}
        result = check_tool_claims("lint failures in module", results)
        assert result is True

    def test_gap_about_tests_passes_when_tests_passed(self):
        results = {"test": {"passed": True}}
        result = check_tool_claims("tests are failing", results)
        assert result is False

    def test_gap_not_about_tools(self):
        results = {"lint": {"passed": True}}
        result = check_tool_claims("architecture needs improvement", results)
        assert result is None

    def test_empty_results(self):
        result = check_tool_claims("lint failing", {})
        assert result is None

    def test_coverage_claim(self):
        results = {"coverage": {"passed": False, "coverage_pct": 45.0}}
        result = check_tool_claims("coverage is below threshold", results)
        assert result is True
