#!/usr/bin/env python3
"""Install skills, hooks, and commands to ~/.claude/."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).parent
HOME_CLAUDE = Path.home() / ".claude"

COPIES = [
    ("skills/ultrathink-gap-analysis", "skills/ultrathink-gap-analysis"),
    ("skills/post-impl-review", "skills/post-impl-review"),
    ("skills/production-readiness-review", "skills/production-readiness-review"),
    ("commands/ultrathink.md", "commands/ultrathink.md"),
]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_file():
            target = dst / item.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and file_hash(item) == file_hash(target):
                print(f"  skip (identical): {target}")
                continue
            shutil.copy2(item, target)
            print(f"  copied: {target}")


def register_hook() -> None:
    settings_path = HOME_CLAUDE / "settings.json"
    settings = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])
    hook_cmd = "python -m superpower_workflow.hooks.convergence_gate"
    already = any(hook_cmd in str(entry) for entry in stop_hooks)
    if not already:
        stop_hooks.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": hook_cmd, "timeout": 30}],
            }
        )
        settings_path.write_text(json.dumps(settings, indent=2))
        print(f"  registered Stop hook in {settings_path}")
    else:
        print("  Stop hook already registered")


def main() -> None:
    print("Installing superpower-workflow components to ~/.claude/")
    for src_rel, dst_rel in COPIES:
        src = REPO_ROOT / src_rel
        dst = HOME_CLAUDE / dst_rel
        if src.is_dir():
            copy_tree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and file_hash(src) == file_hash(dst):
                print(f"  skip (identical): {dst}")
            else:
                shutil.copy2(src, dst)
                print(f"  copied: {dst}")
    register_hook()
    print("Done.")


if __name__ == "__main__":
    main()
