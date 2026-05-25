from __future__ import annotations


class TestDbExports:
    def test_db_package_has_all(self):
        import superpower_workflow.db

        assert hasattr(superpower_workflow.db, "__all__")

    def test_db_exports_engine(self):
        from superpower_workflow.db import create_engine_from_url, get_session_factory

        assert callable(create_engine_from_url)
        assert callable(get_session_factory)

    def test_db_exports_models(self):
        from superpower_workflow.db import (
            Base,
            SwCoverageResult,
            SwEvent,
            SwGapReport,
            SwMilestone,
            SwPhase,
            SwProject,
            SwQualityGate,
            SwRun,
        )

        assert Base is not None
        assert SwProject is not None
        assert SwRun is not None
        assert SwMilestone is not None
        assert SwPhase is not None
        assert SwEvent is not None
        assert SwQualityGate is not None
        assert SwCoverageResult is not None
        assert SwGapReport is not None

    def test_db_exports_writer(self):
        from superpower_workflow.db import TelemetryDbWriter

        assert TelemetryDbWriter is not None

    def test_db_exports_sync(self):
        from superpower_workflow.db import DbSyncAdapter

        assert DbSyncAdapter is not None


class TestServerExports:
    def test_server_package_has_all(self):
        import superpower_workflow.server

        assert hasattr(superpower_workflow.server, "__all__")

    def test_server_exports_app(self):
        from superpower_workflow.server import create_app

        assert callable(create_app)

    def test_server_exports_config(self):
        from superpower_workflow.server import ServerConfig, load_server_config

        assert ServerConfig is not None
        assert callable(load_server_config)

    def test_server_exports_registry(self):
        from superpower_workflow.server import ProjectEntry, ProjectRegistry

        assert ProjectRegistry is not None
        assert ProjectEntry is not None


class TestRouterExports:
    def test_routers_package_has_all(self):
        import superpower_workflow.server.routers

        assert hasattr(superpower_workflow.server.routers, "__all__")
