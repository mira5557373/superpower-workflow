# SP7: Docs, DX & Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-generate project documentation (README, CHANGELOG, API docs, architecture diagrams), provide one-command project bootstrap via `sw bootstrap`, detect outdated dependencies via `sw upgrade`, and introduce a plugin system with entry-point-based discovery that lets the community extend every layer of superpower-workflow.

**Architecture:** Three new subpackages. `docs/` contains four generators: deterministic CHANGELOG (parses conventional commits), deterministic Mermaid diagram (parses Python imports), Sphinx/MkDocs API docs wrapper, and AI-assisted README generation via `run_claude`. `plugins/` contains the Plugin base class, PluginVetoError exception, and entry-point-based loader via `importlib.metadata`. Top-level `bootstrap.py` renders project scaffolding from string.Template templates, and `upgrade.py` detects outdated deps via pip/npm JSON output. The orchestrator gains two new hook sites: plugin lifecycle hooks (pre_phase/post_phase/pre_commit/post_milestone) and post-milestone docs generation. All docs and plugin config lives under new `docs` and `plugins` sections in workflow.json.

**Tech Stack:** Python 3.11+, `subprocess` (git, pip, npm, sphinx), `ast` (import parsing), `string.Template` (bootstrap templates), `importlib.metadata` (plugin discovery), `json`, `re`, `dataclasses`. Zero new dependencies -- all stdlib.

**Spec reference:** `docs/superpowers/specs/2026-05-24-sp7-docs-dx-plugins.md`

**Working directory:** `superpower-workflow/` (the repo root).

---

## Design Decisions

1. **README generation:** Opt-in (enabled: false by default). Conservative default; user enables when ready.
2. **Plugin sandboxing:** No sandboxing in v1. Plugins are trusted (installed via pip). Community can add sandboxing in a future SP.
3. **`sw upgrade` strategy:** One branch per major (breaking) dep bump; batch all minor/patch into a single branch. Keeps PRs focused for breaking changes.
4. **Architecture diagrams:** Only `src/` directory (spec: "Parse Python imports from all .py files in `src/`"). Test files excluded.
5. **Template engine:** `string.Template` (stdlib) instead of Jinja2 to maintain zero-dependency policy. Variable substitution is sufficient for current templates; Jinja2 can be added later if conditionals/loops are needed.
6. **Plugin naming convention:** Community plugins named `sw-plugin-{name}` on PyPI. The `add` command wraps `pip install`.
7. **Docs generation timing:** Post-milestone, after Phase D (or Phase E/F if enabled). Configured via `docs` section in workflow.json.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/docs/__init__.py` | New | Package exports with `__all__` |
| `src/superpower_workflow/docs/changelog.py` | New | Deterministic CHANGELOG from conventional commits |
| `src/superpower_workflow/docs/diagrams.py` | New | Mermaid dependency graph from Python imports |
| `src/superpower_workflow/docs/api_docs.py` | New | Sphinx/MkDocs build wrapper |
| `src/superpower_workflow/docs/readme_gen.py` | New | AI-assisted README generation via run_claude |
| `src/superpower_workflow/bootstrap.py` | New | Project scaffold generator (devcontainer, CI, hooks, CLAUDE.md) |
| `src/superpower_workflow/upgrade.py` | New | Outdated dep detection, breaking change classification |
| `src/superpower_workflow/plugins/__init__.py` | New | Package exports with `__all__` |
| `src/superpower_workflow/plugins/interface.py` | New | Plugin base class, PluginVetoError |
| `src/superpower_workflow/plugins/loader.py` | New | Entry-point discovery, load_plugins() |
| `src/superpower_workflow/cli.py` | Edit | Add bootstrap, upgrade, plugin subcommands |
| `src/superpower_workflow/orchestrator.py` | Edit | Plugin lifecycle hooks + post-milestone docs generation |
| `src/superpower_workflow/telemetry.py` | Edit | New event types: DocsGenerated, BootstrapCompleted, PluginLoaded, PluginVetoed, UpgradeChecked |
| `templates/workflow.json` | Edit | Add `docs` and `plugins` config sections |
| `tests/test_docs_config.py` | New | Config schema tests for docs + plugins sections |
| `tests/test_changelog.py` | New | CHANGELOG generation tests |
| `tests/test_diagrams.py` | New | Mermaid diagram generation tests |
| `tests/test_api_docs.py` | New | API docs wrapper tests |
| `tests/test_readme_gen.py` | New | README generation tests |
| `tests/test_bootstrap.py` | New | Bootstrap template rendering + CLI tests |
| `tests/test_upgrade.py` | New | Upgrade detection + CLI tests |
| `tests/test_plugin_interface.py` | New | Plugin base class + veto tests |
| `tests/test_plugin_loader.py` | New | Plugin loader tests |
| `tests/test_plugin_cli.py` | New | Plugin CLI subcommand tests |
| `tests/test_docs_orchestrator.py` | New | Orchestrator plugin + docs hook tests |
| `tests/test_docs_telemetry.py` | New | Telemetry event tests for SP7 |
| `tests/test_docs_exports.py` | New | Package export completeness tests |
| `tests/test_docs_plugins_integration.py` | New | End-to-end integration tests |

---

### Task 1: Config schema -- `docs` + `plugins` sections

**Files:**
- Edit: `templates/workflow.json`
- Edit: `src/superpower_workflow/cli.py` (default config in `_cmd_init`)
- New: `tests/test_docs_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_config.py
from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init


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
```

- [ ] **Step 2: Run tests -- expect FAIL** (docs/plugins keys don't exist)

- [ ] **Step 3: Add config sections**

In `cli.py` `_cmd_init`, add to `default_config` dict after the `parallel` block:

```python
"docs": {
    "readme": {
        "enabled": False,
        "template": None,
        "sections": ["overview", "quickstart", "architecture", "contributing"],
    },
    "changelog": {
        "enabled": True,
    },
    "api": {
        "tool": "sphinx",
        "output_dir": "docs/api",
    },
    "diagrams": {
        "enabled": True,
        "output": "docs/architecture.mmd",
    },
},
"plugins": {
    "enabled": True,
    "blocked": [],
},
```

Update `templates/workflow.json` to include the same sections.

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_docs_config.py --fix
ruff format src/superpower_workflow/cli.py tests/test_docs_config.py
git add src/superpower_workflow/cli.py templates/workflow.json tests/test_docs_config.py
git commit -m "feat: add docs and plugins config sections to workflow.json"
```

---

### Task 2: Docs package + CHANGELOG generation

**Files:**
- New: `src/superpower_workflow/docs/__init__.py`
- New: `src/superpower_workflow/docs/changelog.py`
- New: `tests/test_changelog.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_changelog.py
from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.docs.changelog import (
    generate_changelog,
    parse_commits,
    render_changelog,
)


def _git_log_output(lines: list[str]) -> CompletedProcess:
    stdout = "\n".join(lines)
    return CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class TestParseCommits:
    def test_groups_by_prefix(self):
        lines = [
            "abc1234 feat: add login page",
            "def5678 fix: correct validation",
            "ghi9012 test: add unit tests",
        ]
        groups = parse_commits(lines)
        assert len(groups["feat"]) == 1
        assert len(groups["fix"]) == 1
        assert len(groups["test"]) == 1

    def test_scoped_prefix(self):
        lines = ["abc1234 feat(auth): add oauth flow"]
        groups = parse_commits(lines)
        assert len(groups["feat"]) == 1
        assert "oauth" in groups["feat"][0]

    def test_unknown_prefix_goes_to_other(self):
        lines = ["abc1234 misc: cleanup old files"]
        groups = parse_commits(lines)
        assert len(groups["other"]) == 1

    def test_empty_input(self):
        groups = parse_commits([])
        assert all(len(v) == 0 for v in groups.values())

    def test_malformed_line_skipped(self):
        lines = ["not-a-valid-line", "abc1234 feat: valid entry"]
        groups = parse_commits(lines)
        assert len(groups["feat"]) == 1


class TestRenderChangelog:
    def test_renders_sections_with_entries(self):
        groups = {
            "feat": ["- add login page (abc1234)"],
            "fix": ["- correct validation (def5678)"],
            "refactor": [],
            "docs": [],
            "test": [],
            "chore": [],
            "style": [],
            "other": [],
        }
        output = render_changelog(groups)
        assert "### Features" in output
        assert "### Bug Fixes" in output
        assert "### Refactoring" not in output
        assert "abc1234" in output

    def test_empty_groups_produce_empty_output(self):
        groups = {k: [] for k in ("feat", "fix", "refactor", "docs", "test", "chore", "style", "other")}
        output = render_changelog(groups)
        assert output == ""


class TestGenerateChangelog:
    def test_generates_from_git_log(self):
        log_output = _git_log_output([
            "abc1234 feat: add login",
            "def5678 fix: patch XSS",
        ])
        with patch("superpower_workflow.docs.changelog.subprocess.run", return_value=log_output):
            result = generate_changelog()
        assert "### Features" in result
        assert "### Bug Fixes" in result
        assert "abc1234" in result

    def test_since_tag_passed_to_git(self):
        with patch("superpower_workflow.docs.changelog.subprocess.run", return_value=_git_log_output([])) as mock:
            generate_changelog(since_tag="v0.1.0")
        cmd = mock.call_args[0][0]
        assert "v0.1.0..HEAD" in cmd

    def test_git_failure_returns_empty(self):
        fail = CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")
        with patch("superpower_workflow.docs.changelog.subprocess.run", return_value=fail):
            result = generate_changelog()
        assert result == ""
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/docs/__init__.py
from __future__ import annotations

from superpower_workflow.docs.changelog import generate_changelog

__all__ = [
    "generate_changelog",
]
```

