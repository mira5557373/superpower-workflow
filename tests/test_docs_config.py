from __future__ import annotations

import json
import re
from pathlib import Path

from superpower_workflow.cli import _cmd_init


def _load_json5(path: Path) -> dict:
    text = path.read_text()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return json.loads(text)


class TestDocsConfig:
    def test_init_includes_docs_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "docs" in config
        docs = config["docs"]
        assert "readme" in docs
        assert "changelog" in docs
        assert "api" in docs
        assert "diagrams" in docs

    def test_docs_readme_defaults(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        readme = config["docs"]["readme"]
        assert readme["enabled"] is False
        assert readme["template"] is None
        assert isinstance(readme["sections"], list)
        assert "overview" in readme["sections"]

    def test_docs_changelog_enabled_by_default(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert config["docs"]["changelog"]["enabled"] is True

    def test_docs_api_tool_default(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        api = config["docs"]["api"]
        assert api["tool"] == "sphinx"
        assert api["output_dir"] == "docs/api"

    def test_docs_diagrams_default(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        diag = config["docs"]["diagrams"]
        assert diag["enabled"] is True
        assert diag["output"] == "docs/architecture.mmd"

    def test_init_includes_plugins_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "plugins" in config
        plugins = config["plugins"]
        assert plugins["enabled"] is True
        assert isinstance(plugins["blocked"], list)
        assert plugins["blocked"] == []


class TestTemplateWorkflowJson:
    def test_template_has_docs_section(self):
        template_path = Path(__file__).resolve().parent.parent / "templates" / "workflow.json"
        config = _load_json5(template_path)
        assert "docs" in config

    def test_template_has_plugins_section(self):
        template_path = Path(__file__).resolve().parent.parent / "templates" / "workflow.json"
        config = _load_json5(template_path)
        assert "plugins" in config
