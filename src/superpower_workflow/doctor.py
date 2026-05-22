"""Pre-flight health checks for superpower-workflow."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    ok: bool
    message: str


def run_checks(project_root: Path) -> list[CheckResult]:
    """Run pre-flight health checks and return results.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of CheckResult objects for each check.
    """
    results: list[CheckResult] = []
    claude_dir = project_root / ".claude"

    # Check 1: Claude Code installed
    if shutil.which("claude"):
        results.append(CheckResult(True, "Claude Code installed"))
    else:
        results.append(CheckResult(False, "Claude Code not installed"))

    # Check 2: workflow.json exists and valid
    config_path = claude_dir / "workflow.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            if "schema_version" in config and "spec" in config:
                results.append(CheckResult(True, "workflow.json valid"))
            else:
                results.append(CheckResult(False, "workflow.json missing required fields"))
        except json.JSONDecodeError:
            results.append(CheckResult(False, "workflow.json is not valid JSON"))
    else:
        results.append(CheckResult(False, "workflow.json not found - run `sw init`"))

    return results
