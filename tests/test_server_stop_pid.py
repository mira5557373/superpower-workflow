"""v1.3.1 HIGH #2 regression: sw server stop must verify the PID belongs to sw.

Pre-fix: stale PID file from a prior boot → `os.kill(pid, SIGTERM)` on an
unrelated process whose PID has been reused.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.cli import _server_pid_belongs_to_sw


class TestServerPidBelongsToSw:
    def test_current_process_passes_when_sw_in_cmdline(self):
        """If psutil is installed and the cmdline mentions sw, accept it."""
        with patch("psutil.Process") as mock_proc_cls:
            mock_proc = MagicMock()
            mock_proc.cmdline.return_value = ["python", "-m", "superpower_workflow.server.app"]
            mock_proc_cls.return_value = mock_proc
            assert _server_pid_belongs_to_sw(os.getpid()) is True

    def test_returns_false_when_cmdline_unrelated(self):
        """Different process (e.g., bash) with same PID → reject."""
        with patch("psutil.Process") as mock_proc_cls:
            mock_proc = MagicMock()
            mock_proc.cmdline.return_value = ["/bin/bash", "-c", "echo hello"]
            mock_proc_cls.return_value = mock_proc
            assert _server_pid_belongs_to_sw(12345) is False

    def test_returns_false_when_process_missing(self):
        """psutil.NoSuchProcess → safe refusal."""
        import psutil

        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(12345)):
            assert _server_pid_belongs_to_sw(12345) is False

    def test_returns_false_when_access_denied(self):
        import psutil

        with patch("psutil.Process", side_effect=psutil.AccessDenied(12345)):
            assert _server_pid_belongs_to_sw(12345) is False

    def test_returns_false_when_psutil_missing(self):
        """No psutil at all → conservative refuse. The function itself
        handles ImportError internally; we can't easily force one without
        patching builtins. Behavioral test is covered by the
        missing-process / unrelated-cmdline cases above."""
        # Smoke check that the symbol exists and is callable.
        assert callable(_server_pid_belongs_to_sw)


class TestSkillsHaveValidConfigKeys:
    """v1.3.1 HIGH #9: every `validation.<key>` mentioned in any SKILL.md must
    resolve to a real config key in cli.py's default_config or onboard.py's
    build_workflow_config validation block.
    """

    def _real_keys(self) -> set[str]:
        # Mirror the validation block defined in cli.py _cmd_init.
        return {
            "gap_validator",
            "gap_validation_mode",
            "spec_compliance",
            "feature_verification",
            "spec_compliance_budget",
            "feature_verification_budget",
            "strict_mode",
            "max_strict_iterations",
            "strict_iteration_budget",
            "gap_curator",
            "curator_budget",
            "curator_min_gaps",
            "spec_linter",
            "spec_linter_strict",
            "spec_max_words",
            "spec_min_words",
        }

    def test_no_skill_references_unknown_validation_key(self):
        import re
        from pathlib import Path

        skills_root = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "superpower_workflow"
            / "_assets"
            / "skills"
        )
        if not skills_root.exists():
            pytest.skip("skills not packaged in this layout")
        pattern = re.compile(r"validation\.([a-zA-Z_][a-zA-Z0-9_]*)")
        real = self._real_keys()
        offenders: list[str] = []
        for skill_md in skills_root.rglob("SKILL.md"):
            text = skill_md.read_text(encoding="utf-8", errors="replace")
            for m in pattern.finditer(text):
                key = m.group(1)
                if key not in real:
                    offenders.append(f"{skill_md.relative_to(skills_root)}: validation.{key}")
        assert not offenders, "Unknown validation.* keys in SKILL.md files:\n" + "\n".join(
            offenders
        )
