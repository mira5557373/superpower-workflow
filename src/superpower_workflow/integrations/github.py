from __future__ import annotations

import json
import re
import subprocess
from typing import Any


def parse_issue_ref(ref: str, default_repo: str = "") -> tuple[str, int]:
    ref = ref.strip().lstrip("#")
    if "#" in ref:
        parts = ref.split("#", 1)
        repo = parts[0] or default_repo
        number = int(parts[1])
    else:
        repo = default_repo
        number = int(ref)
    return repo, number


def fetch_issue(issue_ref: str, default_repo: str = "", cwd: str = ".") -> dict[str, Any]:
    repo, number = parse_issue_ref(issue_ref, default_repo)
    cmd = [
        "gh",
        "issue",
        "view",
        str(number),
        "--json",
        "title,body,labels,assignees",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found. Install from https://cli.github.com/") from None
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch issue {issue_ref}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50]


def issue_to_milestone(
    issue_data: dict[str, Any],
    label_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    title = issue_data.get("title", "untitled")
    ms: dict[str, Any] = {
        "name": _slugify(title),
        "description": title,
        "spec_sections": issue_data.get("body", ""),
        "depends_on": [],
    }
    if label_map:
        labels = [lb.get("name", "") for lb in issue_data.get("labels", [])]
        for label in labels:
            if label in label_map:
                ms["type"] = label_map[label]
                break
        if "type" not in ms:
            ms["type"] = ""
    return ms
