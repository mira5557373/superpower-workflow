"""v1.3.3 #19: keep session-report files (OVERNIGHT-*, REVIEW-REPORT-*)
under docs/sessions/, never at the repo root.

Pre-v1.3.3 they accumulated at root — 3 files at the time of v1.3.2.
This regression test fails CI if anyone reintroduces the pattern.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestSessionReportsLiveUnderDocsSessions:
    def test_no_overnight_files_at_repo_root(self):
        offenders = sorted(ROOT.glob("OVERNIGHT*.md"))
        assert not offenders, (
            "Session reports must live under docs/sessions/. Found at root: "
            + ", ".join(str(p.name) for p in offenders)
        )

    def test_no_review_report_files_at_repo_root(self):
        offenders = sorted(ROOT.glob("REVIEW-REPORT-*.md"))
        assert not offenders, (
            "Review reports must live under docs/sessions/. Found at root: "
            + ", ".join(str(p.name) for p in offenders)
        )

    def test_docs_sessions_directory_exists(self):
        assert (ROOT / "docs" / "sessions").is_dir(), (
            "docs/sessions/ must exist as the canonical home for session reports."
        )

    def test_docs_sessions_readme_present(self):
        """A README in docs/sessions/ documents the naming convention so
        future contributors know where to put new reports."""
        assert (ROOT / "docs" / "sessions" / "README.md").exists()


class TestNoEmDashInUserFacingStrings:
    """v1.3.3 cosmetic: em-dash (U+2014) inside `print()` calls or
    `RecommendationReport.rationale` assignments raises UnicodeEncodeError
    on Windows console (cp1252). Comments and docstrings are fine (not
    emitted to stdout); only stdout-bound strings need to stay ASCII-safe.
    """

    def test_no_em_dash_in_print_calls(self):
        """Scan src/ for `print(...)` calls containing the em-dash literal."""
        import re

        offenders = []
        src = ROOT / "src" / "superpower_workflow"
        for py in src.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for m in re.finditer(r"print\([^)]*—[^)]*\)", text):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{py.relative_to(src)}:{line}")
        assert not offenders, (
            "Found em-dash (U+2014) inside print() call(s):\n  "
            + "\n  ".join(offenders)
            + "\nReplace with '--' so Windows console renders cleanly."
        )

    def test_no_em_dash_in_recommender_rationale(self):
        """Specific spot-check on RecommendationReport.rationale, which
        gets printed by `sw recommend-model`."""
        recommender_py = ROOT / "src" / "superpower_workflow" / "recommender.py"
        text = recommender_py.read_text(encoding="utf-8")
        # Crude but effective: find every line assigning to `.rationale` and
        # check the assigned RHS doesn't contain em-dash.
        for line_no, line in enumerate(text.splitlines(), 1):
            if ("rationale =" in line or "rationale = (" in line) and "—" in line:
                raise AssertionError(
                    f"recommender.py:{line_no} sets rationale containing em-dash. "
                    "Replace with '--' for Windows console safety."
                )
