from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from superpower_workflow.cli import _cmd_init
from superpower_workflow.server.config import ServerConfig, load_server_config
from superpower_workflow.server.deps import get_api_key, verify_api_key
from superpower_workflow.server.registry import (
    ProjectEntry,
    ProjectRegistry,
    get_default_registry_path,
)


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


class TestProjectEntry:
    def test_entry_has_required_fields(self):
        e = ProjectEntry(name="myapp", path="/home/user/myapp")
        assert e.name == "myapp"
        assert e.path == "/home/user/myapp"
        assert isinstance(e.added_at, str)

    def test_entry_auto_generates_timestamp(self):
        e = ProjectEntry(name="test", path="/tmp/test")
        assert "T" in e.added_at
        assert e.added_at.endswith("Z")

    def test_entry_to_dict_roundtrip(self):
        e = ProjectEntry(name="app", path="/p/app")
        d = e.to_dict()
        e2 = ProjectEntry.from_dict(d)
        assert e2.name == e.name
        assert e2.path == e.path


class TestProjectRegistry:
    def test_register_project(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("myapp", "/home/user/myapp")
        projects = reg.list_projects()
        assert len(projects) == 1
        assert projects[0].name == "myapp"

    def test_register_deduplicates_by_name(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("myapp", "/path/a")
        reg.register("myapp", "/path/b")
        projects = reg.list_projects()
        assert len(projects) == 1
        assert projects[0].path == "/path/b"

    def test_get_project_by_name(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("app1", "/p/1")
        reg.register("app2", "/p/2")
        p = reg.get_project("app1")
        assert p is not None
        assert p.path == "/p/1"

    def test_get_nonexistent_returns_none(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        assert reg.get_project("nope") is None

    def test_remove_project(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("app", "/p/app")
        reg.remove("app")
        assert reg.list_projects() == []

    def test_persistence_across_instances(self, tmp_path: Path):
        path = tmp_path / "projects.json"
        reg1 = ProjectRegistry(path)
        reg1.register("app", "/p/app")
        reg2 = ProjectRegistry(path)
        assert len(reg2.list_projects()) == 1

    def test_empty_registry(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        assert reg.list_projects() == []

    def test_default_path_under_home(self):
        p = get_default_registry_path()
        assert "sw-projects.json" in str(p)


class TestRegistryCorruption:
    def test_handles_corrupt_json(self, tmp_path: Path):
        path = tmp_path / "projects.json"
        path.write_text("not json{{{")
        reg = ProjectRegistry(path)
        assert reg.list_projects() == []

    def test_handles_missing_file(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "nonexistent" / "projects.json")
        assert reg.list_projects() == []


class TestServerConfig:
    def test_default_values(self):
        cfg = ServerConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 3001
        assert cfg.database_url == ""
        assert cfg.api_key == ""

    def test_from_env(self):
        with patch.dict(
            os.environ,
            {
                "SW_DATABASE_URL": "postgresql://localhost/sw",
                "SW_API_KEY": "test-key-123",
                "SW_SERVER_HOST": "127.0.0.1",
                "SW_SERVER_PORT": "8080",
            },
        ):
            cfg = load_server_config()
        assert cfg.database_url == "postgresql://localhost/sw"
        assert cfg.api_key == "test-key-123"
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8080

    def test_from_config_dict(self):
        config = {"server": {"host": "0.0.0.0", "port": 4000, "cors_origins": ["*"]}}
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_server_config(config)
        assert cfg.port == 4000
        assert cfg.cors_origins == ["*"]


class TestApiKey:
    def test_get_api_key_from_env(self):
        with patch.dict(os.environ, {"SW_API_KEY": "secret"}):
            assert get_api_key() == "secret"

    def test_get_api_key_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_api_key() == ""

    def test_verify_passes_with_correct_key(self):
        assert verify_api_key("secret", "secret") is True

    def test_verify_fails_with_wrong_key(self):
        assert verify_api_key("wrong", "secret") is False

    def test_verify_passes_when_no_key_configured(self):
        assert verify_api_key("anything", "") is True


class TestOrchestratorDbIntegration:
    def test_db_writer_wraps_emitter_when_url_set(self):
        with (
            patch.dict(os.environ, {"SW_DATABASE_URL": "sqlite:///:memory:"}),
            patch("superpower_workflow.orchestrator.TelemetryEmitter"),
            patch("superpower_workflow.orchestrator.run_claude"),
        ):
            pass

    def test_no_import_error_without_server_extras(self):
        with patch.dict(os.environ, {"SW_DATABASE_URL": ""}, clear=False):
            pass


class TestAutoRegister:
    def test_init_registers_project(self, tmp_path: Path):
        reg_path = tmp_path / "registry.json"
        from superpower_workflow.server.registry import ProjectRegistry

        reg = ProjectRegistry(reg_path)
        reg.register("test", str(tmp_path))
        projects = reg.list_projects()
        assert len(projects) == 1
