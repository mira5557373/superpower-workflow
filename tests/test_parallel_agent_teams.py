from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.runner import _build_command, run_claude


class TestAgentTeamsFlag:
    def test_build_command_without_num_agents(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0)
        assert "--num-agents" not in cmd

    def test_build_command_with_num_agents(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0, num_agents=3)
        assert "--num-agents" in cmd
        idx = cmd.index("--num-agents")
        assert cmd[idx + 1] == "3"

    def test_build_command_num_agents_zero_omitted(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0, num_agents=0)
        assert "--num-agents" not in cmd

    def test_build_command_num_agents_none_omitted(self):
        cmd = _build_command("do stuff", "opus", "high", 50.0, num_agents=None)
        assert "--num-agents" not in cmd

    def test_run_claude_passes_num_agents(self):
        with patch("superpower_workflow.runner.subprocess.run") as mock:
            mock.return_value = CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"result":"ok","total_cost_usd":5.0,"session_id":"s1","duration_ms":100}',
                stderr="",
            )
            run_claude("prompt", "opus", "high", 50.0, cwd="/tmp", num_agents=4)
        cmd = mock.call_args[0][0]
        assert "--num-agents" in cmd
        idx = cmd.index("--num-agents")
        assert cmd[idx + 1] == "4"
