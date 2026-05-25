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
        assert e.type == "docs_generated"
        assert e.doc_type == "changelog"
        assert e.output_path == "CHANGELOG.md"

    def test_readme_type(self):
        e = DocsGenerated(doc_type="readme", output_path="README.md")
        assert e.doc_type == "readme"


class TestBootstrapCompleted:
    def test_fields(self):
        e = BootstrapCompleted(project_type="python", files_created=5)
        assert e.type == "bootstrap_completed"
        assert e.project_type == "python"
        assert e.files_created == 5


class TestPluginLoaded:
    def test_fields(self):
        e = PluginLoaded(plugin_name="my-plugin", plugin_version="1.0.0")
        assert e.type == "plugin_loaded"
        assert e.plugin_name == "my-plugin"


class TestPluginVetoed:
    def test_fields(self):
        e = PluginVetoed(plugin_name="veto", phase="plan", reason="blocked")
        assert e.type == "plugin_vetoed"
        assert e.plugin_name == "veto"
        assert e.phase == "plan"
        assert e.reason == "blocked"


class TestUpgradeChecked:
    def test_fields(self):
        e = UpgradeChecked(outdated_count=5, breaking_count=1)
        assert e.type == "upgrade_checked"
        assert e.outdated_count == 5
        assert e.breaking_count == 1
