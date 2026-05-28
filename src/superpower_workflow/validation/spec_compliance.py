"""Spec compliance checker: independent claude -p call to verify spec requirements."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def build_compliance_prompt(spec_path: str, spec_sections: str, module_dir: str) -> str:
    return (
        f"Read the spec at {spec_path}, focusing on sections {spec_sections}.\n"
        f"Read all files in {module_dir} and tests/.\n"
        f"For each requirement in the spec:\n"
        f"  1. Search the codebase for its implementation\n"
        f'  2. Rate: "implemented" (with file:function evidence) or "missing"\n'
        f"Write .claude/.spec-compliance.json with this exact schema:\n"
        f'{{"spec_path": "{spec_path}", "spec_sections": "{spec_sections}", '
        f'"total_requirements": N, "implemented": N, "missing": N, '
        f'"details": [{{"requirement": "...", "status": "implemented"|"missing", '
        f'"evidence": "file.py:function"}}]}}\n'
        f"IMPORTANT: Output ONLY the JSON content, nothing else."
    )


def parse_compliance_output(raw_text: str) -> dict[str, Any]:
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_text[start:end])
            return {
                "spec_path": data.get("spec_path", ""),
                "spec_sections": data.get("spec_sections", ""),
                "total_requirements": data.get("total_requirements", 0),
                "implemented": data.get("implemented", 0),
                "missing": data.get("missing", 0),
                "details": data.get("details", []),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return {
        "spec_path": "",
        "spec_sections": "",
        "total_requirements": 0,
        "implemented": 0,
        "missing": 0,
        "details": [],
    }


def run_spec_compliance(
    spec_path: str,
    spec_sections: str,
    module_dirs: list[str],
    run_claude_fn: Callable,
    model: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    module_dir = ", ".join(module_dirs) if module_dirs else "src/"
    prompt = build_compliance_prompt(spec_path, spec_sections, module_dir)

    result = run_claude_fn(
        prompt,
        model=model,
        effort="high",
        budget=budget,
        cwd=cwd,
        system_prompt=system_prompt,
        fallback_model=fallback_model,
    )

    if result.is_error:
        report = parse_compliance_output("")
        report["cost_usd"] = result.cost_usd
        return report

    report = parse_compliance_output(result.text)
    report["cost_usd"] = result.cost_usd

    if output_path:
        tmp = output_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(output_path))

    return report
