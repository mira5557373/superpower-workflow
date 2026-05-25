from __future__ import annotations

import subprocess

SECTION_TITLES = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "test": "Tests",
    "chore": "Chores",
    "style": "Style",
    "other": "Other",
}

GROUP_KEYS = tuple(SECTION_TITLES.keys())


def generate_changelog(since_tag: str | None = None, cwd: str = ".") -> str:
    cmd = ["git", "log", "--format=%H %s"]
    if since_tag:
        cmd.append(f"{since_tag}..HEAD")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    if result.returncode != 0:
        return ""
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    groups = parse_commits(lines)
    return render_changelog(groups)


def parse_commits(lines: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {k: [] for k in GROUP_KEYS}
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, msg = parts
        prefix = msg.split(":")[0].split("(")[0].strip().lower()
        bucket = prefix if prefix in groups else "other"
        groups[bucket].append(f"- {msg} ({sha[:7]})")
    return groups


def render_changelog(groups: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for key, title in SECTION_TITLES.items():
        items = groups.get(key, [])
        if items:
            lines.append(f"### {title}\n")
            lines.extend(items)
            lines.append("")
    return "\n".join(lines).strip()
