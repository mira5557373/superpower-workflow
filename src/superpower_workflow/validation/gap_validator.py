"""Gap validator: verify file references, detect duplicates, cross-check tool claims."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


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


_FILE_COLON_LINE = re.compile(r"([\w./\\-]+\.(?:py|ts|js|jsx|tsx|md|yaml|yml|json|toml)):(\d+)")
_FILE_LINE_N = re.compile(
    r"([\w./\\-]+\.(?:py|ts|js|jsx|tsx|md|yaml|yml|json|toml))\s+line\s+(\d+)",
    re.IGNORECASE,
)
_FILE_ONLY = re.compile(r"([\w./\\-]+\.(?:py|ts|js|jsx|tsx|md|yaml|yml|json|toml))")
_SYMBOL_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:\.[a-z_][a-z0-9_]*)?)\b")


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
