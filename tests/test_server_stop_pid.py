"""v1.3.1 HIGH #2 regression: sw server stop must verify the PID belongs to sw.

Pre-fix: stale PID file from a prior boot → `os.kill(pid, SIGTERM)` on an
unrelated process whose PID has been reused.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.cli import _server_pid_belongs_to_sw


def _mock_proc(cmdline):
    p = MagicMock()
    p.cmdline.return_value = cmdline
    return p


class TestServerPidBelongsToSw:
    """v1.3.2 #1: predicate must accept genuine sw-server launches and reject
    every false positive the original v1.3.1 predicate let through."""

    # --- POSITIVES: real server launches ---

    def test_accepts_python_dash_m_server_app(self):
        with patch(
            "psutil.Process",
            return_value=_mock_proc(["python", "-m", "superpower_workflow.server.app"]),
        ):
            assert _server_pid_belongs_to_sw(os.getpid()) is True

    def test_accepts_python_path_server_app(self):
        with patch(
            "psutil.Process",
            return_value=_mock_proc(
                ["/usr/bin/python3.12", "/x/superpower_workflow/server/app.py"]
            ),
        ):
            assert _server_pid_belongs_to_sw(99) is True

    def test_accepts_sw_entry_with_server_subcommand(self):
        with patch(
            "psutil.Process",
            return_value=_mock_proc(["/usr/local/bin/sw", "server", "run", "--port", "8080"]),
        ):
            assert _server_pid_belongs_to_sw(99) is True

    def test_accepts_sw_exe_with_server_subcommand_windows(self):
        with patch(
            "psutil.Process",
            return_value=_mock_proc(["C:\\Python\\Scripts\\sw.exe", "server", "run"]),
        ):
            assert _server_pid_belongs_to_sw(99) is True

    # --- NEGATIVES: v1.3.1's false positives must now be rejected ---

    def test_rejects_unrelated_bash(self):
        with patch("psutil.Process", return_value=_mock_proc(["/bin/bash", "-c", "echo hello"])):
            assert _server_pid_belongs_to_sw(99) is False

    def test_rejects_editor_viewing_sw_source(self):
        """v1.3.2 #1: vim opened on a sw file used to be accepted via the
        loose substring match. Must now be rejected (head argv is `vim`)."""
        with patch(
            "psutil.Process",
            return_value=_mock_proc(["vim", "/projects/superpower_workflow/src/cli.py"]),
        ):
            assert _server_pid_belongs_to_sw(99) is False

    def test_rejects_bash_dash_c_sw(self):
        """v1.3.2 #1: bare token `sw` no longer flips the predicate true."""
        with patch("psutil.Process", return_value=_mock_proc(["/bin/bash", "-c", "sw"])):
            assert _server_pid_belongs_to_sw(99) is False

    def test_rejects_other_sw_subcommand(self):
        """v1.3.2 #1: `sw run` or `sw watch` running in another terminal must
        NOT be SIGTERM'd by `sw server stop` after PID reuse."""
        with patch(
            "psutil.Process",
            return_value=_mock_proc(["/usr/local/bin/sw", "run", "--milestone", "M1"]),
        ):
            assert _server_pid_belongs_to_sw(99) is False

    def test_rejects_other_sw_module_invocation(self):
        """python -m superpower_workflow.cli (not the server) must be rejected."""
        with patch(
            "psutil.Process",
            return_value=_mock_proc(["python", "-m", "superpower_workflow.cli", "run"]),
        ):
            assert _server_pid_belongs_to_sw(99) is False

    def test_rejects_python_app_sw_arg(self):
        with patch("psutil.Process", return_value=_mock_proc(["python", "app.py", "sw"])):
            assert _server_pid_belongs_to_sw(99) is False

    def test_rejects_non_python_non_sw_head(self):
        """Even with `superpower_workflow.server` in argv, if head argv is
        not python/sw we should refuse (e.g., a malicious wrapper that
        spoofs the marker)."""
        with patch(
            "psutil.Process",
            return_value=_mock_proc(
                ["/usr/bin/curl", "-O", "http://x/superpower_workflow.server.txt"]
            ),
        ):
            assert _server_pid_belongs_to_sw(99) is False

    # --- ERROR PATHS: fail closed ---

    def test_returns_false_when_process_missing(self):
        import psutil

        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(12345)):
            assert _server_pid_belongs_to_sw(12345) is False

    def test_returns_false_when_access_denied(self):
        import psutil

        with patch("psutil.Process", side_effect=psutil.AccessDenied(12345)):
            assert _server_pid_belongs_to_sw(12345) is False

    def test_returns_false_when_zombie(self):
        import psutil

        with patch("psutil.Process", side_effect=psutil.ZombieProcess(12345)):
            assert _server_pid_belongs_to_sw(12345) is False

    def test_returns_false_on_empty_cmdline(self):
        """Some kernel-thread / exited processes return empty argv."""
        with patch("psutil.Process", return_value=_mock_proc([])):
            assert _server_pid_belongs_to_sw(99) is False


class TestCmdServerStopWiring:
    """v1.3.2 #1: ensure `_cmd_server_stop` actually consults
    `_server_pid_belongs_to_sw` and refuses to SIGTERM when False.
    """

    def test_stop_does_not_kill_when_predicate_false(self, tmp_path, monkeypatch):
        from pathlib import Path

        from superpower_workflow import cli as cli_mod

        pid_file = tmp_path / "sw-server.pid"
        pid_file.write_text("99999")
        monkeypatch.setattr(Path, "home", lambda: tmp_path.parent)
        # Re-point Path.home() / ".claude" / "sw-server.pid" to our file:
        claude_dir = tmp_path.parent / ".claude"
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / "sw-server.pid").write_text("99999")

        kills = []
        monkeypatch.setattr("os.kill", lambda pid, sig: kills.append((pid, sig)))
        monkeypatch.setattr(cli_mod, "_server_pid_belongs_to_sw", lambda pid: False)

        cli_mod._cmd_server_stop()
        assert kills == [], "os.kill must NOT be called when predicate is False"

    def test_stop_kills_when_predicate_true(self, tmp_path, monkeypatch):
        from pathlib import Path

        from superpower_workflow import cli as cli_mod

        monkeypatch.setattr(Path, "home", lambda: tmp_path.parent)
        claude_dir = tmp_path.parent / ".claude"
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / "sw-server.pid").write_text("42")

        kills = []
        monkeypatch.setattr("os.kill", lambda pid, sig: kills.append((pid, sig)))
        monkeypatch.setattr(cli_mod, "_server_pid_belongs_to_sw", lambda pid: True)

        cli_mod._cmd_server_stop()
        assert kills and kills[0][0] == 42


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