```python
# src/superpower_workflow/docs/changelog.py
from __future__ import annotations

import subprocess

SECTION_TITLES = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "test": "Tests",
    "chore": "Chores",
    "style": "Style",
    "other": "Other",
}

GROUP_KEYS = tuple(SECTION_TITLES.keys())


def generate_changelog(since_tag: str | None = None, cwd: str = ".") -> str:
    cmd = ["git", "log", "--format=%H %s"]
    if since_tag:
        cmd.append(f"{since_tag}..HEAD")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    if result.returncode != 0:
        return ""
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    groups = parse_commits(lines)
    return render_changelog(groups)


def parse_commits(lines: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {k: [] for k in GROUP_KEYS}
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, msg = parts
        prefix = msg.split(":")[0].split("(")[0].strip().lower()
        bucket = prefix if prefix in groups else "other"
        groups[bucket].append(f"- {msg} ({sha[:7]})")
    return groups


def render_changelog(groups: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for key, title in SECTION_TITLES.items():
        items = groups.get(key, [])
        if items:
            lines.append(f"### {title}\n")
            lines.extend(items)
            lines.append("")
    return "\n".join(lines).strip()
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/docs/ tests/test_changelog.py --fix
ruff format src/superpower_workflow/docs/ tests/test_changelog.py
git add src/superpower_workflow/docs/__init__.py src/superpower_workflow/docs/changelog.py tests/test_changelog.py
git commit -m "feat: add deterministic CHANGELOG generation from conventional commits"
```

---

### Task 3: Architecture diagrams -- Mermaid from Python imports

**Files:**
- New: `src/superpower_workflow/docs/diagrams.py`
- New: `tests/test_diagrams.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_diagrams.py
from __future__ import annotations

from pathlib import Path

from superpower_workflow.docs.diagrams import (
    generate_mermaid,
    parse_imports,
    path_to_module,
)


class TestPathToModule:
    def test_regular_file(self, tmp_path: Path):
        base = tmp_path / "src"
        base.mkdir()
        f = base / "mypackage" / "foo.py"
        f.parent.mkdir(parents=True)
        f.touch()
        assert path_to_module(f, base) == "mypackage.foo"

    def test_init_file(self, tmp_path: Path):
        base = tmp_path / "src"
        base.mkdir()
        f = base / "mypackage" / "__init__.py"
        f.parent.mkdir(parents=True)
        f.touch()
        assert path_to_module(f, base) == "mypackage"

    def test_nested_module(self, tmp_path: Path):
        base = tmp_path / "src"
        base.mkdir()
        f = base / "pkg" / "sub" / "deep.py"
        f.parent.mkdir(parents=True)
        f.touch()
        assert path_to_module(f, base) == "pkg.sub.deep"


class TestParseImports:
    def test_import_statement(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("import os\nimport json\n")
        imports = parse_imports(f)
        assert "os" in imports
        assert "json" in imports

    def test_from_import(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("from mypackage.utils import helper\n")
        imports = parse_imports(f)
        assert "mypackage.utils" in imports

    def test_syntax_error_returns_empty(self, tmp_path: Path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n")
        imports = parse_imports(f)
        assert imports == []

    def test_no_imports(self, tmp_path: Path):
        f = tmp_path / "empty.py"
        f.write_text("x = 1\n")
        imports = parse_imports(f)
        assert imports == []


class TestGenerateMermaid:
    def test_generates_graph_header(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("from mypkg import b\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert result.startswith("graph TD")

    def test_captures_internal_edges(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("from mypkg.b import helper\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert "mypkg.a" in result
        assert "mypkg.b" in result
        assert "-->" in result

    def test_excludes_external_imports(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("import os\nfrom mypkg import b\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert "os" not in result

    def test_empty_package(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        result = generate_mermaid(src, project_prefix="mypkg")
        assert result == "graph TD"

    def test_auto_detects_prefix(self, tmp_path: Path):
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "a.py").write_text("from mypkg.b import x\n")
        (src / "b.py").write_text("")
        result = generate_mermaid(src)
        assert "mypkg.a" in result
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/docs/diagrams.py
from __future__ import annotations

import ast
import re
from pathlib import Path


def generate_mermaid(src_dir: Path, project_prefix: str | None = None) -> str:
    if project_prefix is None:
        project_prefix = src_dir.name

    edges: set[tuple[str, str]] = set()
    for py_file in sorted(src_dir.rglob("*.py")):
        module = path_to_module(py_file, src_dir.parent)
        for imp in parse_imports(py_file):
            if imp.startswith(project_prefix):
                edges.add((module, imp))

    lines = ["graph TD"]
    for src, dst in sorted(edges):
        safe_src = _sanitize_id(src)
        safe_dst = _sanitize_id(dst)
        lines.append(f"    {safe_src}[\"{src}\"] --> {safe_dst}[\"{dst}\"]")
    return "\n".join(lines)


def path_to_module(py_file: Path, base: Path) -> str:
    rel = py_file.relative_to(base)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")
    return ".".join(parts)


def parse_imports(py_file: Path) -> list[str]:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _sanitize_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/docs/diagrams.py tests/test_diagrams.py --fix
ruff format src/superpower_workflow/docs/diagrams.py tests/test_diagrams.py
git add src/superpower_workflow/docs/diagrams.py tests/test_diagrams.py
git commit -m "feat: add Mermaid architecture diagram generation from Python imports"
```

---

### Task 4: API docs wrapper

**Files:**
- New: `src/superpower_workflow/docs/api_docs.py`
- New: `tests/test_api_docs.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api_docs.py
from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import call, patch

from superpower_workflow.docs.api_docs import build_api_docs


def _success() -> CompletedProcess:
    return CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _failure() -> CompletedProcess:
    return CompletedProcess(args=[], returncode=1, stdout="", stderr="error")


class TestBuildApiDocsSphinx:
    def test_sphinx_runs_apidoc_then_build(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run", return_value=_success()) as mock:
            result = build_api_docs(src, out, tool="sphinx")
        assert result is True
        cmds = [c[0][0] for c in mock.call_args_list]
        assert any("sphinx-apidoc" in cmd for cmd in cmds)
        assert any("sphinx-build" in cmd for cmd in cmds)

    def test_sphinx_apidoc_failure_returns_false(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run", return_value=_failure()):
            result = build_api_docs(src, out, tool="sphinx")
        assert result is False

    def test_sphinx_build_failure_returns_false(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run") as mock:
            mock.side_effect = [_success(), _failure()]
            result = build_api_docs(src, out, tool="sphinx")
        assert result is False

    def test_creates_output_dir(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run", return_value=_success()):
            build_api_docs(src, out, tool="sphinx")
        assert out.exists()


class TestBuildApiDocsMkdocs:
    def test_mkdocs_runs_build(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run", return_value=_success()) as mock:
            result = build_api_docs(src, out, tool="mkdocs")
        assert result is True
        cmd = mock.call_args[0][0]
        assert "mkdocs" in cmd
        assert "build" in cmd

    def test_unsupported_tool_raises(self, tmp_path: Path):
        import pytest

        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with pytest.raises(ValueError, match="Unsupported"):
            build_api_docs(src, out, tool="unknown")
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/docs/api_docs.py
from __future__ import annotations

import subprocess
from pathlib import Path


def build_api_docs(
    src_dir: Path,
    output_dir: Path,
    tool: str = "sphinx",
    cwd: str = ".",
) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)

    if tool == "sphinx":
        return _build_sphinx(src_dir, output_dir, cwd)
    elif tool == "mkdocs":
        return _build_mkdocs(cwd)
    else:
        raise ValueError(f"Unsupported docs tool: {tool}")


def _build_sphinx(src_dir: Path, output_dir: Path, cwd: str) -> bool:
    apidoc = subprocess.run(
        ["sphinx-apidoc", "-o", str(output_dir / "source"), str(src_dir)],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )
    if apidoc.returncode != 0:
        return False
    build = subprocess.run(
        ["sphinx-build", str(output_dir / "source"), str(output_dir / "build")],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )
    return build.returncode == 0


def _build_mkdocs(cwd: str) -> bool:
    result = subprocess.run(
        ["mkdocs", "build"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
    )
    return result.returncode == 0
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/docs/api_docs.py tests/test_api_docs.py --fix
ruff format src/superpower_workflow/docs/api_docs.py tests/test_api_docs.py
git add src/superpower_workflow/docs/api_docs.py tests/test_api_docs.py
git commit -m "feat: add Sphinx/MkDocs API documentation build wrapper"
```

---

### Task 5: README generation -- AI-assisted

