from __future__ import annotations

from superpower_workflow.telemetry import (
    BootstrapCompleted,
    DocsGenerated,
    PluginLoaded,
    PluginVetoed,
    UpgradeChecked,
)


class TestDocsGenerated:
    def test_fields(self):
        e = DocsGenerated(doc_type="changelog", output_path="CHANGELOG.md")
        assert e.EVENT_TYPE == "docs_generated"
        assert e.doc_type == "changelog"
        assert e.output_path == "CHANGELOG.md"

    def test_extends_telemetry_event(self):
        from superpower_workflow.telemetry import TelemetryEvent

        e = DocsGenerated(doc_type="readme", output_path="README.md")
        assert isinstance(e, TelemetryEvent)
        d = e.to_dict()
        assert d["type"] == "docs_generated"
        assert d["doc_type"] == "readme"
        assert "timestamp" in d

    def test_readme_type(self):
        e = DocsGenerated(doc_type="readme", output_path="README.md")
        assert e.doc_type == "readme"


class TestBootstrapCompleted:
    def test_fields(self):
        e = BootstrapCompleted(project_type="python", files_created=5)
        assert e.EVENT_TYPE == "bootstrap_completed"
        assert e.project_type == "python"
        assert e.files_created == 5

    def test_serializable(self):
        e = BootstrapCompleted(project_type="python", files_created=3)
        d = e.to_dict()
        assert d["type"] == "bootstrap_completed"
        assert d["project_type"] == "python"


class TestPluginLoaded:
    def test_fields(self):
        e = PluginLoaded(plugin_name="my-plugin", plugin_version="1.0.0")
        assert e.EVENT_TYPE == "plugin_loaded"
        assert e.plugin_name == "my-plugin"
        assert e.plugin_version == "1.0.0"

    def test_serializable(self):
        e = PluginLoaded(plugin_name="x", plugin_version="1.0")
        line = e.to_json_line()
        assert '"plugin_loaded"' in line


class TestPluginVetoed:
    def test_fields(self):
        e = PluginVetoed(plugin_name="veto", phase="plan", reason="blocked")
        assert e.EVENT_TYPE == "plugin_vetoed"
        assert e.plugin_name == "veto"
        assert e.phase == "plan"
        assert e.reason == "blocked"


class TestUpgradeChecked:
    def test_fields(self):
        e = UpgradeChecked(outdated_count=5, breaking_count=1)
        assert e.EVENT_TYPE == "upgrade_checked"
        assert e.outdated_count == 5
        assert e.breaking_count == 1

    def test_serializable(self):
        e = UpgradeChecked(outdated_count=2, breaking_count=0)
        d = e.to_dict()
        assert d["type"] == "upgrade_checked"
        assert d["outdated_count"] == 2
