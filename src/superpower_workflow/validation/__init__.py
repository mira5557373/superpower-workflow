"""Trust-but-verify validation layer: gap validator, spec compliance, feature verification."""

from __future__ import annotations

from superpower_workflow.validation.feature_tester import (
    build_verification_prompt,
    parse_verification_output,
    run_feature_verification,
)
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
from superpower_workflow.validation.spec_compliance import (
    build_compliance_prompt,
    parse_compliance_output,
    run_spec_compliance,
)
from superpower_workflow.validation.spec_linter import (
    CheckResult,
    CheckState,
    SpecLintReport,
    lint_spec,
    write_report,
)

__all__ = [
    "CheckResult",
    "CheckState",
    "FileReference",
    "GapState",
    "GapValidationReport",
    "GapValidationResult",
    "SpecLintReport",
    "ValidationCheck",
    "build_compliance_prompt",
    "build_verification_prompt",
    "check_file_exists",
    "check_line_in_range",
    "check_symbol_exists",
    "check_tool_claims",
    "extract_file_references",
    "find_duplicates",
    "lint_spec",
    "parse_compliance_output",
    "parse_verification_output",
    "run_feature_verification",
    "run_spec_compliance",
    "validate_gaps",
    "write_report",
]
