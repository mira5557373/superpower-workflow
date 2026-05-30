"""Tests for the complexity audit script (v1.2.0 T2.0.3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "complexity_audit.py"


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
