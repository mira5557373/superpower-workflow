from __future__ import annotations

import subprocess
from pathlib import Path


def build_api_docs(
    src_dir: Path,
    output_dir: Path,
    tool: str = "sphinx",
    cwd: str = ".",
) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)

    if tool == "sphinx":
        return _build_sphinx(src_dir, output_dir, cwd)
    elif tool == "mkdocs":
        return _build_mkdocs(cwd)
    else:
        raise ValueError(f"Unsupported docs tool: {tool}")


def _build_sphinx(src_dir: Path, output_dir: Path, cwd: str) -> bool:
    apidoc = subprocess.run(
        ["sphinx-apidoc", "-o", str(output_dir / "source"), str(src_dir)],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )
    if apidoc.returncode != 0:
        return False
    build = subprocess.run(
        ["sphinx-build", str(output_dir / "source"), str(output_dir / "build")],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )
    return build.returncode == 0


def _build_mkdocs(cwd: str) -> bool:
    result = subprocess.run(
        ["mkdocs", "build"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )
    return result.returncode == 0
