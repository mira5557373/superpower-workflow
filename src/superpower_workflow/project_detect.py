"""Project-type detection + per-language QA gate defaults (T1.8.4).

Inspects a project root for marker files (pyproject.toml, package.json,
Cargo.toml, go.mod, etc.) and returns:
- detected `languages: list[str]` (ordered by priority; first is primary)
- recommended `verify_commands` block
- recommended `quality_gates` block

Used by `sw init --with-quality-gates` (T1.8.2) and `sw onboard` (v1.1.9).
All commands are STRING templates; user is responsible for installing the
listed tools. `sw doctor` (future) will verify they resolve in PATH.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectProfile:
    """Result of project detection."""

    languages: list[str] = field(default_factory=list)
    verify_commands: dict[str, str | None] = field(default_factory=dict)
    quality_gates: dict[str, str | None] = field(default_factory=dict)

    @property
    def primary_language(self) -> str:
        return self.languages[0] if self.languages else "generic"


# Marker files per language. Order matters — the first match becomes primary.
_LANG_MARKERS: list[tuple[str, list[str]]] = [
    ("python", ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"]),
    ("typescript", ["tsconfig.json"]),
    ("javascript", ["package.json"]),
    ("rust", ["Cargo.toml"]),
    ("go", ["go.mod"]),
    ("java", ["pom.xml", "build.gradle", "build.gradle.kts"]),
    ("ruby", ["Gemfile"]),
]


_VERIFY_COMMANDS: dict[str, dict[str, str]] = {
    "python": {
        "lint": "ruff check .",
        "format": "ruff format --check .",
        "test": "pytest -q",
        "coverage": "pytest --cov=src --cov-fail-under=80",
    },
    "typescript": {
        "lint": "npx eslint .",
        "format": "npx prettier --check .",
        "test": "npm test",
        "coverage": "npm test -- --coverage",
    },
    "javascript": {
        "lint": "npx eslint .",
        "format": "npx prettier --check .",
        "test": "npm test",
    },
    "rust": {
        "lint": "cargo clippy -- -D warnings",
        "format": "cargo fmt --check",
        "test": "cargo test",
    },
    "go": {
        "lint": "golangci-lint run",
        "format": "gofmt -l .",
        "test": "go test ./...",
    },
}


_QUALITY_GATES: dict[str, dict[str, str]] = {
    "python": {
        # Security: bandit scans Python for common vulnerabilities (`-ll` = high+medium)
        "sast": "bandit -r src/ -ll -q",
        # Dependency vulnerabilities
        "dep_scan": "pip-audit --strict",
        # Cyclomatic complexity ceiling — fail when functions exceed grade C
        "complexity": "radon cc src/ -n C -a",
        # Type checking (optional but recommended)
        "type_check": "mypy src/",
        "secret_scan": None,  # leave for user to configure
    },
    "typescript": {
        "sast": None,  # No standard SAST for TS yet; eslint-plugin-security can fill in
        "dep_scan": "npm audit --audit-level=high",
        "type_check": "npx tsc --noEmit",
        "secret_scan": None,
    },
    "javascript": {
        "sast": None,
        "dep_scan": "npm audit --audit-level=high",
        "secret_scan": None,
    },
    "rust": {
        "dep_scan": "cargo audit",
        "secret_scan": None,
        "sast": None,
    },
    "go": {
        "dep_scan": "govulncheck ./...",
        "sast": "gosec ./...",
        "secret_scan": None,
    },
}


def detect_languages(project_root: Path) -> list[str]:
    """Return detected languages, primary first. Empty list when no markers found."""
    found: list[str] = []
    for lang, markers in _LANG_MARKERS:
        if any((project_root / m).exists() for m in markers):
            found.append(lang)
    return found


def detect(project_root: Path) -> ProjectProfile:
    """Inspect project_root and return a ProjectProfile with recommended config."""
    langs = detect_languages(project_root)
    profile = ProjectProfile(languages=langs)
    if not langs:
        return profile

    primary = langs[0]
    profile.verify_commands = dict(_VERIFY_COMMANDS.get(primary, {}))
    profile.quality_gates = dict(_QUALITY_GATES.get(primary, {}))

    # For mixed-language projects (G1.8.6), merge secondary languages' dep_scan
    # so we cover all manifests. Primary's choices win on conflicts.
    for secondary in langs[1:]:
        sec_gates = _QUALITY_GATES.get(secondary, {})
        for key, cmd in sec_gates.items():
            if cmd and key not in profile.quality_gates:
                profile.quality_gates[key] = cmd

    return profile


def language_supported(lang: str) -> bool:
    """True if we have at least basic recommendations for this language."""
    return lang in _VERIFY_COMMANDS or lang in _QUALITY_GATES
