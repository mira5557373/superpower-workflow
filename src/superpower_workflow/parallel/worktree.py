from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

BRANCH_PREFIX = "sw-parallel/"


@dataclass
class WorktreeInfo:
    name: str
    path: Path
    branch: str
    head_sha: str = ""


@dataclass
class MergeResult:
    success: bool
    merged_branch: str
    conflicts: list[str]
    message: str = ""


class WorktreeManager:
    def __init__(self, repo_root: Path, worktree_dir: Path | None = None) -> None:
        self.repo_root = repo_root
        self.worktree_dir = worktree_dir or repo_root / ".worktrees"

    def create(self, name: str, base_ref: str = "HEAD") -> WorktreeInfo:
        branch = f"{BRANCH_PREFIX}{name}"
        wt_path = self.worktree_dir / name
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(wt_path), base_ref],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return WorktreeInfo(name=name, path=wt_path, branch=branch)

    def remove(self, name: str, prune_branch: bool = False) -> None:
        wt_path = self.worktree_dir / name
        subprocess.run(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=60,
        )
        if prune_branch:
            branch = f"{BRANCH_PREFIX}{name}"
            subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                timeout=10,
            )

    def list(self) -> list[WorktreeInfo]:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return _parse_porcelain(result.stdout)

    def cleanup_all(self) -> None:
        for wt in self.list():
            if wt.branch.startswith(BRANCH_PREFIX):
                self.remove(wt.name, prune_branch=True)

    def merge(self, name: str, target_branch: str = "HEAD") -> MergeResult:
        branch = f"{BRANCH_PREFIX}{name}"
        result = subprocess.run(
            ["git", "merge", branch, "--no-edit"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
            timeout=120,
        )
        if result.returncode == 0:
            return MergeResult(
                success=True,
                merged_branch=branch,
                conflicts=[],
                message=result.stdout.strip(),
            )
        conflicts = _parse_conflicts(result.stdout + result.stderr)
        subprocess.run(
            ["git", "merge", "--abort"],
            capture_output=True,
            cwd=str(self.repo_root),
            timeout=10,
        )
        return MergeResult(
            success=False,
            merged_branch=branch,
            conflicts=conflicts,
            message=result.stderr.strip(),
        )


def _parse_porcelain(output: str) -> list[WorktreeInfo]:
    trees: list[WorktreeInfo] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                path = Path(current.get("worktree", ""))
                branch = current.get("branch", "").replace("refs/heads/", "")
                name = (
                    branch.replace(BRANCH_PREFIX, "")
                    if branch.startswith(BRANCH_PREFIX)
                    else path.name
                )
                trees.append(
                    WorktreeInfo(
                        name=name,
                        path=path,
                        branch=branch,
                        head_sha=current.get("HEAD", ""),
                    )
                )
                current = {}
        elif line.startswith("worktree "):
            current["worktree"] = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD ") :]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :]
    return trees


def _parse_conflicts(output: str) -> list[str]:
    conflicts = []
    for line in output.splitlines():
        if line.startswith("CONFLICT"):
            conflicts.append(line)
    return conflicts
