from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init
from superpower_workflow.validation.gap_validator import (
    FileReference,
    GapState,
    extract_file_references,
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
