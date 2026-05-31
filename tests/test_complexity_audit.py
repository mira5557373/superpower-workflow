"""Tests for the complexity audit script (v1.2.0 T2.0.3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "complexity_audit.py"


# v1.3.1 HIGH #6 regression: elif over-counting
def _load_audit_module():
    """Import the complexity_audit script as a module for unit-testing helpers."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("complexity_audit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMaxNestingElif:
    """v1.3.1 HIGH #6: `_max_nesting` previously counted each `elif` as a
    nested `If` (because Python's AST models elif via If.orelse). A flat
    if/elif/elif/elif/else reported nesting=4 instead of 1."""

    def setup_method(self):
        import ast

        self.audit = _load_audit_module()
        self.ast = ast

    def _parse_function(self, source: str):
        tree = self.ast.parse(source)
        return tree.body[0]

    def test_flat_if_elif_chain_is_one_level(self):
        src = """
def f(x):
    if x == 1:
        return 'a'
    elif x == 2:
        return 'b'
    elif x == 3:
        return 'c'
    elif x == 4:
        return 'd'
    else:
        return 'z'
"""
        fn = self._parse_function(src)
        depth = self.audit._max_nesting(fn)
        # The whole if/elif chain inside the function counts as ONE nesting
        # level (the function body has depth 0; the if-chain bumps to 1).
        assert depth == 1, f"flat elif chain should be nesting=1, got {depth}"

    def test_genuinely_nested_if_counts_each_level(self):
        """Real nesting (if inside body of if) still counts."""
        src = """
def f(x):
    if x:
        if x > 1:
            if x > 2:
                return 'deep'
    return None
"""
        fn = self._parse_function(src)
        depth = self.audit._max_nesting(fn)
        # Three actually-nested ifs → depth 3
        assert depth == 3, f"3-deep nested ifs should be nesting=3, got {depth}"

    def test_async_for_with_treated_as_nesting(self):
        src = """
async def f(items):
    async for x in items:
        async with x as ctx:
            print(ctx)
"""
        fn = self._parse_function(src)
        depth = self.audit._max_nesting(fn)
        assert depth == 2, f"async for + async with should be nesting=2, got {depth}"

    def test_nested_function_not_double_counted(self):
        """Inner function body is audited separately; outer function shouldn't
        inherit inner's depth."""
        src = """
def outer():
    def inner():
        if True:
            if True:
                if True:
                    return 1
    return inner
"""
        fn = self._parse_function(src)
        depth = self.audit._max_nesting(fn)
        # Outer function has nothing nested; inner is scored separately.
        assert depth == 0, f"outer should not inherit inner nesting; got {depth}"


class TestComplexityAuditPassesAtV120Ceilings:
    """The v1.2.0 ceilings (510/50/7) grandfather current code; CI uses these."""

    def test_audit_passes_at_ceilings(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--max-lines",
                "510",
                "--max-cc",
                "50",
                "--max-nesting",
                "7",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"Complexity audit failed at v1.2.0 ceilings.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "OK" in result.stdout

    def test_audit_fails_at_target_ceilings(self):
        """At the v1.2.1 targets (100/15/4), known violations exist —
        confirms the script detects them."""
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--max-lines",
                "100",
                "--max-cc",
                "15",
                "--max-nesting",
                "4",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 1
        assert "FAILED" in result.stdout
        # _run_milestone is the canonical violator
        assert "_run_milestone" in result.stdout

    def test_baseline_reports_without_failing(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--baseline"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "Functions audited" in result.stdout
        assert "Top 10" in result.stdout
