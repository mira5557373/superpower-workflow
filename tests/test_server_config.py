from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init


class TestDatabaseConfig:
    def test_init_includes_database_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "database" in config
        db = config["database"]
        assert db["url_env"] == "SW_DATABASE_URL"
        assert db["retention_days"] == 90
        assert db["auto_sync"] is True

    def test_init_includes_server_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "server" in config
        srv = config["server"]
        assert srv["host"] == "0.0.0.0"
        assert srv["port"] == 3001
        assert isinstance(srv["cors_origins"], list)

    def test_server_cors_defaults_to_localhost(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        origins = config["server"]["cors_origins"]
        assert "http://localhost:3001" in origins

    def test_database_section_does_not_contain_url(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        db = config["database"]
        assert "url" not in db
        assert "password" not in db
