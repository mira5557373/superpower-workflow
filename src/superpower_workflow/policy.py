from __future__ import annotations

import ast
import subprocess
from pathlib import Path


class PolicyEngine:
    def __init__(self, policies: dict) -> None:
        self._policies = policies

    def check(
        self,
        cwd: Path,
        files: list[Path] | None = None,
        base_sha: str | None = None,
    ) -> tuple[bool, list[str]]:
        if files is None:
            files = self._changed_files(cwd, base_sha)
        violations: list[str] = []
        max_lines = self._policies.get("max_file_lines")
        if max_lines is not None:
            violations.extend(self._check_max_file_lines(files, max_lines))
        banned = self._policies.get("banned_imports")
        if banned is not None:
            violations.extend(self._check_banned_imports(files, banned))
        return len(violations) == 0, violations

    def _changed_files(self, cwd: Path, base_sha: str | None) -> list[Path]:
        if not base_sha:
            return []
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{base_sha}..HEAD"],
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=10,
            )
            if result.returncode != 0:
                return []
            return [cwd / f.strip() for f in result.stdout.splitlines() if f.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def _check_max_file_lines(self, files: list[Path], max_lines: int) -> list[str]:
        violations: list[str] = []
        for f in files:
            if not f.exists() or f.suffix != ".py":
                continue
            try:
                count = len(f.read_text(encoding="utf-8").splitlines())
                if count > max_lines:
                    violations.append(
                        f"max_file_lines: {f.name} has {count} lines (limit {max_lines})"
                    )
            except OSError:
                continue
        return violations

    def _check_banned_imports(self, files: list[Path], banned: list[str]) -> list[str]:
        violations: list[str] = []
        banned_set = set(banned)
        for f in files:
            if not f.exists() or f.suffix != ".py":
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        full = f"{node.module}.{alias.name}"
                        if full in banned_set:
                            violations.append(f"banned_imports: {f.name} imports {full}")
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    full = f"{node.value.id}.{node.attr}"
                    if full in banned_set:
                        violations.append(f"banned_imports: {f.name} uses {full}")
        return violations
