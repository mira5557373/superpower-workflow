from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init


class TestParallelConfig:
    def test_init_includes_model_routing(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "model_routing" in config
        routing = config["model_routing"]
        assert "enabled" in routing
        assert routing["enabled"] is False
        assert "rules" in routing
        assert isinstance(routing["rules"], list)

    def test_init_includes_parallel_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "parallel" in config
        par = config["parallel"]
        assert par["enabled"] is False
        assert par["max_workers"] == 4
        assert par["best_of_n"] == 1
        assert par["agent_teams_count"] == 0
        assert par["remote"] is None

    def test_init_includes_default_routing_rules(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        rules = config["model_routing"]["rules"]
        assert len(rules) == 3
        assert rules[0]["model"] == "opus"
        assert rules[1]["model"] == "sonnet"
        assert rules[2]["model"] == "haiku"

    def test_model_routing_default_model_key(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert config["model_routing"]["default_model"] == "opus"

    def test_parallel_worktree_dir_configurable(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert config["parallel"]["worktree_dir"] == ".worktrees"