**Files:**
- New: `src/superpower_workflow/docs/readme_gen.py`
- New: `tests/test_readme_gen.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_readme_gen.py
from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.docs.readme_gen import generate_readme, gather_context
from superpower_workflow.runner import ClaudeResult


class TestGatherContext:
    def test_reads_claude_md(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("# My Project\nSome context here.")
        context = gather_context(tmp_path, cwd=str(tmp_path))
        assert "My Project" in context

    def test_includes_git_log(self, tmp_path: Path):
        log = CompletedProcess(args=[], returncode=0, stdout="abc1234 feat: login\n", stderr="")
        with patch("superpower_workflow.docs.readme_gen.subprocess.run", return_value=log):
            context = gather_context(tmp_path, cwd=str(tmp_path))
        assert "abc1234" in context

    def test_handles_no_claude_md(self, tmp_path: Path):
        log = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("superpower_workflow.docs.readme_gen.subprocess.run", return_value=log):
            context = gather_context(tmp_path, cwd=str(tmp_path))
        assert isinstance(context, str)

    def test_git_failure_still_returns_context(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("# Proj")
        fail = CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")
        with patch("superpower_workflow.docs.readme_gen.subprocess.run", return_value=fail):
            context = gather_context(tmp_path, cwd=str(tmp_path))
        assert "Proj" in context


class TestGenerateReadme:
    def test_returns_claude_output(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("# Project")
        mock_result = ClaudeResult(text="# My README\nGenerated.", is_error=False, cost_usd=0.5)
        with (
            patch("superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result),
            patch("superpower_workflow.docs.readme_gen.subprocess.run",
                  return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
        ):
            result = generate_readme(tmp_path, cwd=str(tmp_path))
        assert "My README" in result

    def test_returns_empty_on_error(self, tmp_path: Path):
        mock_result = ClaudeResult(text="", is_error=True, cost_usd=0.0)
        with (
            patch("superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result),
            patch("superpower_workflow.docs.readme_gen.subprocess.run",
                  return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
        ):
            result = generate_readme(tmp_path, cwd=str(tmp_path))
        assert result == ""

    def test_passes_effort_and_budget_to_claude(self, tmp_path: Path):
        mock_result = ClaudeResult(text="content", is_error=False, cost_usd=0.1)
        with (
            patch("superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result) as mock_claude,
            patch("superpower_workflow.docs.readme_gen.subprocess.run",
                  return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
        ):
            generate_readme(tmp_path, effort="medium", budget=10, cwd=str(tmp_path))
        _, kwargs = mock_claude.call_args
        assert kwargs["effort"] == "medium"
        assert kwargs["budget"] == 10

    def test_passes_sections_to_prompt(self, tmp_path: Path):
        mock_result = ClaudeResult(text="content", is_error=False, cost_usd=0.1)
        with (
            patch("superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result) as mock_claude,
            patch("superpower_workflow.docs.readme_gen.subprocess.run",
                  return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
        ):
            generate_readme(tmp_path, sections=["overview", "api"], cwd=str(tmp_path))
        prompt = mock_claude.call_args[0][0]
        assert "overview" in prompt
        assert "api" in prompt

    def test_uses_template_when_provided(self, tmp_path: Path):
        (tmp_path / "tmpl.md").write_text("# Template\n$project_name")
        mock_result = ClaudeResult(text="content", is_error=False, cost_usd=0.1)
        with (
            patch("superpower_workflow.docs.readme_gen.run_claude", return_value=mock_result) as mock_claude,
            patch("superpower_workflow.docs.readme_gen.subprocess.run",
                  return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
        ):
            generate_readme(tmp_path, template="tmpl.md", cwd=str(tmp_path))
        prompt = mock_claude.call_args[0][0]
        assert "Template" in prompt
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/docs/readme_gen.py
from __future__ import annotations

import subprocess
from pathlib import Path

from superpower_workflow.runner import run_claude


def generate_readme(
    project_root: Path,
    model: str = "opus",
    effort: str = "high",
    budget: float = 25,
    template: str | None = None,
    sections: list[str] | None = None,
    cwd: str = ".",
) -> str:
    context = gather_context(project_root, cwd)

    section_hint = ""
    if sections:
        section_hint = f"Include these sections: {', '.join(sections)}. "

    template_hint = ""
    if template:
        template_path = project_root / template
        if template_path.exists():
            content = template_path.read_text(encoding="utf-8")[:2000]
            template_hint = f"\nUse this template as base structure:\n{content}"

    prompt = (
        f"Update README.md based on this context. Keep existing sections, update stats. "
        f"{section_hint}{template_hint}\n\n"
        f"Context:\n{context}\n\n"
        f"Output only the README.md content, nothing else."
    )

    result = run_claude(prompt, model=model, effort=effort, budget=budget, cwd=cwd)
    if result.is_error:
        return ""
    return result.text.strip()


def gather_context(project_root: Path, cwd: str) -> str:
    parts: list[str] = []

    claude_md = project_root / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")[:3000]
        parts.append(f"## CLAUDE.md\n{content}")

    git_log = subprocess.run(
        ["git", "log", "--oneline", "-5"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )
    if git_log.returncode == 0 and git_log.stdout.strip():
        parts.append(f"## Recent commits\n{git_log.stdout.strip()}")

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/docs/readme_gen.py tests/test_readme_gen.py --fix
ruff format src/superpower_workflow/docs/readme_gen.py tests/test_readme_gen.py
git add src/superpower_workflow/docs/readme_gen.py tests/test_readme_gen.py
git commit -m "feat: add AI-assisted README generation via run_claude"
```

---

### Task 6: Bootstrap templates + renderer

**Files:**
- New: `src/superpower_workflow/bootstrap.py`
- New: `tests/test_bootstrap.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_bootstrap.py
from __future__ import annotations

from pathlib import Path

from superpower_workflow.bootstrap import (
    TEMPLATES,
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
        created = bootstrap(tmp_path, project_type="python")
        ci = tmp_path / ".github" / "workflows" / "ci.yml"
        assert ci.exists()

    def test_creates_claude_md(self, tmp_path: Path):
        created = bootstrap(tmp_path, project_type="python")
        assert (tmp_path / "CLAUDE.md").exists()

    def test_creates_docs_scaffold(self, tmp_path: Path):
        created = bootstrap(tmp_path, project_type="python")
        assert (tmp_path / "docs" / "index.md").exists()
        assert (tmp_path / "docs" / "architecture.mmd").exists()

    def test_creates_workflow_json(self, tmp_path: Path):
        created = bootstrap(tmp_path, project_type="python")
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
        created = bootstrap(tmp_path, project_type="typescript")
        ci = tmp_path / ".github" / "workflows" / "ci.yml"
        assert ci.exists()
        ci_content = ci.read_text()
        assert "npm" in ci_content or "node" in ci_content

    def test_auto_detect_type(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        created = bootstrap(tmp_path)
        assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/bootstrap.py
from __future__ import annotations

import json
from pathlib import Path
from string import Template


def detect_project_type(project_root: Path) -> str:
    if (project_root / "pyproject.toml").exists():
        return "python"
    if (project_root / "requirements.txt").exists():
        return "python"
    if (project_root / "package.json").exists():
        return "typescript"
    if (project_root / "Cargo.toml").exists():
        return "rust"
    return "unknown"


def render_template(template_str: str, **kwargs: str) -> str:
    return Template(template_str).safe_substitute(**kwargs)


TEMPLATES: dict[str, dict[str, str]] = {
    "python": {
        ".devcontainer/devcontainer.json": json.dumps(
            {
                "name": "Python Dev",
                "image": "mcr.microsoft.com/devcontainers/python:3.11",
                "features": {},
                "postCreateCommand": "pip install -e '.[dev]'",
            },
            indent=2,
        ),
        ".github/workflows/ci.yml": (
            "name: CI\n"
            "on: [push, pull_request]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-python@v5\n"
            "        with:\n"
            "          python-version: '3.11'\n"
            "      - run: pip install -e '.[dev]'\n"
            "      - run: python -m pytest -q\n"
            "      - run: python -m ruff check src/\n"
        ),
        ".pre-commit-config.yaml": (
            "repos:\n"
            "  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
            "    rev: v0.4.0\n"
            "    hooks:\n"
            "      - id: ruff\n"
            "      - id: ruff-format\n"
        ),
        "CLAUDE.md": (
            "# $project_name -- Project Instructions\n\n"
            "## What this project is\n\n"
            "(Describe your project here.)\n\n"
            "## Conventions\n\n"
            "- Python 3.11+\n"
            "- pytest for tests, conventional commits\n"
            "- ruff for lint + format\n"
        ),
        "docs/index.md": "# $project_name\n\nProject documentation.\n",
        "docs/architecture.mmd": "graph TD\n    A[Module A] --> B[Module B]\n",
        ".claude/workflow.json": "",
    },
    "typescript": {
        ".devcontainer/devcontainer.json": json.dumps(
            {
                "name": "Node Dev",
                "image": "mcr.microsoft.com/devcontainers/javascript-node:20",
                "features": {},
                "postCreateCommand": "npm install",
            },
            indent=2,
        ),
        ".github/workflows/ci.yml": (
            "name: CI\n"
            "on: [push, pull_request]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-node@v4\n"
            "        with:\n"
            "          node-version: '20'\n"
            "      - run: npm ci\n"
            "      - run: npm test\n"
            "      - run: npm run lint\n"
        ),
        ".pre-commit-config.yaml": (
            "repos:\n"
            "  - repo: https://github.com/pre-commit/mirrors-eslint\n"
            "    rev: v8.56.0\n"
            "    hooks:\n"
            "      - id: eslint\n"
        ),
        "CLAUDE.md": (
            "# $project_name -- Project Instructions\n\n"
            "## What this project is\n\n"
            "(Describe your project here.)\n\n"
            "## Conventions\n\n"
            "- Node.js 20+, TypeScript\n"
            "- Jest/Vitest for tests, conventional commits\n"
            "- ESLint + Prettier for lint + format\n"
        ),
        "docs/index.md": "# $project_name\n\nProject documentation.\n",
        "docs/architecture.mmd": "graph TD\n    A[Module A] --> B[Module B]\n",
        ".claude/workflow.json": "",
    },
}


def bootstrap(
    project_root: Path,
    project_type: str | None = None,
) -> list[str]:
    if project_type is None:
        project_type = detect_project_type(project_root)
    if project_type == "unknown":
        project_type = "python"

    templates = TEMPLATES.get(project_type, TEMPLATES["python"])
    project_name = project_root.name
    created: list[str] = []

    for rel_path, content in sorted(templates.items()):
        full = project_root / rel_path
        if full.exists():
            continue
        full.parent.mkdir(parents=True, exist_ok=True)

        if rel_path == ".claude/workflow.json":
            from superpower_workflow.cli import _cmd_init

            _cmd_init(project_root)
            created.append(rel_path)
            continue

        rendered = render_template(content, project_name=project_name)
        full.write_text(rendered)
        created.append(rel_path)

    return created
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/bootstrap.py tests/test_bootstrap.py --fix
ruff format src/superpower_workflow/bootstrap.py tests/test_bootstrap.py
git add src/superpower_workflow/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: add bootstrap project scaffolding with Python and TypeScript templates"
```

