from __future__ import annotations

import subprocess
from pathlib import Path

from superpower_workflow.runner import run_claude


def generate_readme(
    project_root: Path,
    model: str = "opus",
    effort: str = "high",
    budget: float = 25,
    template: str | None = None,
    sections: list[str] | None = None,
    cwd: str = ".",
) -> str:
    context = gather_context(project_root, cwd)

    section_hint = ""
    if sections:
        section_hint = f"Include these sections: {', '.join(sections)}. "

    template_hint = ""
    if template:
        template_path = project_root / template
        if template_path.exists():
            content = template_path.read_text(encoding="utf-8")[:2000]
            template_hint = f"\nUse this template as base structure:\n{content}"

    prompt = (
        f"Update README.md based on this context. Keep existing sections, update stats. "
        f"{section_hint}{template_hint}\n\n"
        f"Context:\n{context}\n\n"
        f"Output only the README.md content, nothing else."
    )

    result = run_claude(prompt, model=model, effort=effort, budget=budget, cwd=cwd)
    if result.is_error:
        return ""
    return result.text.strip()


def gather_context(project_root: Path, cwd: str) -> str:
    parts: list[str] = []

    claude_md = project_root / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")[:3000]
        parts.append(f"## CLAUDE.md\n{content}")

    git_log = subprocess.run(
        ["git", "log", "--oneline", "-5"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )
    if git_log.returncode == 0 and git_log.stdout.strip():
        parts.append(f"## Recent commits\n{git_log.stdout.strip()}")

    return "\n\n".join(parts)
