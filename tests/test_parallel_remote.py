from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from superpower_workflow.parallel.remote import RemoteConfig, RemoteRunner


class TestRemoteConfig:
    def test_parse_simple_url(self):
        cfg = RemoteConfig.from_url("ssh://host.example.com")
        assert cfg.host == "host.example.com"
        assert cfg.user is None
        assert cfg.port == 22
        assert cfg.path is None

    def test_parse_full_url(self):
        cfg = RemoteConfig.from_url("ssh://user@host.example.com:2222/home/user/project")
        assert cfg.host == "host.example.com"
        assert cfg.user == "user"
        assert cfg.port == 2222
        assert cfg.path == "/home/user/project"

    def test_parse_url_with_user_no_port(self):
        cfg = RemoteConfig.from_url("ssh://deploy@10.0.0.5")
        assert cfg.host == "10.0.0.5"
        assert cfg.user == "deploy"
        assert cfg.port == 22

    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="ssh://"):
            RemoteConfig.from_url("http://example.com")

    def test_ssh_target(self):
        cfg = RemoteConfig(host="example.com", user="deploy", port=2222)
        assert cfg.ssh_target == "deploy@example.com"

    def test_ssh_target_no_user(self):
        cfg = RemoteConfig(host="example.com")
        assert cfg.ssh_target == "example.com"


class TestRemoteRunner:
    def test_sync_pushes_to_remote(self):
        cfg = RemoteConfig(host="example.com", user="deploy", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch(
            "superpower_workflow.parallel.remote.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ) as mock:
            runner.sync()
        cmd = mock.call_args[0][0]
        assert "git" in cmd
        assert "push" in cmd

    def test_run_milestone_via_ssh(self):
        cfg = RemoteConfig(host="example.com", user="deploy", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch(
            "superpower_workflow.parallel.remote.subprocess.run",
            return_value=CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"result":"ok","total_cost_usd":5.0}',
                stderr="",
            ),
        ) as mock:
            runner.run_milestone("m1")
        cmd = mock.call_args[0][0]
        assert "ssh" in cmd
        assert "example.com" in " ".join(cmd)

    def test_pull_results_fetches(self):
        cfg = RemoteConfig(host="example.com", user="deploy", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch(
            "superpower_workflow.parallel.remote.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ) as mock:
            runner.pull_results()
        cmd = mock.call_args[0][0]
        assert "git" in cmd
        assert "pull" in cmd or "fetch" in cmd

    def test_run_milestone_returns_cost(self):
        cfg = RemoteConfig(host="example.com", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch(
            "superpower_workflow.parallel.remote.subprocess.run",
            return_value=CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"cost_usd": 12.5, "success": true}',
                stderr="",
            ),
        ):
            result = runner.run_milestone("m1")
        assert result.cost_usd == 12.5
        assert result.success is True

    def test_ssh_command_includes_port(self):
        cfg = RemoteConfig(host="example.com", user="deploy", port=2222, path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch(
            "superpower_workflow.parallel.remote.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="{}", stderr=""),
        ) as mock:
            runner.run_milestone("m1")
        cmd = mock.call_args[0][0]
        assert "-p" in cmd or "2222" in " ".join(cmd)

    def test_run_milestone_failure(self):
        cfg = RemoteConfig(host="example.com", path="/app")
        runner = RemoteRunner(cfg, cwd="/local/repo")
        with patch(
            "superpower_workflow.parallel.remote.subprocess.run",
            return_value=CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="connection refused",
            ),
        ):
            result = runner.run_milestone("m1")
        assert result.success is False
