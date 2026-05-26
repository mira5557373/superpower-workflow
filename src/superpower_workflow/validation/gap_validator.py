"""Gap validator: verify file references, detect duplicates, cross-check tool claims."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
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


_SKIP_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".git",
        ".worktrees",
        "build",
        "dist",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".egg-info",
    }
)


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


def normalize_gap(text: str) -> str:
    text = re.sub(r"\[[\w-]+\]\s*", "", text)
    text = re.sub(r":\d+", "", text)
    text = re.sub(r"\S+/", "", text)
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
                return not tool_passed
            return None
    return None
