from __future__ import annotations

from superpower_workflow.cli import build_parser


class TestServerSubcommands:
    def test_server_start_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "start"])
        assert args.command == "server"
        assert args.server_command == "start"

    def test_server_stop_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "stop"])
        assert args.command == "server"
        assert args.server_command == "stop"

    def test_server_init_db_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "init-db"])
        assert args.command == "server"
        assert args.server_command == "init-db"

    def test_server_sync_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "sync"])
        assert args.command == "server"
        assert args.server_command == "sync"

    def test_server_start_host_port(self):
        parser = build_parser()
        args = parser.parse_args(["server", "start", "--host", "127.0.0.1", "--port", "8080"])
        assert args.host == "127.0.0.1"
        assert args.port == 8080

    def test_server_sync_all_flag(self):
        parser = build_parser()
        args = parser.parse_args(["server", "sync", "--all"])
        assert args.sync_all is True

    def test_server_sync_project_flag(self):
        parser = build_parser()
        args = parser.parse_args(["server", "sync", "--project", "/p/app"])
        assert args.project == "/p/app"

    def test_server_start_database_url(self):
        parser = build_parser()
        args = parser.parse_args(["server", "start", "--database-url", "postgresql://localhost/sw"])
        assert args.database_url == "postgresql://localhost/sw"
