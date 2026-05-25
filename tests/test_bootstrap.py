from __future__ import annotations

from pathlib import Path

from superpower_workflow.bootstrap import (
    bootstrap,
    detect_project_type,
    render_template,
)


class TestDetectProjectType:
    def test_detects_python(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        assert detect_project_type(tmp_path) == "python"

    def test_detects_typescript(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "app"}')
        assert detect_project_type(tmp_path) == "typescript"

    def test_detects_python_requirements(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        assert detect_project_type(tmp_path) == "python"

    def test_unknown_when_no_markers(self, tmp_path: Path):
        assert detect_project_type(tmp_path) == "unknown"


class TestRenderTemplate:
    def test_substitutes_variables(self):
        tmpl = "Hello $project_name, version $version"
        result = render_template(tmpl, project_name="myapp", version="1.0")
        assert result == "Hello myapp, version 1.0"

    def test_missing_variable_left_as_is(self):
        tmpl = "Name: $project_name, Missing: $unknown"
        result = render_template(tmpl, project_name="app")
        assert "app" in result


class TestBootstrap:
    def test_creates_devcontainer(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        created = bootstrap(tmp_path, project_type="python")
        devcontainer = tmp_path / ".devcontainer" / "devcontainer.json"
        assert devcontainer.exists()
        assert ".devcontainer/devcontainer.json" in created

    def test_creates_ci_workflow(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        bootstrap(tmp_path, project_type="python")
        ci = tmp_path / ".github" / "workflows" / "ci.yml"
        assert ci.exists()

    def test_creates_claude_md(self, tmp_path: Path):
        bootstrap(tmp_path, project_type="python")
        assert (tmp_path / "CLAUDE.md").exists()

    def test_creates_docs_scaffold(self, tmp_path: Path):
        bootstrap(tmp_path, project_type="python")
        assert (tmp_path / "docs" / "index.md").exists()
        assert (tmp_path / "docs" / "architecture.mmd").exists()

    def test_creates_workflow_json(self, tmp_path: Path):
        bootstrap(tmp_path, project_type="python")
        assert (tmp_path / ".claude" / "workflow.json").exists()

    def test_skips_existing_files(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("Existing content")
        created = bootstrap(tmp_path, project_type="python")
        assert "CLAUDE.md" not in created
        assert (tmp_path / "CLAUDE.md").read_text() == "Existing content"

    def test_returns_list_of_created_files(self, tmp_path: Path):
        created = bootstrap(tmp_path, project_type="python")
        assert isinstance(created, list)
        assert len(created) > 0
        assert all(isinstance(f, str) for f in created)

    def test_typescript_templates(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "app"}')
        bootstrap(tmp_path, project_type="typescript")
        ci = tmp_path / ".github" / "workflows" / "ci.yml"
        assert ci.exists()
        ci_content = ci.read_text()
        assert "npm" in ci_content or "node" in ci_content

    def test_auto_detect_type(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        bootstrap(tmp_path)
        assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()
