from __future__ import annotations


class TestDocsExports:
    def test_docs_package_has_all(self):
        import superpower_workflow.docs as docs

        assert hasattr(docs, "__all__")
        expected = [
            "generate_changelog",
            "generate_mermaid",
            "build_api_docs",
            "generate_readme",
        ]
        for name in expected:
            assert name in docs.__all__, f"{name} missing from docs.__all__"

    def test_docs_exports_importable(self):
        from superpower_workflow.docs import (
            build_api_docs,
            generate_changelog,
            generate_mermaid,
            generate_readme,
        )

        assert callable(generate_changelog)
        assert callable(generate_mermaid)
        assert callable(build_api_docs)
        assert callable(generate_readme)


class TestPluginsExports:
    def test_plugins_package_has_all(self):
        import superpower_workflow.plugins as plugins

        assert hasattr(plugins, "__all__")
        expected = [
            "Plugin",
            "PluginVetoError",
            "load_plugins",
            "ENTRY_POINT_GROUP",
        ]
        for name in expected:
            assert name in plugins.__all__, f"{name} missing from plugins.__all__"

    def test_plugins_exports_importable(self):
        from superpower_workflow.plugins import (
            ENTRY_POINT_GROUP,
            Plugin,
            PluginVetoError,
            load_plugins,
        )

        assert callable(load_plugins)
        assert issubclass(Plugin, object)
        assert issubclass(PluginVetoError, Exception)
        assert isinstance(ENTRY_POINT_GROUP, str)


class TestTelemetryExports:
    def test_sp7_events_importable(self):
        from superpower_workflow.telemetry import (  # noqa: F401
            BootstrapCompleted,
            DocsGenerated,
            PluginLoaded,
            PluginVetoed,
            UpgradeChecked,
        )
