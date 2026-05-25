from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OutdatedDep:
    name: str
    current: str
    latest: str
    is_breaking: bool


@dataclass
class UpgradeResult:
    name: str
    upgraded: bool
    branch: str | None = None
    error: str = ""


def detect_package_manager(project_root: Path) -> str:
    if (project_root / "pyproject.toml").exists():
        return "pip"
    if (project_root / "requirements.txt").exists():
        return "pip"
    if (project_root / "package.json").exists():
        return "npm"
    if (project_root / "Cargo.toml").exists():
        return "cargo"
    return "unknown"


def is_major_bump(current: str, latest: str) -> bool:
    try:
        cur_major = int(current.split(".")[0])
        lat_major = int(latest.split(".")[0])
        return lat_major > cur_major
    except (ValueError, IndexError):
        return False


def list_outdated(package_manager: str, cwd: str = ".") -> list[OutdatedDep]:
    if package_manager == "pip":
        return _pip_outdated(cwd)
    elif package_manager == "npm":
        return _npm_outdated(cwd)
    return []


def _pip_outdated(cwd: str) -> list[OutdatedDep]:
    result = subprocess.run(
        ["pip", "list", "--outdated", "--format=json"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )
    if result.returncode != 0:
        return []
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    deps: list[OutdatedDep] = []
    for item in items:
        current = item.get("version", "0.0.0")
        latest = item.get("latest_version", "0.0.0")
        deps.append(
            OutdatedDep(
                name=item["name"],
                current=current,
                latest=latest,
                is_breaking=is_major_bump(current, latest),
            )
        )
    return deps


def _npm_outdated(cwd: str) -> list[OutdatedDep]:
    result = subprocess.run(
        ["npm", "outdated", "--json"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    deps: list[OutdatedDep] = []
    for name, info in items.items():
        current = info.get("current", "0.0.0")
        latest = info.get("latest", "0.0.0")
        deps.append(
            OutdatedDep(
                name=name,
                current=current,
                latest=latest,
                is_breaking=is_major_bump(current, latest),
            )
        )
    return deps


def perform_upgrade(dep: OutdatedDep, cwd: str = ".") -> UpgradeResult:
    if dep.is_breaking:
        branch = f"upgrade/{dep.name}-{dep.current}-to-{dep.latest}"
        checkout = subprocess.run(
            ["git", "checkout", "-b", branch],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        if checkout.returncode != 0:
            return UpgradeResult(name=dep.name, upgraded=False, error=checkout.stderr.strip())

        install = subprocess.run(
            ["pip", "install", f"{dep.name}=={dep.latest}"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        if install.returncode != 0:
            subprocess.run(["git", "checkout", "-"], capture_output=True, cwd=cwd, timeout=10)
            subprocess.run(
                ["git", "branch", "-D", branch], capture_output=True, cwd=cwd, timeout=10
            )
            return UpgradeResult(name=dep.name, upgraded=False, error=install.stderr.strip())

        return UpgradeResult(name=dep.name, upgraded=True, branch=branch)

    install = subprocess.run(
        ["pip", "install", f"{dep.name}=={dep.latest}"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )
    if install.returncode != 0:
        return UpgradeResult(name=dep.name, upgraded=False, error=install.stderr.strip())

    return UpgradeResult(name=dep.name, upgraded=True)
