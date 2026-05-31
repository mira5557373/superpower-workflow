#!/usr/bin/env python3
"""Complexity audit script (v1.2.0 lite, T2.0.3).

Walks the package source and reports any function exceeding configurable
thresholds for:
  - line count (default 100)
  - cyclomatic complexity (default 15)
  - nesting depth (default 4)

Exits 0 when all thresholds pass, 1 otherwise. Run in CI to prevent regression.

Usage:
  python scripts/complexity_audit.py [--max-lines N] [--max-cc N] [--max-nesting N]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

DEFAULT_MAX_LINES = 100
DEFAULT_MAX_CC = 15
DEFAULT_MAX_NESTING = 4
PACKAGE_DIR = Path(__file__).resolve().parent.parent / "src" / "superpower_workflow"


_CONTROL_FLOW = (
    ast.If,
    ast.For,
    ast.While,
    ast.With,
    ast.Try,
    ast.AsyncFor,
    ast.AsyncWith,
)


def _max_nesting(node: ast.AST, current: int = 0) -> int:
    """Recursive max-nesting depth for an ast node.

    v1.3.1 HIGH #6 fix: Python's AST models `elif` as a nested `If` inside
    `If.orelse`. A flat `if/elif/elif/else` would otherwise be counted as
    depth=4. We walk if-chains iteratively, charging only ONE nesting level
    for the whole chain.

    Nested function bodies are NOT recursed into — they're scored separately
    by `audit_function`, so the outer function's nesting doesn't inherit
    inner function depth.
    """
    depth = current

    # Special-case If chains: drain the elif chain iteratively so the whole
    # chain counts as ONE nesting level. Genuine nested If inside a body
    # still bumps because the body recursion goes through `_descend_stmt`.
    if isinstance(node, ast.If):
        for stmt in node.body:
            depth = max(depth, _descend_stmt(stmt, current))
        orelse = node.orelse
        while len(orelse) == 1 and isinstance(orelse[0], ast.If):
            elif_node = orelse[0]
            for stmt in elif_node.body:
                depth = max(depth, _descend_stmt(stmt, current))
            orelse = elif_node.orelse
        for stmt in orelse:
            depth = max(depth, _descend_stmt(stmt, current))
        return depth

    for child in ast.iter_child_nodes(node):
        # Skip nested function/lambda bodies — they audit themselves.
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        depth = max(depth, _descend_stmt(child, current))
    return depth


def _descend_stmt(stmt: ast.AST, current: int) -> int:
    """Recurse into one statement, bumping `current` only when stmt is itself
    a control-flow construct."""
    if isinstance(stmt, _CONTROL_FLOW):
        return _max_nesting(stmt, current + 1)
    return _max_nesting(stmt, current)


def _cyclomatic_complexity(node: ast.AST) -> int:
    """Approximate cyclomatic complexity: 1 + count of branch points."""
    count = 1
    for child in ast.walk(node):
        if isinstance(child, ast.If | ast.For | ast.While | ast.And | ast.Or | ast.ExceptHandler):
            count += 1
        elif isinstance(child, ast.BoolOp):
            count += len(child.values) - 1
    return count


def audit_function(node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> dict:
    """Compute metrics for one function."""
    line_count = (node.end_lineno or node.lineno) - node.lineno + 1
    cc = _cyclomatic_complexity(node)
    nesting = _max_nesting(node)
    return {
        "name": node.name,
        "lineno": node.lineno,
        "lines": line_count,
        "cc": cc,
        "nesting": nesting,
    }


def audit_file(path: Path) -> list[dict]:
    """Audit every function/method in the file."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    results: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            r = audit_function(node, source)
            r["file"] = str(path.relative_to(PACKAGE_DIR.parent.parent))
            results.append(r)
    return results


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    p.add_argument("--max-cc", type=int, default=DEFAULT_MAX_CC)
    p.add_argument("--max-nesting", type=int, default=DEFAULT_MAX_NESTING)
    p.add_argument(
        "--baseline",
        action="store_true",
        help="Report current values without failing — for setting initial thresholds",
    )
    args = p.parse_args()

    if not PACKAGE_DIR.exists():
        print(f"Package directory not found: {PACKAGE_DIR}", file=sys.stderr)
        return 1

    all_metrics: list[dict] = []
    for py in PACKAGE_DIR.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        all_metrics.extend(audit_file(py))

    violations = [
        m
        for m in all_metrics
        if m["lines"] > args.max_lines or m["cc"] > args.max_cc or m["nesting"] > args.max_nesting
    ]

    if args.baseline:
        print(f"\nFunctions audited: {len(all_metrics)}")
        top10 = sorted(all_metrics, key=lambda m: -m["lines"])[:10]
        print("\nTop 10 by line count:")
        for m in top10:
            print(
                f"  {m['file']}:{m['lineno']}  {m['name']}  "
                f"lines={m['lines']} cc={m['cc']} nest={m['nesting']}"
            )
        return 0

    if violations:
        print(f"\nComplexity audit FAILED: {len(violations)} violation(s)\n")
        print(
            f"Thresholds: max_lines={args.max_lines} "
            f"max_cc={args.max_cc} max_nesting={args.max_nesting}\n"
        )
        for v in violations:
            reasons = []
            if v["lines"] > args.max_lines:
                reasons.append(f"lines={v['lines']}")
            if v["cc"] > args.max_cc:
                reasons.append(f"cc={v['cc']}")
            if v["nesting"] > args.max_nesting:
                reasons.append(f"nest={v['nesting']}")
            print(f"  {v['file']}:{v['lineno']}  {v['name']}  ({', '.join(reasons)})")
        return 1

    print(f"Complexity audit OK ({len(all_metrics)} functions audited)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