---

### Task 7: Bootstrap + Upgrade CLI subcommands

**Files:**
- Edit: `src/superpower_workflow/cli.py`
- Modify: `tests/test_bootstrap.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_bootstrap.py -- add class

from unittest.mock import patch


class TestBootstrapCLI:
    def test_bootstrap_subcommand_exists(self):
        from superpower_workflow.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["bootstrap"])
        assert args.command == "bootstrap"

    def test_bootstrap_type_flag(self):
        from superpower_workflow.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["bootstrap", "--type", "typescript"])
        assert args.project_type == "typescript"

    def test_upgrade_subcommand_exists(self):
        from superpower_workflow.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["upgrade"])
        assert args.command == "upgrade"

    def test_upgrade_dry_run_flag(self):
        from superpower_workflow.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["upgrade", "--dry-run"])
        assert args.dry_run is True
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add subcommands to CLI**

In `cli.py` `build_parser()`, add after the `run_p` block:

```python
bootstrap_p = sub.add_parser("bootstrap", help="One-command project setup")
bootstrap_p.add_argument(
    "--type",
    dest="project_type",
    default=None,
    help="Project type (python, typescript). Auto-detected if omitted.",
)

upgrade_p = sub.add_parser("upgrade", help="Detect and upgrade outdated dependencies")
upgrade_p.add_argument("--dry-run", action="store_true", help="List outdated deps without upgrading")
```

In `main()`, add command handlers:

```python
elif args.command == "bootstrap":
    from superpower_workflow.bootstrap import bootstrap

    cwd = Path.cwd()
    created = bootstrap(cwd, project_type=args.project_type)
    if created:
        print(f"  Created {len(created)} files:")
        for f in created:
            print(f"    {f}")
    else:
        print("  All files already exist. Nothing to do.")

elif args.command == "upgrade":
    from superpower_workflow.upgrade import detect_package_manager, list_outdated

    cwd = Path.cwd()
    pm = detect_package_manager(cwd)
    if pm == "unknown":
        print("  Could not detect package manager.")
        sys.exit(1)
    outdated = list_outdated(pm, cwd=str(cwd))
    if not outdated:
        print("  All dependencies are up to date.")
    else:
        print(f"  Found {len(outdated)} outdated dependencies:")
        for dep in outdated:
            flag = " [BREAKING]" if dep.is_breaking else ""
            print(f"    {dep.name}: {dep.current} -> {dep.latest}{flag}")
    if args.dry_run:
        return
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_bootstrap.py --fix
ruff format src/superpower_workflow/cli.py tests/test_bootstrap.py
git add src/superpower_workflow/cli.py tests/test_bootstrap.py
git commit -m "feat: add bootstrap and upgrade CLI subcommands"
```

---

### Task 8: Upgrade detection -- outdated deps

**Files:**
- New: `src/superpower_workflow/upgrade.py`
- New: `tests/test_upgrade.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_upgrade.py
from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.upgrade import (
    OutdatedDep,
    UpgradeResult,
    detect_package_manager,
    is_major_bump,
    list_outdated,
    perform_upgrade,
)


