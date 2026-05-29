"""Gap curator: post-process raw gap reports to drop noise and surface real, scoped gaps.

Insertion point: after Phase A or Phase C writes `.gap-report.json`, before the
convergence gate / validator / archival pipeline. Reads raw gaps + spec + focused
diff + (review-phase only) spec compliance findings. Writes a curated gap report
schema-compatible with the original so downstream consumers need no awareness.

Design principles:
- Conservatism over aggressiveness: when uncertain, KEEP the gap. False negatives
  cost more than false positives.
- Phase-aware: plan-phase tolerates anchors to the plan markdown; review-phase
  requires anchors to written code.
- Cost-bounded: skip when raw count < min; fixed budget per call; fallback to raw
  on any failure mode (parse error, model rejection, IO error).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BUDGET = 1.0
DEFAULT_MIN_GAPS = 5
DIFF_TRUNCATE_BYTES = 30_000
SPEC_TRUNCATE_BYTES = 20_000

_FILE_REF = re.compile(r"([\w./\\-]+\.(?:py|ts|js|jsx|tsx|md|yaml|yml|json|toml)):(\d+)")


def _extract_referenced_files(raw_gaps: dict) -> set[str]:
    """Return the set of files mentioned by any gap summary (for focused diff)."""
    files: set[str] = set()
    for key in ("critical", "important", "architectural", "minor", "deferred"):
        for g in raw_gaps.get(key, []) or []:
            text = (
                g if isinstance(g, str) else (g.get("summary", "") if isinstance(g, dict) else "")
            )
            for m in _FILE_REF.finditer(text):
                files.add(m.group(1))
    # Also scan a flat "gaps" list if present
    for g in raw_gaps.get("gaps", []) or []:
        text = g if isinstance(g, str) else (g.get("summary", "") if isinstance(g, dict) else "")
        for m in _FILE_REF.finditer(text):
            files.add(m.group(1))
    return files


def _read_focused_diff(project_root: Path, files: set[str], plan_sha: str) -> str:
    """Read git diff for only the files mentioned in raw gaps, truncated."""
    if not files or not plan_sha:
        return ""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", plan_sha, "--", *sorted(files)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return ""
        diff = result.stdout
        if len(diff) > DIFF_TRUNCATE_BYTES:
            diff = diff[:DIFF_TRUNCATE_BYTES] + "\n...[truncated]..."
        return diff
    except (subprocess.SubprocessError, OSError):
        return ""


def _read_text_truncated(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]..."
    return text


def build_curator_prompt(
    phase: str,
    raw_gap_report: dict,
    spec_text: str,
    compliance_text: str,
    diff_text: str,
) -> str:
    """Construct a phase-aware curator prompt."""
    is_review = phase == "review"
    anchor_rule = (
        "Anchor must point at code that EXISTS in the diff above."
        if is_review
        else "Anchor must point at the plan markdown file OR pre-milestone code."
    )

    sections = [
        f"You are reviewing a raw gap report from the {phase!r} phase. "
        f"Your job is to drop noise and surface only real, scoped, actionable gaps.",
        "",
        "RAW GAP REPORT (JSON):",
        json.dumps(raw_gap_report, indent=2)[:8000],
        "",
        "SPEC (truncated):",
        spec_text or "(no spec available)",
        "",
    ]
    if is_review and compliance_text:
        sections.extend(
            [
                "SPEC COMPLIANCE FINDINGS (these are ALREADY tracked by trust-but-verify):",
                compliance_text,
                "",
            ]
        )
    if diff_text:
        sections.extend(
            [
                "DIFF (only files mentioned by raw gaps):",
                diff_text,
                "",
            ]
        )
    sections.extend(
        [
            "FILTERS to apply (apply ALL):",
            "  1. DROP gaps without a verifiable anchor. " + anchor_rule,
            "  2. DROP gaps already covered by spec compliance above (avoid duplication).",
            "  3. DROP style preferences, 'consider extracting X' refactor suggestions, "
            "vague architectural concerns without a defect prediction.",
            "  4. DROP speculative gaps that don't predict a measurable failure.",
            "  5. KEEP gaps that predict a measurable defect AND propose a concrete 1-line fix.",
            "",
            "CONSERVATIVE BIAS: when uncertain, KEEP the gap. False negatives hurt more "
            "than false positives. If you can't decide, keep it.",
            "",
            "For each surviving gap, produce this shape:",
            '  {"summary": "...", "file": "...", "line": <int|null>, "symbol": "...", '
            '"predicted_defect": "...", "fix_recommendation": "...", '
            '"severity": "critical"|"architectural"|"important"|"minor", '
            '"confidence": 0.0-1.0}',
            "",
            "Output a SINGLE JSON object and NOTHING ELSE (no prose, no tool calls "
            "to write files):",
            "{",
            '  "curated_gaps": [...],',
            '  "dropped_count": <int>,',
            '  "dropped_reasons": {',
            '    "unanchored": <int>, "spec_duplicate": <int>,',
            '    "trivial": <int>, "speculative": <int>',
            "  },",
            '  "critical_gaps": <count where severity=="critical">,',
            '  "architectural_gaps": <count where severity=="architectural">,',
            '  "important_gaps": <count where severity=="important">,',
            '  "minor_gaps": <count where severity=="minor">,',
            '  "deferred_gaps": 0,',
            '  "total_gaps_found": <len(curated_gaps)>,',
            '  "converged": <true if total_gaps_found == 0>,',
            '  "curated": true',
            "}",
            "Begin with `{` and end with `}`.",
        ]
    )
    return "\n".join(sections)


def parse_curator_output(raw_text: str) -> dict[str, Any] | None:
    """Defensive JSON parse — returns None on failure (caller falls back to raw)."""
    if not raw_text:
        return None
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        data = json.loads(raw_text[start:end])
        # Sanity: must have curated_gaps as a list
        if not isinstance(data.get("curated_gaps"), list):
            return None
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def run_gap_curator(
    raw_gap_report: dict,
    phase: str,
    project_root: Path,
    spec_path: Path | None,
    compliance_path: Path | None,
    plan_sha: str,
    run_claude_fn: Callable,
    model: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any] | None:
    """Run the curator on a raw gap report. Returns the curated dict on success,
    None on any failure (caller should fall back to raw)."""

    spec_text = _read_text_truncated(spec_path, SPEC_TRUNCATE_BYTES) if spec_path else ""
    compliance_text = ""
    if compliance_path and compliance_path.exists():
        compliance_text = _read_text_truncated(compliance_path, 10_000)

    files = _extract_referenced_files(raw_gap_report)
    diff_text = _read_focused_diff(project_root, files, plan_sha)

    prompt = build_curator_prompt(
        phase=phase,
        raw_gap_report=raw_gap_report,
        spec_text=spec_text,
        compliance_text=compliance_text,
        diff_text=diff_text,
    )

    try:
        result = run_claude_fn(
            prompt,
            model=model,
            effort="medium",
            budget=budget,
            cwd=cwd,
            system_prompt=system_prompt,
            fallback_model=fallback_model,
        )
    except Exception:
        logger.warning("gap curator: claude call raised", exc_info=True)
        return None

    if getattr(result, "is_error", False):
        logger.warning("gap curator: claude returned is_error")
        return None

    parsed = parse_curator_output(getattr(result, "text", ""))
    if parsed is None:
        logger.warning("gap curator: failed to parse output as JSON")
        return None

    parsed.setdefault("cost_usd", getattr(result, "cost_usd", 0.0))
    parsed["cost_usd"] = parsed.get("cost_usd") or getattr(result, "cost_usd", 0.0)
    parsed.setdefault("curated", True)

    if output_path:
        try:
            tmp = output_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(output_path))
        except OSError:
            logger.warning("gap curator: failed to write output_path")

    return parsed
