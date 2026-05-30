"""Spec linter — pure text-analysis quality gate on spec.md before `sw decompose`.

Per the v1.1.7 roadmap (T1.7.1): runs as part of `sw decompose` and as a
standalone `sw lint-spec` command. Zero LLM cost. Catches noise at the input
layer so downstream filters (gap curator, strict mode, trust-but-verify) have
less work to do.

Checks (each returns CheckResult with state, reason, optional suggestion):
- requirements_countable (FAIL): >=1 numbered/bulleted requirement list block
- nonfunctional_section (WARN): "## Non-functional" or equivalent with >=3 bullets
- quality_gates_declared (WARN): mentions lint/test/coverage threshold
- out_of_scope_section (WARN): explicit "Out of scope" or "Not included" section
- no_placeholders (FAIL): no TBD/TODO/XXX/??? markers
- acceptance_criteria (WARN): multiple AC styles supported
- length_reasonable (WARN): word count in [min, max] (configurable)
- code_blocks_balanced (FAIL): no orphan ``` or ~~~ fences

Scoring (0-100): FAIL = -10 each, WARN = -3 each, floor at 0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

DEFAULT_MIN_WORDS = 200
DEFAULT_MAX_WORDS = 5000
DEFAULT_SCORE = 100
FAIL_PENALTY = 10
WARN_PENALTY = 3


class CheckState(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    state: CheckState
    reason: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict:
        d = {"name": self.name, "state": self.state.value}
        if self.reason:
            d["reason"] = self.reason
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d


@dataclass
class SpecLintReport:
    spec_path: str = ""
    score: int = DEFAULT_SCORE
    checks: list[CheckResult] = field(default_factory=list)
    blocker_count: int = 0
    warning_count: int = 0

    def to_dict(self) -> dict:
        return {
            "spec_path": self.spec_path,
            "score": self.score,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "checks": [c.to_dict() for c in self.checks],
        }

    @property
    def has_blockers(self) -> bool:
        return self.blocker_count > 0


# --- patterns ----------------------------------------------------------------

# Numbered list (1. / 1) / 2.) or bullet (- / * / +)
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.\)]|[-*+])\s+\S", re.MULTILINE)

# Non-functional section heading (markdown # or ## variants)
_NFR_HEADING = re.compile(
    r"^\s*#{1,6}\s*(?:non[-_ ]functional|nfr|qualities|constraints)\b",
    re.MULTILINE | re.IGNORECASE,
)

# Out-of-scope heading
_OOS_HEADING = re.compile(
    r"^\s*#{1,6}\s*(?:out[-_ ]of[-_ ]scope|not[-_ ]included|non[-_ ]goals|exclusions)\b",
    re.MULTILINE | re.IGNORECASE,
)

# Quality-gate mentions
_QG_KEYWORDS = re.compile(
    r"\b(?:lint|test(?:s|ing)?|coverage|threshold|ruff|pytest|mypy|bandit)\b",
    re.IGNORECASE,
)

# Placeholders that signal incomplete spec. Word-bounded for letter
# placeholders (so "tbdfoo" doesn't match) but plain match for "???"
# since `\b` requires a word/non-word transition that "?" never produces.
_PLACEHOLDERS = re.compile(r"(?:\b(?:TBD|TODO|FIXME|XXX)\b|\?\?\?)")

# Acceptance-criteria style markers (any one is fine)
_AC_STYLES = re.compile(
    r"(?:\bmust\b|\bshall\b|\bwhen\b.{0,40}\bthen\b|"
    r"\bgiven\b.{0,80}\bwhen\b|\bREQ-\d+|\bAC-\d+)",
    re.IGNORECASE | re.DOTALL,
)

# Code-block fences — both backtick and tilde styles
_BACKTICK_FENCE = re.compile(r"^```", re.MULTILINE)
_TILDE_FENCE = re.compile(r"^~~~", re.MULTILINE)

# Heading at any level for section extraction
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)$", re.MULTILINE)


def _read_spec(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _section_body(text: str, heading_re: re.Pattern) -> str:
    """Extract the body following a matched heading until the next heading or EOF."""
    m = heading_re.search(text)
    if not m:
        return ""
    start = m.end()
    next_h = _HEADING.search(text, start)
    end = next_h.start() if next_h else len(text)
    return text[start:end]


def _count_list_items(text: str) -> int:
    return len(_LIST_ITEM.findall(text))


def _word_count(text: str) -> int:
    # Strip code blocks for a fairer word count
    stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    stripped = re.sub(r"~~~.*?~~~", "", stripped, flags=re.DOTALL)
    return len(re.findall(r"\b\w+\b", stripped))


# --- individual checks -------------------------------------------------------


def _check_requirements_countable(text: str) -> CheckResult:
    n = _count_list_items(text)
    if n >= 1:
        return CheckResult(
            "requirements_countable",
            CheckState.PASS,
            f"{n} list items found",
        )
    return CheckResult(
        "requirements_countable",
        CheckState.FAIL,
        "No numbered or bulleted lists detected. Requirements should be enumerable.",
        suggestion="Add a `## Functional requirements` section with numbered items.",
    )


def _check_nonfunctional_section(text: str) -> CheckResult:
    if not _NFR_HEADING.search(text):
        return CheckResult(
            "nonfunctional_section",
            CheckState.WARN,
            "No non-functional requirements section detected.",
            suggestion="Add `## Non-functional requirements` listing perf, security, "
            "compat, observability constraints.",
        )
    body = _section_body(text, _NFR_HEADING)
    bullets = _count_list_items(body)
    if bullets < 3:
        return CheckResult(
            "nonfunctional_section",
            CheckState.WARN,
            f"Non-functional section has {bullets} bullets; expect >= 3.",
            suggestion="Cover perf, security, observability at minimum.",
        )
    return CheckResult(
        "nonfunctional_section",
        CheckState.PASS,
        f"{bullets} non-functional bullets",
    )


def _check_quality_gates_declared(text: str) -> CheckResult:
    matches = _QG_KEYWORDS.findall(text)
    if matches:
        return CheckResult(
            "quality_gates_declared",
            CheckState.PASS,
            f"{len(matches)} quality-gate references",
        )
    return CheckResult(
        "quality_gates_declared",
        CheckState.WARN,
        "No lint/test/coverage mentions — quality bar is implicit.",
        suggestion="Declare verification commands: lint, test, coverage threshold.",
    )


def _check_out_of_scope_section(text: str) -> CheckResult:
    if _OOS_HEADING.search(text):
        return CheckResult(
            "out_of_scope_section",
            CheckState.PASS,
            "out-of-scope section present",
        )
    return CheckResult(
        "out_of_scope_section",
        CheckState.WARN,
        "No explicit out-of-scope section.",
        suggestion="Add `## Out of scope` to prevent scope creep during decomposition.",
    )


def _check_no_placeholders(text: str) -> CheckResult:
    matches = _PLACEHOLDERS.findall(text)
    if matches:
        return CheckResult(
            "no_placeholders",
            CheckState.FAIL,
            f"Found {len(matches)} placeholder markers: {sorted(set(matches))}",
            suggestion="Resolve TBD/TODO/XXX/??? before running `sw decompose`.",
        )
    return CheckResult("no_placeholders", CheckState.PASS, "no placeholders")


def _check_acceptance_criteria(text: str) -> CheckResult:
    matches = _AC_STYLES.findall(text)
    if len(matches) >= 1:
        return CheckResult(
            "acceptance_criteria",
            CheckState.PASS,
            f"{len(matches)} acceptance-criteria phrases",
        )
    return CheckResult(
        "acceptance_criteria",
        CheckState.WARN,
        "No testable acceptance criteria detected.",
        suggestion="Use 'must', 'when X then Y', or 'REQ-NN' style per requirement.",
    )


def _check_length_reasonable(text: str, min_words: int, max_words: int) -> CheckResult:
    n = _word_count(text)
    if n < min_words:
        return CheckResult(
            "length_reasonable",
            CheckState.WARN,
            f"Spec is {n} words; under {min_words} usually means vague.",
            suggestion="Expand requirements with concrete behavior.",
        )
    if n > max_words:
        return CheckResult(
            "length_reasonable",
            CheckState.WARN,
            f"Spec is {n} words; over {max_words} usually needs decomposition.",
            suggestion="Split into multiple specs via the `spec_paths` config (v1.1.7+).",
        )
    return CheckResult(
        "length_reasonable",
        CheckState.PASS,
        f"{n} words (in [{min_words}, {max_words}])",
    )


def _check_code_blocks_balanced(text: str) -> CheckResult:
    backticks = len(_BACKTICK_FENCE.findall(text))
    tildes = len(_TILDE_FENCE.findall(text))
    issues = []
    if backticks % 2:
        issues.append(f"{backticks} backtick fences (odd)")
    if tildes % 2:
        issues.append(f"{tildes} tilde fences (odd)")
    if issues:
        return CheckResult(
            "code_blocks_balanced",
            CheckState.FAIL,
            "Unclosed code block: " + ", ".join(issues),
            suggestion="Match every opening fence with a closing fence.",
        )
    return CheckResult(
        "code_blocks_balanced",
        CheckState.PASS,
        f"{backticks // 2} backtick blocks, {tildes // 2} tilde blocks",
    )


# --- top-level entry ---------------------------------------------------------


def lint_spec(
    spec_path: Path,
    min_words: int = DEFAULT_MIN_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
    section: str | None = None,
) -> SpecLintReport:
    """Lint the spec at `spec_path`. Returns a SpecLintReport with score 0-100.

    If `section` is given, restricts checks to the matching markdown section
    body (per G1.7.4). Useful for milestone-level linting via spec_sections.
    """
    text = _read_spec(spec_path)
    if section:
        section_re = re.compile(
            rf"^\s*#{{1,6}}\s*.*\b{re.escape(section)}\b",
            re.MULTILINE | re.IGNORECASE,
        )
        body = _section_body(text, section_re)
        if body:
            text = body

    checks: list[CheckResult] = [
        _check_requirements_countable(text),
        _check_nonfunctional_section(text),
        _check_quality_gates_declared(text),
        _check_out_of_scope_section(text),
        _check_no_placeholders(text),
        _check_acceptance_criteria(text),
        _check_length_reasonable(text, min_words, max_words),
        _check_code_blocks_balanced(text),
    ]

    blocker_count = sum(1 for c in checks if c.state == CheckState.FAIL)
    warning_count = sum(1 for c in checks if c.state == CheckState.WARN)
    score = max(0, DEFAULT_SCORE - blocker_count * FAIL_PENALTY - warning_count * WARN_PENALTY)

    return SpecLintReport(
        spec_path=str(spec_path),
        score=score,
        checks=checks,
        blocker_count=blocker_count,
        warning_count=warning_count,
    )


def write_report(report: SpecLintReport, output_path: Path) -> None:
    """Persist report as JSON (used by `sw decompose` to share with downstream)."""
    import os

    tmp = output_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    os.replace(str(tmp), str(output_path))
