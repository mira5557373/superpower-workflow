"""Tests for statusline (v1.3.0 skeleton, T3.0.4)."""

from __future__ import annotations

import json

from superpower_workflow.statusline import (
    IDLE,
    render_statusline,
    write_statusline_file,
)


def _setup(claude_dir, state=None, config=None):
    claude_dir.mkdir(parents=True, exist_ok=True)
    if state is not None:
        (claude_dir / "workflow-state.json").write_text(json.dumps(state))
    if config is not None:
        (claude_dir / "workflow.json").write_text(json.dumps(config))


class TestRenderStatusline:
    def test_idle_when_no_state_file(self, tmp_path):
        assert render_statusline(tmp_path) == IDLE

    def test_idle_when_no_run_id(self, tmp_path):
        cd = tmp_path / ".claude"
        _setup(cd, state={"run_id": "", "completed": []}, config={})
        assert render_statusline(cd) == IDLE

    def test_idle_when_corrupt_state(self, tmp_path):
        cd = tmp_path / ".claude"
        cd.mkdir()
        (cd / "workflow-state.json").write_text("not json")
        (cd / "workflow.json").write_text("{}")
        assert render_statusline(cd) == IDLE

    def test_active_run_includes_milestone_and_cost(self, tmp_path):
        cd = tmp_path / ".claude"
        _setup(
            cd,
            state={
                "run_id": "r1",
                "completed": ["M1"],
                "current_milestone_index": 1,
                "current_step": "implement",
                "total_cost_usd": 5.67,
            },
            config={
                "milestones": [{"name": "M1"}, {"name": "M2"}, {"name": "M3"}],
                "max_total_budget_usd": 50,
            },
        )
        line = render_statusline(cd)
        assert "[sw]" in line
        assert "M2/3" in line
        assert "$5.67" in line
        assert "/$50" in line
        assert "implement" in line
        assert "1 done" in line


class TestWriteStatuslineFile:
    def test_writes_idle_when_no_state(self, tmp_path):
        cd = tmp_path / ".claude"
        cd.mkdir()
        path = write_statusline_file(cd)
        assert path.exists()
        assert "idle" in path.read_text()

    def test_writes_active_status(self, tmp_path):
        cd = tmp_path / ".claude"
        _setup(
            cd,
            state={
                "run_id": "r1",
                "completed": [],
                "current_milestone_index": 0,
                "current_step": "plan",
                "total_cost_usd": 1.23,
            },
            config={"milestones": [{"name": "M1"}], "max_total_budget_usd": 25},
        )
        path = write_statusline_file(cd)
        content = path.read_text()
        assert "M1/1" in content
        assert "$1.23" in content
