"""Stop hook that determines convergence based on phase state and gap report."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PHASE_FILE = ".workflow-phase.json"
GAP_REPORT_FILE = ".gap-report.json"


def _is_stuck(current_summaries: list[str], previous_summaries: list[str]) -> bool:
    """Detect stuck convergence loops via fuzzy gap matching."""
    if not previous_summaries or not current_summaries:
        return False

    def normalize(s: str) -> str:
        s = re.sub(r":\d+", "", s)
        s = re.sub(r"\S+/", "", s)
        return s.strip().lower()

    current_normalized = {normalize(s) for s in current_summaries}
    previous_normalized = {normalize(s) for s in previous_summaries}
    if len(current_normalized) == 0:
        return False
    overlap = current_normalized & previous_normalized
    return len(overlap) / len(current_normalized) > 0.8


def compute_exit_code(claude_dir: Path) -> int:
    """Core logic. Returns 0 (allow stop) or 2 (block stop)."""
    phase_path = claude_dir / PHASE_FILE
    gap_path = claude_dir / GAP_REPORT_FILE

    if not phase_path.exists():
        return 0

    try:
        phase = json.loads(phase_path.read_text())
    except (json.JSONDecodeError, TypeError):
        return 0

    iteration = phase.get("iteration", 0)
    max_iterations = phase.get("max_iterations", 5)

    if iteration >= max_iterations:
        return 0

    if not gap_path.exists():
        _increment_iteration(phase_path, phase)
        return 2

    try:
        gap_report = json.loads(gap_path.read_text())
    except (json.JSONDecodeError, TypeError):
        _increment_iteration(phase_path, phase)
        return 2

    current_summaries = gap_report.get("gap_summaries", [])
    prev_summaries = phase.get("previous_gap_summaries", [])
    if _is_stuck(current_summaries, prev_summaries):
        return 0

    critical_gaps = gap_report.get("critical_gaps", 0)
    important_gaps = gap_report.get("important_gaps", 0)
    tests_green = gap_report.get("tests_green", True)
    lint_clean = gap_report.get("lint_clean", True)
    phase_type = phase.get("phase", "")
    previous_important_gaps = phase.get("previous_important_gaps")

    converged = False

    if phase_type == "review":
        converged = critical_gaps == 0 and important_gaps == 0 and tests_green and lint_clean
    elif phase_type == "ultrathink":
        if previous_important_gaps is None:
            converged = critical_gaps == 0 and important_gaps <= 3
        else:
            converged = critical_gaps == 0 and (
                important_gaps <= 3 or important_gaps <= previous_important_gaps * 0.5
            )

    if converged:
        return 0

    _increment_iteration(
        phase_path,
        phase,
        current_important=important_gaps,
        current_summaries=current_summaries,
    )
    return 2


def _increment_iteration(
    phase_path: Path,
    phase: dict,
    current_important: int | None = None,
    current_summaries: list[str] | None = None,
) -> None:
    """Increment iteration counter and optionally update gap tracking."""
    phase["iteration"] = phase.get("iteration", 0) + 1
    if current_important is not None:
        phase["previous_important_gaps"] = current_important
    if current_summaries is not None:
        phase["previous_gap_summaries"] = current_summaries
    tmp = phase_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(phase, indent=2))
    os.replace(str(tmp), str(phase_path))


def main() -> None:
    claude_dir = Path(".claude")
    code = compute_exit_code(claude_dir)
    if code == 2:
        print("Gaps remain. Continue analyzing and fixing.", file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
