from __future__ import annotations

import ast
import re
from pathlib import Path


def generate_mermaid(src_dir: Path, project_prefix: str | None = None) -> str:
    if project_prefix is None:
        project_prefix = src_dir.name

    edges: set[tuple[str, str]] = set()
    for py_file in sorted(src_dir.rglob("*.py")):
        module = path_to_module(py_file, src_dir.parent)
        for imp in parse_imports(py_file):
            if imp.startswith(project_prefix):
                edges.add((module, imp))

    lines = ["graph TD"]
    for src, dst in sorted(edges):
        safe_src = _sanitize_id(src)
        safe_dst = _sanitize_id(dst)
        lines.append(f'    {safe_src}["{src}"] --> {safe_dst}["{dst}"]')
    return "\n".join(lines)


def path_to_module(py_file: Path, base: Path) -> str:
    rel = py_file.relative_to(base)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")
    return ".".join(parts)


def parse_imports(py_file: Path) -> list[str]:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _sanitize_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)
