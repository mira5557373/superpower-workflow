"""Pre-flight health checks for superpower-workflow."""

from __future__ import annotations

import importlib
import json
import pkgutil
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    ok: bool
    message: str


def _experimental_modules() -> list[str]:
    """v1.3.3 #11: discover modules in the sw package that advertise
    `__experimental__ = True`. Surfaces these to the user via `sw doctor`
    so the marker is no longer dead code — it actually informs operators.

    Walks `superpower_workflow.*` once and instantiates `__experimental__`
    via getattr. Missing-attribute defaults to False; import failures are
    swallowed so doctor stays robust on partial installs.
    """
    import superpower_workflow

    flagged: list[str] = []
    for info in pkgutil.walk_packages(
        superpower_workflow.__path__,
        prefix="superpower_workflow.",
    ):
        try:
            mod = importlib.import_module(info.name)
        except Exception:
            continue
        if getattr(mod, "__experimental__", False):
            flagged.append(info.name)
    return sorted(flagged)


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

    # Check 3 (v1.3.3 #11): surface experimental modules so operators know
    # which surfaces are not production-grade yet. Informational only — does
    # NOT fail the doctor (no `ok=False`); experimental code is opt-in.
    flagged = _experimental_modules()
    if flagged:
        results.append(
            CheckResult(
                True,
                f"experimental modules (not production-ready): {', '.join(flagged)}",
            )
        )

    return results
