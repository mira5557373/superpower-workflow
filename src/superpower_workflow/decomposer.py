"""Two-pass spec to milestone decomposition via claude -p."""

from __future__ import annotations

import json
import re

from superpower_workflow.runner import run_claude

DECOMPOSE_PROMPT = """Read the spec at {spec_path}. Identify implementation milestones.
Rules:
- Each milestone: 10-25 tasks of TDD work (1-3 days)
- Group by dependency (foundations first)
- Each milestone independently testable
- Name format: {{phase}}-m{{N}}-{{short-name}}
Output ONLY a JSON array of milestones, each with: name, spec_sections, description, depends_on."""

VALIDATE_PROMPT = """Review these proposed milestones against the spec at {spec_path}.
Check: all spec sections covered? Dependencies correct? Sizes reasonable?
Fix any issues. Output ONLY the corrected JSON array.

Proposed milestones:
{milestones_json}"""


def decompose(spec_path: str, model: str, cwd: str) -> list[dict]:
    """Two-pass decomposition: propose then validate milestones."""
    # Pass 1: Propose milestones
    result = run_claude(
        DECOMPOSE_PROMPT.format(spec_path=spec_path),
        model=model,
        effort="max",
        budget=10.0,
        cwd=cwd,
    )
    if result.is_error:
        return []
    milestones = _extract_json_array(result.text)
    if not milestones:
        return []

    # Pass 2: Validate
    validate_result = run_claude(
        VALIDATE_PROMPT.format(
            spec_path=spec_path, milestones_json=json.dumps(milestones, indent=2)
        ),
        model=model,
        effort="max",
        budget=10.0,
        cwd=cwd,
    )
    if not validate_result.is_error:
        validated = _extract_json_array(validate_result.text)
        if validated:
            return validated
        print("  Warning: validation pass returned no milestones, using unvalidated results")
    else:
        print("  Warning: validation pass failed, using unvalidated results")
    return milestones


def _extract_json_array(text: str) -> list[dict]:
    """Extract JSON array from text, handling markdown code blocks."""
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []
