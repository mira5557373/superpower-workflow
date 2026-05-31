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

    def test_v132_inner_function_inside_if_not_double_counted(self):
        """v1.3.2 #4: When the inner def lives inside an `if` body, the v1.3.1
        fix's special-cased If-chain handling bypassed the nested-fn filter
        and inflated the outer depth via the inner's branches.
        """
        src = """
def outer(x):
    if x:
        def inner():
            if True:
                if True:
                    if True:
                        return 99
"""
        fn = self._parse_function(src)
        depth = self.audit._max_nesting(fn)
        # Outer's depth is 1 (the `if x:` wrapping the inner def). Inner's
        # internal nesting should not roll up.
        assert depth == 1, f"expected outer depth=1, got {depth}"

    def test_v132_lambda_inside_for_not_double_counted(self):
        """v1.3.2 #4: lambdas should be skipped just like functions."""
        src = """
def outer(xs):
    for x in xs:
        f = lambda y: y if y > 0 else -y
        yield f(x)
"""
        fn = self._parse_function(src)
        depth = self.audit._max_nesting(fn)
        # For body = 1 level. The lambda inside should not bump further
        # (the ternary inside the lambda would not count anyway because
        # _max_nesting tracks statement-level nesting, not expressions).
        assert depth == 1


class TestCyclomaticComplexityV132:
    """v1.3.2 #21: _cyclomatic_complexity must skip nested function bodies
    and recognize Match/match_case/IfExp/AsyncFor/AsyncWith.
    """

    def setup_method(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("complexity_audit", SCRIPT)
        self.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.audit)

    def _parse_function(self, src):
        import ast as _ast

        tree = _ast.parse(src)
        for n in _ast.walk(tree):
            if isinstance(n, _ast.FunctionDef | _ast.AsyncFunctionDef):
                return n
        raise AssertionError("no function in fixture")

    def test_cc_skips_nested_function_body(self):
        """Pre-fix `ast.walk` recursed into inner function bodies, double-
        counting their branches against the outer function."""
        src = """
def outer():
    def inner():
        if 1:
            if 1:
                if 1:
                    if 1:
                        if 1:
                            return 1
    return inner
"""
        fn = self._parse_function(src)
        # Outer has zero branch points of its own → CC == 1.
        assert self.audit._cyclomatic_complexity(fn) == 1

    def test_cc_counts_match_arms(self):
        """v1.3.2 #21: pattern matching (PEP 634) was missing from the
        branch tuple — `match`/`case` arms now count."""
        src = """
def routing(x):
    match x:
        case 1:
            return "one"
        case 2:
            return "two"
        case _:
            return "other"
"""
        fn = self._parse_function(src)
        # 1 baseline + 1 Match + 3 match_case = 5
        cc = self.audit._cyclomatic_complexity(fn)
        assert cc == 5, f"expected match-case CC=5, got {cc}"

    def test_cc_counts_ifexp_ternary(self):
        src = """
def pick(x):
    return x if x > 0 else -x
"""
        fn = self._parse_function(src)
        # 1 baseline + 1 IfExp = 2
        assert self.audit._cyclomatic_complexity(fn) == 2

    def test_cc_counts_async_for_and_async_with(self):
        src = """
async def driver(items):
    async with open() as f:
        async for x in items:
            f.write(x)
"""
        fn = self._parse_function(src)
        # 1 baseline + 1 AsyncWith + 1 AsyncFor = 3
        assert self.audit._cyclomatic_complexity(fn) == 3


class TestComplexityAuditPassesAtV120Ceilings:
    """The v1.2.0 ceilings grandfather current code; CI uses these.

    v1.3.2 #21 widened the CC formula to also count `Match`, `match_case`,
    `IfExp`, `AsyncFor`, `AsyncWith` — so existing code reports slightly
    higher CC under the new (more accurate) metric. The CC ceiling is bumped
    from 50 → 55 to absorb the recalibration without forcing immediate
    refactors. v1.2.1 targets (15) still apply for new code.
    """

    def test_audit_passes_at_ceilings(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--max-lines",
                "510",
                "--max-cc",
                "55",
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
