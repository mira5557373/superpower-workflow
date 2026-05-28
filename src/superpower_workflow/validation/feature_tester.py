"""Feature verification tester: independent claude -p call to verify features work."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def build_verification_prompt(compliance_path: str) -> str:
    return (
        f"Read {compliance_path}.\n"
        f'For each requirement marked "implemented":\n'
        f"  1. Find an existing test that verifies this feature\n"
        f"  2. If no test exists, write a verification test\n"
        f"  3. Run all verification tests\n"
        f"Report which features pass and which fail.\n"
        f'Only verify objectively testable features. Mark subjective ones as "manual_review".\n'
        f"Write .claude/.feature-verification.json with this exact schema:\n"
        f'{{"total_features": N, "verified_working": N, "broken": N, "manual_review": N, '
        f'"details": [{{"feature": "...", "status": "pass"|"fail"|"manual_review", '
        f'"test": "test_file.py::test_name", "reason": "..."}}]}}\n'
        f"IMPORTANT: Output ONLY the JSON content, nothing else."
    )


def parse_verification_output(raw_text: str) -> dict[str, Any]:
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_text[start:end])
            return {
                "total_features": data.get("total_features", 0),
                "verified_working": data.get("verified_working", 0),
                "broken": data.get("broken", 0),
                "manual_review": data.get("manual_review", 0),
                "details": data.get("details", []),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return {
        "total_features": 0,
        "verified_working": 0,
        "broken": 0,
        "manual_review": 0,
        "details": [],
    }


def run_feature_verification(
    compliance_path: Path,
    run_claude_fn: Callable,
    model: str,
    budget: float,
    cwd: str,
    system_prompt: str | None = None,
    fallback_model: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if not compliance_path.exists():
        return parse_verification_output("")

    prompt = build_verification_prompt(str(compliance_path))

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
        report = parse_verification_output("")
        report["cost_usd"] = result.cost_usd
        return report

    report = parse_verification_output(result.text)
    report["cost_usd"] = result.cost_usd

    if output_path:
        tmp = output_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(output_path))

    return report
