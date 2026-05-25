from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.cli import build_parser


class TestPluginCLI:
    def test_plugin_list_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["plugin", "list"])
        assert args.command == "plugin"
        assert args.plugin_command == "list"

    def test_plugin_add_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["plugin", "add", "my-plugin"])
        assert args.command == "plugin"
        assert args.plugin_command == "add"
        assert args.plugin_name == "my-plugin"

    def test_plugin_remove_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["plugin", "remove", "my-plugin"])
        assert args.command == "plugin"
        assert args.plugin_command == "remove"
        assert args.plugin_name == "my-plugin"


class TestPluginAddInstalls:
    def test_add_calls_pip_install(self):
        result = CompletedProcess(args=[], returncode=0, stdout="Installed", stderr="")
        with patch("superpower_workflow.cli.subprocess.run", return_value=result) as mock:
            from superpower_workflow.cli import _cmd_plugin_add

            _cmd_plugin_add("my-plugin")
        cmd = mock.call_args[0][0]
        assert "pip" in cmd
        assert "install" in cmd
        assert "sw-plugin-my-plugin" in cmd

    def test_add_failure_prints_error(self, capsys):
        result = CompletedProcess(args=[], returncode=1, stdout="", stderr="not found")
        with patch("superpower_workflow.cli.subprocess.run", return_value=result):
            from superpower_workflow.cli import _cmd_plugin_add

            _cmd_plugin_add("nonexistent")
        captured = capsys.readouterr()
        assert "Failed" in captured.out or "failed" in captured.out.lower()