class TestDetectPackageManager:
    def test_detects_pip(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        assert detect_package_manager(tmp_path) == "pip"

    def test_detects_npm(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "app"}')
        assert detect_package_manager(tmp_path) == "npm"

    def test_detects_requirements(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        assert detect_package_manager(tmp_path) == "pip"

    def test_unknown(self, tmp_path: Path):
        assert detect_package_manager(tmp_path) == "unknown"


class TestIsMajorBump:
    def test_major_bump(self):
        assert is_major_bump("1.2.3", "2.0.0") is True

    def test_minor_bump(self):
        assert is_major_bump("1.2.3", "1.3.0") is False

    def test_patch_bump(self):
        assert is_major_bump("1.2.3", "1.2.4") is False

    def test_same_version(self):
        assert is_major_bump("1.0.0", "1.0.0") is False

    def test_malformed_version(self):
        assert is_major_bump("abc", "def") is False


class TestListOutdatedPip:
    def test_parses_pip_json(self):
        pip_output = json.dumps([
            {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"},
            {"name": "flask", "version": "2.3.0", "latest_version": "3.0.0"},
        ])
        result = CompletedProcess(args=[], returncode=0, stdout=pip_output, stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert len(deps) == 2
        assert deps[0].name == "requests"
        assert deps[0].is_breaking is False
        assert deps[1].name == "flask"
        assert deps[1].is_breaking is True

    def test_empty_output(self):
        result = CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert deps == []

    def test_pip_failure(self):
        result = CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert deps == []


class TestListOutdatedNpm:
    def test_parses_npm_json(self):
        npm_output = json.dumps({
            "lodash": {"current": "4.17.0", "latest": "4.17.21"},
            "react": {"current": "17.0.2", "latest": "18.2.0"},
        })
        result = CompletedProcess(args=[], returncode=1, stdout=npm_output, stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("npm")
        assert len(deps) == 2
        breaking = [d for d in deps if d.is_breaking]
        assert len(breaking) == 1
        assert breaking[0].name == "react"

    def test_unknown_manager_returns_empty(self):
        deps = list_outdated("unknown")
        assert deps == []


class TestPerformUpgrade:
    def test_creates_branch_for_breaking_dep(self):
        dep = OutdatedDep(name="flask", current="2.3.0", latest="3.0.0", is_breaking=True)
        with patch("superpower_workflow.upgrade.subprocess.run") as mock:
            mock.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            result = perform_upgrade(dep, cwd=".")
        branch_calls = [c for c in mock.call_args_list if "checkout" in str(c)]
        assert len(branch_calls) >= 1
        assert result.branch == "upgrade/flask-2.3.0-to-3.0.0"

    def test_non_breaking_upgrade_bumps_in_place(self):
        dep = OutdatedDep(name="requests", current="2.28.0", latest="2.31.0", is_breaking=False)
        with patch("superpower_workflow.upgrade.subprocess.run") as mock:
            mock.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            result = perform_upgrade(dep, cwd=".")
        assert result.branch is None
        assert result.upgraded is True

    def test_pip_install_failure(self):
        dep = OutdatedDep(name="broken", current="1.0", latest="2.0", is_breaking=False)
        with patch("superpower_workflow.upgrade.subprocess.run") as mock:
            mock.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            result = perform_upgrade(dep, cwd=".")
        assert result.upgraded is False
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/upgrade.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OutdatedDep:
    name: str
    current: str
    latest: str
    is_breaking: bool


def detect_package_manager(project_root: Path) -> str:
    if (project_root / "pyproject.toml").exists():
        return "pip"
    if (project_root / "requirements.txt").exists():
        return "pip"
    if (project_root / "package.json").exists():
        return "npm"
    if (project_root / "Cargo.toml").exists():
        return "cargo"
    return "unknown"


def is_major_bump(current: str, latest: str) -> bool:
    try:
        cur_major = int(current.split(".")[0])
        lat_major = int(latest.split(".")[0])
        return lat_major > cur_major
    except (ValueError, IndexError):
        return False


def list_outdated(package_manager: str, cwd: str = ".") -> list[OutdatedDep]:
    if package_manager == "pip":
        return _pip_outdated(cwd)
    elif package_manager == "npm":
        return _npm_outdated(cwd)
    return []


def _pip_outdated(cwd: str) -> list[OutdatedDep]:
    result = subprocess.run(
        ["pip", "list", "--outdated", "--format=json"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )
    if result.returncode != 0:
        return []
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    deps: list[OutdatedDep] = []
    for item in items:
        current = item.get("version", "0.0.0")
        latest = item.get("latest_version", "0.0.0")
        deps.append(
            OutdatedDep(
                name=item["name"],
                current=current,
                latest=latest,
                is_breaking=is_major_bump(current, latest),
            )
        )
    return deps


def _npm_outdated(cwd: str) -> list[OutdatedDep]:
    result = subprocess.run(
        ["npm", "outdated", "--json"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    deps: list[OutdatedDep] = []
    for name, info in items.items():
        current = info.get("current", "0.0.0")
        latest = info.get("latest", "0.0.0")
        deps.append(
            OutdatedDep(
                name=name,
                current=current,
                latest=latest,
                is_breaking=is_major_bump(current, latest),
            )
        )
    return deps


@dataclass
class UpgradeResult:
    name: str
    upgraded: bool
    branch: str | None = None
    error: str = ""


def perform_upgrade(dep: OutdatedDep, cwd: str = ".") -> UpgradeResult:
    if dep.is_breaking:
        branch = f"upgrade/{dep.name}-{dep.current}-to-{dep.latest}"
        checkout = subprocess.run(
            ["git", "checkout", "-b", branch],
            capture_output=True, text=True, cwd=cwd, timeout=30,
        )
        if checkout.returncode != 0:
            return UpgradeResult(name=dep.name, upgraded=False, error=checkout.stderr.strip())

        install = subprocess.run(
            ["pip", "install", f"{dep.name}=={dep.latest}"],
            capture_output=True, text=True, cwd=cwd, timeout=120,
        )
        if install.returncode != 0:
            subprocess.run(["git", "checkout", "-"], capture_output=True, cwd=cwd, timeout=10)
            subprocess.run(["git", "branch", "-D", branch], capture_output=True, cwd=cwd, timeout=10)
            return UpgradeResult(name=dep.name, upgraded=False, error=install.stderr.strip())

        return UpgradeResult(name=dep.name, upgraded=True, branch=branch)

    install = subprocess.run(
        ["pip", "install", f"{dep.name}=={dep.latest}"],
        capture_output=True, text=True, cwd=cwd, timeout=120,
    )
    if install.returncode != 0:
        return UpgradeResult(name=dep.name, upgraded=False, error=install.stderr.strip())

    return UpgradeResult(name=dep.name, upgraded=True)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/upgrade.py tests/test_upgrade.py --fix
ruff format src/superpower_workflow/upgrade.py tests/test_upgrade.py
git add src/superpower_workflow/upgrade.py tests/test_upgrade.py
git commit -m "feat: add dependency upgrade detection with pip and npm support"
```

---

### Task 9: Plugin interface -- base class + PluginVetoError

**Files:**
- New: `src/superpower_workflow/plugins/__init__.py`
- New: `src/superpower_workflow/plugins/interface.py`
- New: `tests/test_plugin_interface.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_plugin_interface.py
from __future__ import annotations

import pytest

from superpower_workflow.plugins.interface import Plugin, PluginVetoError


class TestPlugin:
    def test_default_name(self):
        p = Plugin()
        assert p.name == "unnamed"

    def test_default_version(self):
        p = Plugin()
        assert p.version == "0.0.0"

    def test_pre_phase_is_noop(self):
        p = Plugin()
        p.pre_phase("plan", {"name": "m1"})

    def test_post_phase_is_noop(self):
        p = Plugin()
        p.post_phase("plan", {"name": "m1"}, {"success": True})

    def test_pre_commit_is_noop(self):
        p = Plugin()
        p.pre_commit({"name": "m1"}, ["src/foo.py"])

    def test_post_milestone_is_noop(self):
        p = Plugin()
        p.post_milestone({"name": "m1"}, 5.0)


class TestPluginSubclass:
    def test_custom_plugin(self):
        class MyPlugin(Plugin):
            name = "my-plugin"
            version = "1.0.0"

            def __init__(self):
                self.phases_seen: list[str] = []

            def pre_phase(self, phase: str, milestone: dict) -> None:
                self.phases_seen.append(phase)

        p = MyPlugin()
        p.pre_phase("plan", {"name": "m1"})
        assert p.phases_seen == ["plan"]

    def test_veto_from_pre_phase(self):
        class VetoPlugin(Plugin):
            name = "veto"

            def pre_phase(self, phase: str, milestone: dict) -> None:
                raise PluginVetoError("Blocked by policy")

        p = VetoPlugin()
        with pytest.raises(PluginVetoError, match="Blocked by policy"):
            p.pre_phase("plan", {"name": "m1"})

    def test_veto_from_pre_commit(self):
        class VetoPlugin(Plugin):
            name = "veto"

            def pre_commit(self, milestone: dict, files: list[str]) -> None:
                if any("secrets" in f for f in files):
                    raise PluginVetoError("Cannot commit secrets")

        p = VetoPlugin()
        with pytest.raises(PluginVetoError, match="secrets"):
            p.pre_commit({"name": "m1"}, ["src/secrets.py"])


class TestPluginVetoError:
    def test_is_exception(self):
        assert issubclass(PluginVetoError, Exception)

    def test_message_preserved(self):
        e = PluginVetoError("test reason")
        assert str(e) == "test reason"
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/plugins/__init__.py
from __future__ import annotations

from superpower_workflow.plugins.interface import Plugin, PluginVetoError

__all__ = [
    "Plugin",
    "PluginVetoError",
]
```

```python
# src/superpower_workflow/plugins/interface.py
from __future__ import annotations


class PluginVetoError(Exception):
    """Raised by a plugin to block execution at a lifecycle hook."""


class Plugin:
    """Base class for superpower-workflow plugins.

    All methods are optional no-ops. Override only what you need.
    Raise PluginVetoError from pre_phase or pre_commit to block execution.
    """

    name: str = "unnamed"
    version: str = "0.0.0"

    def pre_phase(self, phase: str, milestone: dict) -> None:
        pass

    def post_phase(self, phase: str, milestone: dict, result: dict) -> None:
        pass

    def pre_commit(self, milestone: dict, files: list[str]) -> None:
        pass

    def post_milestone(self, milestone: dict, cost: float) -> None:
        pass
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/plugins/ tests/test_plugin_interface.py --fix
ruff format src/superpower_workflow/plugins/ tests/test_plugin_interface.py
git add src/superpower_workflow/plugins/__init__.py src/superpower_workflow/plugins/interface.py tests/test_plugin_interface.py
git commit -m "feat: add Plugin base class and PluginVetoError for lifecycle hooks"
```

---

### Task 10: Plugin loader -- entry-point discovery

**Files:**
- New: `src/superpower_workflow/plugins/loader.py`
- New: `tests/test_plugin_loader.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_plugin_loader.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from superpower_workflow.plugins.interface import Plugin
from superpower_workflow.plugins.loader import ENTRY_POINT_GROUP, load_plugins


class _TestPlugin(Plugin):
    name = "test-plugin"
    version = "1.0.0"


class _BadPlugin:
    """Not a Plugin subclass."""

    name = "bad"


class TestLoadPlugins:
    def test_loads_valid_plugin(self):
        ep = MagicMock()
        ep.load.return_value = _TestPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "test-plugin"

    def test_skips_non_plugin_class(self):
        ep = MagicMock()
        ep.load.return_value = _BadPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins()
        assert len(plugins) == 0

    def test_skips_broken_entry_point(self):
        ep = MagicMock()
        ep.load.side_effect = ImportError("missing module")
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins()
        assert len(plugins) == 0

    def test_loads_multiple_plugins(self):
        ep1 = MagicMock()
        ep1.load.return_value = _TestPlugin
        ep2 = MagicMock()
        ep2.load.return_value = _TestPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep1, ep2]):
            plugins = load_plugins()
        assert len(plugins) == 2

    def test_uses_correct_entry_point_group(self):
        assert ENTRY_POINT_GROUP == "superpower_workflow.plugins"

    def test_filters_blocked_plugins(self):
        ep = MagicMock()
        ep.load.return_value = _TestPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins(blocked=["test-plugin"])
        assert len(plugins) == 0

    def test_empty_when_no_entry_points(self):
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[]):
            plugins = load_plugins()
        assert plugins == []
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/plugins/loader.py
from __future__ import annotations

from importlib.metadata import entry_points

from superpower_workflow.plugins.interface import Plugin

ENTRY_POINT_GROUP = "superpower_workflow.plugins"


def load_plugins(blocked: list[str] | None = None) -> list[Plugin]:
    blocked_set = set(blocked or [])
    plugins: list[Plugin] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            instance = cls()
            if isinstance(instance, Plugin):
                if instance.name not in blocked_set:
                    plugins.append(instance)
        except Exception:
            continue
    return plugins
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/plugins/loader.py tests/test_plugin_loader.py --fix
ruff format src/superpower_workflow/plugins/loader.py tests/test_plugin_loader.py
git add src/superpower_workflow/plugins/loader.py tests/test_plugin_loader.py
git commit -m "feat: add entry-point-based plugin loader with blocked list support"
```

---

### Task 11: Plugin CLI -- `sw plugin list/add/remove`

**Files:**
- Edit: `src/superpower_workflow/cli.py`
- New: `tests/test_plugin_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_plugin_cli.py
from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from superpower_workflow.cli import build_parser


class TestPluginCLI:
    def test_plugin_list_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["plugin", "list"])
        assert args.command == "plugin"
        assert args.plugin_command == "list"

    def test_plugin_add_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["plugin", "add", "my-plugin"])
        assert args.command == "plugin"
        assert args.plugin_command == "add"
        assert args.plugin_name == "my-plugin"

    def test_plugin_remove_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["plugin", "remove", "my-plugin"])
        assert args.command == "plugin"
        assert args.plugin_command == "remove"
        assert args.plugin_name == "my-plugin"


class TestPluginAddInstalls:
    def test_add_calls_pip_install(self):
        result = CompletedProcess(args=[], returncode=0, stdout="Installed", stderr="")
        with patch("superpower_workflow.cli.subprocess.run", return_value=result) as mock:
            from superpower_workflow.cli import _cmd_plugin_add

            _cmd_plugin_add("my-plugin")
        cmd = mock.call_args[0][0]
        assert "pip" in cmd
        assert "install" in cmd
        assert "sw-plugin-my-plugin" in cmd

    def test_add_failure_prints_error(self, capsys):
        result = CompletedProcess(args=[], returncode=1, stdout="", stderr="not found")
        with patch("superpower_workflow.cli.subprocess.run", return_value=result):
            from superpower_workflow.cli import _cmd_plugin_add

            _cmd_plugin_add("nonexistent")
        captured = capsys.readouterr()
        assert "Failed" in captured.out or "failed" in captured.out.lower()
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add plugin subcommands to CLI**

In `cli.py` `build_parser()`, add after the `upgrade_p` block:

```python
plugin_p = sub.add_parser("plugin", help="Manage plugins")
plugin_sub = plugin_p.add_subparsers(dest="plugin_command")
plugin_sub.add_parser("list", help="Show installed plugins")
add_p = plugin_sub.add_parser("add", help="Install a plugin")
add_p.add_argument("plugin_name", help="Plugin name (installs sw-plugin-{name})")
remove_p = plugin_sub.add_parser("remove", help="Remove a plugin")
remove_p.add_argument("plugin_name", help="Plugin name (uninstalls sw-plugin-{name})")
```

Add `import re` and `import subprocess` at top of cli.py (subprocess not yet imported there), then add handler functions and wire into `main()`:

```python
import subprocess  # add at top of cli.py

_PLUGIN_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _validate_plugin_name(name: str) -> bool:
    return bool(_PLUGIN_NAME_RE.match(name)) and len(name) <= 64


def _cmd_plugin_add(name: str) -> None:
    if not _validate_plugin_name(name):
        print(f"  Invalid plugin name: {name!r}. Must be alphanumeric with hyphens/underscores.")
        return
    package = f"sw-plugin-{name}"
    result = subprocess.run(
        ["pip", "install", package],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0:
        print(f"  Installed {package}")
    else:
        print(f"  Failed to install {package}: {result.stderr.strip()}")


def _cmd_plugin_remove(name: str) -> None:
    if not _validate_plugin_name(name):
        print(f"  Invalid plugin name: {name!r}. Must be alphanumeric with hyphens/underscores.")
        return
    package = f"sw-plugin-{name}"
    result = subprocess.run(
        ["pip", "uninstall", "-y", package],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        print(f"  Removed {package}")
    else:
        print(f"  Failed to remove {package}: {result.stderr.strip()}")
```

In `main()`:

```python
elif args.command == "plugin":
    if args.plugin_command == "list":
        from superpower_workflow.plugins.loader import load_plugins

        plugins = load_plugins()
        if not plugins:
            print("  No plugins installed.")
        else:
            for p in plugins:
                print(f"  {p.name} v{p.version}")
    elif args.plugin_command == "add":
        _cmd_plugin_add(args.plugin_name)
    elif args.plugin_command == "remove":
        _cmd_plugin_remove(args.plugin_name)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_plugin_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_plugin_cli.py
git add src/superpower_workflow/cli.py tests/test_plugin_cli.py
git commit -m "feat: add sw plugin list/add/remove CLI subcommands"
```

---

### Task 12: Orchestrator plugin hooks -- wire into phase lifecycle

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- New: `tests/test_docs_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_orchestrator.py
from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.plugins.interface import Plugin, PluginVetoError
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import load_state


def _config(tmp_path: Path, **overrides) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "convergence": {"max_iterations": 1, "min_gaps_for_substantial": 20, "persistent_gap_downgrade_after": 3},
        "verify_commands": {"test": "echo ok", "lint": None, "format": None},
        "git_strategy": "main",
        "telemetry": {"enabled": False},
        "milestones": [{"name": "m1"}],
        "plugins": {"enabled": True, "blocked": []},
        "docs": {
            "readme": {"enabled": False, "template": None, "sections": []},
            "changelog": {"enabled": False},
            "api": {"tool": "sphinx", "output_dir": "docs/api"},
            "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
        },
    }
    config.update(overrides)
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    (tmp_path / "spec.md").write_text("# Spec")


def _ok_result() -> ClaudeResult:
    return ClaudeResult(text="done", is_error=False, cost_usd=1.0)


def _smart_subprocess(cmd, **kwargs):
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    if "git" in cmd_str and "rev-parse" in cmd_str:
        return CompletedProcess(args=cmd, returncode=0, stdout="abc1234", stderr="")
    if "git" in cmd_str and ("tag" in cmd_str or "push" in cmd_str):
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    if "echo" in cmd_str:
        return CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class TestOrchestratorPluginHooks:
    def test_loads_plugins_on_init(self, tmp_path: Path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]) as mock_load,
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
        mock_load.assert_called_once()

    def test_calls_pre_phase_for_each_phase(self, tmp_path: Path):
        _config(tmp_path)
        mock_plugin = MagicMock(spec=Plugin)
        mock_plugin.name = "test"
        mock_plugin.version = "1.0"
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[mock_plugin]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        pre_phase_calls = mock_plugin.pre_phase.call_args_list
        phases_seen = [c.args[0] for c in pre_phase_calls]
        assert "plan" in phases_seen
        assert "implement" in phases_seen
        assert len(phases_seen) >= 3

    def test_calls_post_milestone(self, tmp_path: Path):
        _config(tmp_path)
        mock_plugin = MagicMock(spec=Plugin)
        mock_plugin.name = "test"
        mock_plugin.version = "1.0"
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[mock_plugin]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_plugin.post_milestone.assert_called()

    def test_veto_stops_phase(self, tmp_path: Path):
        _config(tmp_path)
        mock_plugin = MagicMock(spec=Plugin)
        mock_plugin.name = "veto"
        mock_plugin.version = "1.0"
        mock_plugin.pre_phase.side_effect = PluginVetoError("blocked")
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[mock_plugin]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.failed

    def test_disabled_plugins_not_loaded(self, tmp_path: Path):
        _config(tmp_path, plugins={"enabled": False, "blocked": []})
        with (
            patch("superpower_workflow.orchestrator.load_plugins") as mock_load,
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
        mock_load.assert_not_called()

    def test_blocked_plugins_passed_to_loader(self, tmp_path: Path):
        _config(tmp_path, plugins={"enabled": True, "blocked": ["bad-plugin"]})
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]) as mock_load,
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        ):
            orch = Orchestrator(tmp_path)
        mock_load.assert_called_once_with(blocked=["bad-plugin"])
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Wire plugins into orchestrator**

In `orchestrator.py`, add import:

```python
from superpower_workflow.plugins.interface import PluginVetoError
from superpower_workflow.plugins.loader import load_plugins
```

In `Orchestrator.__init__`, after secrets handling:

```python
plugins_config = self.config.get("plugins", {})
if plugins_config.get("enabled", True):
    blocked = plugins_config.get("blocked", [])
    self._plugins = load_plugins(blocked=blocked)
else:
    self._plugins = []
```

Add helper methods:

```python
def _call_pre_phase(self, phase: str, milestone: dict) -> None:
    for plugin in self._plugins:
        plugin.pre_phase(phase, milestone)

def _call_post_phase(self, phase: str, milestone: dict, result: dict) -> None:
    for plugin in self._plugins:
        plugin.post_phase(phase, milestone, result)

def _call_pre_commit(self, milestone: dict, files: list[str]) -> None:
    for plugin in self._plugins:
        plugin.pre_commit(milestone, files)

def _call_post_milestone(self, milestone: dict, cost: float) -> None:
    for plugin in self._plugins:
        plugin.post_milestone(milestone, cost)
```

In `_run_milestone`, wrap each phase call with pre/post hooks. Before each phase (plan, implement, review, push):

```python
try:
    self._call_pre_phase("plan", ms)
except PluginVetoError as e:
    raise _PhaseError("plan", str(e)) from e
```

After each phase returns:

```python
self._call_post_phase("plan", ms, {"cost": cost_a})
```

Similarly for phases B, C, D. Before Phase D (push/tag), invoke `pre_commit`:

```python
self._call_pre_commit(ms, [])  # files list populated by git diff if available
```

After milestone completes (before returning cost):

```python
self._call_post_milestone(ms, total_cost)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_docs_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_docs_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_docs_orchestrator.py
git commit -m "feat: wire plugin lifecycle hooks into orchestrator phase execution"
```

---

### Task 13: Orchestrator docs hooks -- post-milestone documentation

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_docs_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_orchestrator.py -- add class

class TestOrchestratorDocsHooks:
    def test_generates_changelog_when_enabled(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": True},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_changelog", return_value="# Changelog") as mock_cl,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_cl.assert_called_once()

    def test_generates_diagram_when_enabled(self, tmp_path: Path):
        src = tmp_path / "src" / "mypackage"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": False},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": True, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_mermaid", return_value="graph TD") as mock_mm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_mm.assert_called_once()

    def test_skips_docs_when_all_disabled(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": False},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_changelog") as mock_cl,
            patch("superpower_workflow.orchestrator.generate_mermaid") as mock_mm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_cl.assert_not_called()
        mock_mm.assert_not_called()

    def test_generates_readme_when_enabled(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": True, "template": None, "sections": ["overview"]},
                "changelog": {"enabled": False},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_readme", return_value="# README") as mock_rm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        mock_rm.assert_called_once()

    def test_docs_failure_does_not_fail_milestone(self, tmp_path: Path):
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": True},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": False, "output": "docs/architecture.mmd"},
            },
        )
        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_changelog", side_effect=RuntimeError("git broke")),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add docs generation to orchestrator**

In `orchestrator.py`, add imports:

```python
from superpower_workflow.docs.api_docs import build_api_docs
from superpower_workflow.docs.changelog import generate_changelog
from superpower_workflow.docs.diagrams import generate_mermaid
from superpower_workflow.docs.readme_gen import generate_readme
```

Add a `_generate_docs` method to `Orchestrator`:

```python
def _generate_docs(self, ms: dict) -> None:
    docs_config = self.config.get("docs", {})
    generated: list[str] = []

    if docs_config.get("changelog", {}).get("enabled", False):
        try:
            changelog = generate_changelog(cwd=self.cwd)
            if changelog:
                cl_path = Path(self.cwd) / "CHANGELOG.md"
                cl_path.write_text(changelog)
                generated.append("CHANGELOG.md")
        except Exception:
            pass

    if docs_config.get("diagrams", {}).get("enabled", False):
        try:
            src_dir = Path(self.cwd) / "src"
            if src_dir.exists():
                mermaid = generate_mermaid(src_dir)
                output = docs_config["diagrams"].get("output", "docs/architecture.mmd")
                out_path = Path(self.cwd) / output
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(mermaid)
                generated.append(output)
        except Exception:
            pass

    api_config = docs_config.get("api", {})
    if api_config.get("tool"):
        try:
            src_dir = Path(self.cwd) / "src"
            out_dir = Path(self.cwd) / api_config.get("output_dir", "docs/api")
            if src_dir.exists():
                build_api_docs(src_dir, out_dir, tool=api_config["tool"], cwd=self.cwd)
                generated.append(api_config.get("output_dir", "docs/api"))
        except Exception:
            pass

    readme_config = docs_config.get("readme", {})
    if readme_config.get("enabled", False):
        try:
            content = generate_readme(
                Path(self.cwd),
                model=self.config["model"],
                effort=self.config.get("effort", {}).get("review", "high"),
                budget=self.config.get("budgets", {}).get("push", 3),
                template=readme_config.get("template"),
                sections=readme_config.get("sections"),
                cwd=self.cwd,
            )
            if content:
                (Path(self.cwd) / "README.md").write_text(content)
                generated.append("README.md")
        except Exception:
            pass

    if generated:
        self._commit_docs(generated)


def _commit_docs(self, files: list[str]) -> None:
    try:
        subprocess.run(
            ["git", "add"] + files,
            capture_output=True, text=True, cwd=self.cwd, timeout=30,
        )
        model = self.config.get("model", "opus")
        subprocess.run(
            ["git", "commit", "-m", "docs: update generated documentation",
             "--trailer", f"Generated-By: {model}"],
            capture_output=True, text=True, cwd=self.cwd, timeout=30,
        )
    except Exception:
        pass
```

Call `_generate_docs(ms)` after each milestone completes, before returning cost (in `_run_milestone`, after Phase D succeeds).

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_docs_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_docs_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_docs_orchestrator.py
git commit -m "feat: add post-milestone documentation generation to orchestrator"
```

---

### Task 14: Telemetry events -- DocsGenerated, PluginLoaded, BootstrapCompleted, UpgradeChecked

**Files:**
- Edit: `src/superpower_workflow/telemetry.py`
- New: `tests/test_docs_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_telemetry.py
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
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add event dataclasses to telemetry.py**

```python
# Add to telemetry.py after existing event dataclasses

@dataclass
class DocsGenerated:
    doc_type: str
    output_path: str
    type: str = "docs_generated"


@dataclass
class BootstrapCompleted:
    project_type: str
    files_created: int
    type: str = "bootstrap_completed"


@dataclass
class PluginLoaded:
    plugin_name: str
    plugin_version: str
    type: str = "plugin_loaded"


@dataclass
class PluginVetoed:
    plugin_name: str
    phase: str
    reason: str
    type: str = "plugin_vetoed"


@dataclass
class UpgradeChecked:
    outdated_count: int
    breaking_count: int
    type: str = "upgrade_checked"
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_docs_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_docs_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_docs_telemetry.py
git commit -m "feat: add telemetry events for docs generation, plugins, bootstrap, and upgrade"
```

---

### Task 15: Package exports -- `__all__` for docs + plugins

**Files:**
- Edit: `src/superpower_workflow/docs/__init__.py`
- Edit: `src/superpower_workflow/plugins/__init__.py`
- New: `tests/test_docs_exports.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_exports.py
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
        from superpower_workflow.telemetry import (
            BootstrapCompleted,
            DocsGenerated,
            PluginLoaded,
            PluginVetoed,
            UpgradeChecked,
        )

        assert DocsGenerated is not None
        assert BootstrapCompleted is not None
        assert PluginLoaded is not None
        assert PluginVetoed is not None
        assert UpgradeChecked is not None
```

- [ ] **Step 2: Run tests -- expect FAIL** (exports incomplete)

- [ ] **Step 3: Update package exports**

```python
# src/superpower_workflow/docs/__init__.py
from __future__ import annotations

from superpower_workflow.docs.api_docs import build_api_docs
from superpower_workflow.docs.changelog import generate_changelog
from superpower_workflow.docs.diagrams import generate_mermaid
from superpower_workflow.docs.readme_gen import generate_readme

__all__ = [
    "build_api_docs",
    "generate_changelog",
    "generate_mermaid",
    "generate_readme",
]
```

```python
# src/superpower_workflow/plugins/__init__.py
from __future__ import annotations

from superpower_workflow.plugins.interface import Plugin, PluginVetoError
from superpower_workflow.plugins.loader import ENTRY_POINT_GROUP, load_plugins

__all__ = [
    "ENTRY_POINT_GROUP",
    "Plugin",
    "PluginVetoError",
    "load_plugins",
]
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/docs/__init__.py src/superpower_workflow/plugins/__init__.py tests/test_docs_exports.py --fix
ruff format src/superpower_workflow/docs/__init__.py src/superpower_workflow/plugins/__init__.py tests/test_docs_exports.py
git add src/superpower_workflow/docs/__init__.py src/superpower_workflow/plugins/__init__.py tests/test_docs_exports.py
git commit -m "feat: add complete __all__ exports for docs and plugins packages"
```

---

### Task 16: Update workflow.json template

**Files:**
- Edit: `templates/workflow.json`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_config.py -- add class

class TestTemplateWorkflowJson:
    def test_template_has_docs_section(self):
        import json
        from pathlib import Path

        template_path = Path(__file__).resolve().parent.parent / "templates" / "workflow.json"
        config = json.loads(template_path.read_text())
        assert "docs" in config

    def test_template_has_plugins_section(self):
        import json
        from pathlib import Path

        template_path = Path(__file__).resolve().parent.parent / "templates" / "workflow.json"
        config = json.loads(template_path.read_text())
        assert "plugins" in config
```

- [ ] **Step 2: Run tests -- expect FAIL** (template doesn't have docs/plugins yet)

- [ ] **Step 3: Update template**

Add `docs` and `plugins` sections to `templates/workflow.json` matching the structure from Task 1:

```json
{
    "docs": {
        "readme": {
            "enabled": false,
            "template": null,
            "sections": ["overview", "quickstart", "architecture", "contributing"]
        },
        "changelog": {
            "enabled": true
        },
        "api": {
            "tool": "sphinx",
            "output_dir": "docs/api"
        },
        "diagrams": {
            "enabled": true,
            "output": "docs/architecture.mmd"
        }
    },
    "plugins": {
        "enabled": true,
        "blocked": []
    }
}
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check tests/test_docs_config.py --fix
ruff format tests/test_docs_config.py
git add templates/workflow.json tests/test_docs_config.py
git commit -m "feat: add docs and plugins sections to workflow.json template"
```

---

### Task 17: Integration tests -- end-to-end scenarios

**Files:**
- New: `tests/test_docs_plugins_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_docs_plugins_integration.py
from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from superpower_workflow.bootstrap import bootstrap, detect_project_type
from superpower_workflow.docs.changelog import generate_changelog
from superpower_workflow.docs.diagrams import generate_mermaid
from superpower_workflow.orchestrator import Orchestrator
from superpower_workflow.plugins.interface import Plugin, PluginVetoError
from superpower_workflow.plugins.loader import load_plugins
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import load_state
from superpower_workflow.upgrade import detect_package_manager, list_outdated


def _config(tmp_path: Path, **overrides) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 0,
        "convergence": {"max_iterations": 1, "min_gaps_for_substantial": 20, "persistent_gap_downgrade_after": 3},
        "verify_commands": {"test": "echo ok", "lint": None, "format": None},
        "git_strategy": "main",
        "telemetry": {"enabled": False},
        "milestones": [{"name": "m1"}],
        "plugins": {"enabled": True, "blocked": []},
        "docs": {
            "readme": {"enabled": False, "template": None, "sections": []},
            "changelog": {"enabled": True},
            "api": {"tool": "sphinx", "output_dir": "docs/api"},
            "diagrams": {"enabled": True, "output": "docs/architecture.mmd"},
        },
    }
    config.update(overrides)
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    (tmp_path / "spec.md").write_text("# Spec")


def _ok_result() -> ClaudeResult:
    return ClaudeResult(text="done", is_error=False, cost_usd=1.0)


def _smart_subprocess(cmd, **kwargs):
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    if "git" in cmd_str and "rev-parse" in cmd_str:
        return CompletedProcess(args=cmd, returncode=0, stdout="abc1234", stderr="")
    if "git" in cmd_str and "log" in cmd_str and "--format" in cmd_str:
        return CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="abc1234 feat: add login\ndef5678 fix: patch bug\n",
            stderr="",
        )
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class TestBootstrapThenRun:
    def test_bootstrap_creates_config_orchestrator_can_load(self, tmp_path: Path):
        bootstrap(tmp_path, project_type="python")
        config_path = tmp_path / ".claude" / "workflow.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "milestones" in config
        assert "docs" in config

    def test_bootstrap_auto_detect_and_scaffold(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        assert detect_project_type(tmp_path) == "python"
        created = bootstrap(tmp_path)
        assert len(created) > 0
        assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "docs" / "index.md").exists()


class TestDocsGeneration:
    def test_changelog_from_real_format(self):
        log = CompletedProcess(
            args=[],
            returncode=0,
            stdout="abc1234 feat: add feature\ndef5678 fix: bugfix\nghi9012 chore: cleanup\n",
            stderr="",
        )
        with patch("superpower_workflow.docs.changelog.subprocess.run", return_value=log):
            result = generate_changelog()
        assert "### Features" in result
        assert "### Bug Fixes" in result
        assert "### Chores" in result

    def test_mermaid_from_real_files(self, tmp_path: Path):
        pkg = tmp_path / "src" / "myapp"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("from myapp.core import run\n")
        (pkg / "core.py").write_text("from myapp.utils import helper\n")
        (pkg / "utils.py").write_text("")
        result = generate_mermaid(pkg, project_prefix="myapp")
        assert "graph TD" in result
        assert "myapp" in result
        assert "-->" in result


class TestPluginLifecycle:
    def test_plugin_hooks_called_during_run(self, tmp_path: Path):
        _config(tmp_path)
        tracker: list[str] = []

        class TrackingPlugin(Plugin):
            name = "tracker"
            version = "1.0"

            def pre_phase(self, phase, milestone):
                tracker.append(f"pre:{phase}")

            def post_phase(self, phase, milestone, result):
                tracker.append(f"post:{phase}")

            def post_milestone(self, milestone, cost):
                tracker.append(f"done:{milestone['name']}")

        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[TrackingPlugin()]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_changelog", return_value=""),
            patch("superpower_workflow.orchestrator.generate_mermaid", return_value="graph TD"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert any("pre:" in t for t in tracker)
        assert any("post:" in t for t in tracker)
        assert "done:m1" in tracker

    def test_multiple_plugins_all_called(self, tmp_path: Path):
        _config(tmp_path)

        class PluginA(Plugin):
            name = "a"
            version = "1.0"
            called = False

            def post_milestone(self, milestone, cost):
                PluginA.called = True

        class PluginB(Plugin):
            name = "b"
            version = "2.0"
            called = False

            def post_milestone(self, milestone, cost):
                PluginB.called = True

        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[PluginA(), PluginB()]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_changelog", return_value=""),
            patch("superpower_workflow.orchestrator.generate_mermaid", return_value="graph TD"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert PluginA.called
        assert PluginB.called


class TestUpgradeIntegration:
    def test_detect_and_list_outdated(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        assert detect_package_manager(tmp_path) == "pip"
        pip_output = json.dumps([
            {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"},
        ])
        result = CompletedProcess(args=[], returncode=0, stdout=pip_output, stderr="")
        with patch("superpower_workflow.upgrade.subprocess.run", return_value=result):
            deps = list_outdated("pip")
        assert len(deps) == 1
        assert deps[0].name == "requests"

    def test_upgrade_no_deps_file(self, tmp_path: Path):
        assert detect_package_manager(tmp_path) == "unknown"


class TestDocsAndPluginsTogether:
    def test_full_pipeline_with_docs_and_plugins(self, tmp_path: Path):
        src = tmp_path / "src" / "myapp"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("from myapp import __init__\n")
        _config(
            tmp_path,
            docs={
                "readme": {"enabled": False, "template": None, "sections": []},
                "changelog": {"enabled": True},
                "api": {"tool": "sphinx", "output_dir": "docs/api"},
                "diagrams": {"enabled": True, "output": "docs/architecture.mmd"},
            },
            plugins={"enabled": True, "blocked": []},
        )

        class CountPlugin(Plugin):
            name = "counter"
            version = "1.0"
            milestone_count = 0

            def post_milestone(self, milestone, cost):
                CountPlugin.milestone_count += 1

        CountPlugin.milestone_count = 0

        with (
            patch("superpower_workflow.orchestrator.load_plugins", return_value=[CountPlugin()]),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
            patch("superpower_workflow.orchestrator.generate_changelog", return_value="# Changes") as mock_cl,
            patch("superpower_workflow.orchestrator.generate_mermaid", return_value="graph TD") as mock_mm,
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
        assert CountPlugin.milestone_count == 1
        mock_cl.assert_called()
        mock_mm.assert_called()
```

- [ ] **Step 2: Run tests -- expect PASS** (if all prior tasks complete)

If any fail, debug and fix. This is the final integration verification.

- [ ] **Step 3: Full suite verification**

```bash
python -m pytest -v
python -m ruff check src/ tests/ --fix
python -m ruff format src/ tests/
```

- [ ] **Step 4: Lint + commit**

```bash
git add tests/test_docs_plugins_integration.py
git commit -m "test: add end-to-end docs, DX, and plugins integration tests"
```

---

## Self-Review

**Spec coverage:**
- SP7 README generation -> Task 5 (AI-assisted via run_claude)
- SP7 CHANGELOG generation -> Task 2 (deterministic conventional commit parsing)
- SP7 API docs -> Task 4 (Sphinx/MkDocs wrapper)
- SP7 Architecture diagrams -> Task 3 (Mermaid from Python imports)
- SP7 `sw bootstrap` -> Tasks 6, 7 (templates, renderer, CLI)
- SP7 `sw upgrade` -> Tasks 7, 8 (detection, CLI)
- SP7 Plugin system -> Tasks 9, 10, 11 (interface, loader, entry-point discovery)
- SP7 Plugin CLI -> Task 11 (`sw plugin list/add/remove`)
- Orchestrator plugin hooks -> Task 12 (pre_phase, post_phase, pre_commit, post_milestone)
- Orchestrator docs hooks -> Task 13 (post-milestone changelog, diagram, README)
- Telemetry -> Task 14 (5 new event types)
- Package exports -> Task 15 (__all__ for docs + plugins)
- Config schema -> Tasks 1, 16 (docs + plugins sections)
- Integration tests -> Task 17 (end-to-end scenarios)

**All roadmap SP7 interfaces covered:**
- Docs: generated post-milestone, committed alongside code
- Bootstrap: generates devcontainer, CI, hooks, CLAUDE.md, docs scaffold
- Plugins: entry-point-based discovery, `sw plugin add <name>`
- Plugin API: hooks into orchestrator lifecycle (pre-phase, post-phase, pre-commit, post-milestone)

**Open questions resolved:**
- README generation: opt-in (enabled: false by default)
- Plugin sandboxing: no sandboxing in v1 (trust model)
- `sw upgrade`: one branch per major, batch minors
- Architecture diagrams: only src/ (per spec)

**Placeholder scan:** No TBD, TODO, or "implement later."

**Type consistency:** All dataclasses use `from __future__ import annotations`. All subprocess calls include timeout. All new modules follow existing patterns. `run_claude` calls include required `effort` and `budget` parameters matching the actual function signature.

**Security:** Plugin names validated against `^[a-zA-Z0-9][a-zA-Z0-9_-]*$` before passing to pip. No shell injection possible (subprocess uses list, not string).

**Backward compatibility:** All new config sections are optional with defaults. Plugins default to enabled with empty blocked list. Docs generation defaults to changelog + diagrams on, readme off. No existing CLI commands or orchestrator behavior changed when config sections are absent.

**Zero new dependencies:** Everything uses stdlib (`string.Template`, `importlib.metadata`, `ast`, `subprocess`, `json`, `re`, `dataclasses`).

**Gaps addressed in ultrathink pass 1:**
- Fixed `run_claude` calls to include required `effort` and `budget` parameters (was missing, would cause runtime TypeError)
- Fixed CLI subprocess import (was aliased as `_subprocess`, breaking mock patch paths)
- Added plugin name validation to prevent untrusted input reaching pip
- Added `pre_commit` hook invocation before Phase D in orchestrator
- Added API docs generation to `_generate_docs` orchestrator method
- Added `_commit_docs` helper to commit generated docs with `Generated-By` trailer per spec
- Added `perform_upgrade` function for breaking change branch creation
- Strengthened Task 12 test assertion from `>= 1` to per-phase verification
- Fixed Task 16 template path test to use `__file__`-relative path instead of fragile CWD
