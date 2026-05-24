# SP7: Docs, DX & Plugins -- Design Spec

**Date:** 2026-05-24
**Spec version:** 1.0
**Status:** Draft
**Roadmap:** SP7 of 7 -> v0.8.0-v1.0.0
**Goal:** Auto-generate project documentation, provide one-command project bootstrap, and introduce a plugin system that lets the community extend every layer of superpower-workflow.

**Depends on:** SP1-SP6 (plugins wrap all features; docs consume telemetry from SP2).

---

## 1. Overview

Eight capabilities across three themes:

**Docs generation:**
1. **README generation** -- Claude reads CLAUDE.md + git log, generates updated README.md
2. **CHANGELOG generation** -- deterministic parsing of conventional commits
3. **API docs** -- Sphinx or MkDocs from docstrings
4. **Architecture diagrams** -- Mermaid dependency graphs from module imports

**Developer experience:**
5. **`sw bootstrap`** -- one-command project setup (devcontainer, CI, hooks, CLAUDE.md, docs)
6. **`sw upgrade`** -- detect outdated deps, generate upgrade PRs with migration code

**Plugin system:**
7. **Plugin loader** -- entry-point-based discovery (setuptools)
8. **`sw plugin add/list/remove`** -- manage community plugins

---

## 2. README Generation

### Trigger

Runs as post-milestone step (after Phase D or Phase E).

### Flow

1. Read CLAUDE.md for project context
2. Read last 5 git log entries for recent changes
3. Read telemetry summary (test count, coverage, milestone count) from SP2
4. Invoke claude -p: "Update README.md based on this context: {context}. Keep existing sections, update stats."
5. Commit updated README.md with trailer `Generated-By: {model}`

### Config

```json
{
  "docs": {
    "readme": {
      "enabled": true,
      "template": null,
      "sections": ["overview", "quickstart", "architecture", "contributing"]
    }
  }
}
```

If `template` is set, use it as the base structure instead of the existing README.

---

## 3. CHANGELOG Generation

### Implementation (deterministic, no AI)

```python
def generate_changelog(since_tag: str | None = None) -> str:
    fmt = "--format=%H %s"
    cmd = ["git", "log", fmt]
    if since_tag:
        cmd.append(f"{since_tag}..HEAD")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    groups: dict[str, list[str]] = {
        "feat": [], "fix": [], "refactor": [], "docs": [],
        "test": [], "chore": [], "other": [],
    }
    for line in result.stdout.strip().splitlines():
        sha, msg = line.split(" ", 1)
        prefix = msg.split(":")[0].split("(")[0].strip()
        bucket = prefix if prefix in groups else "other"
        groups[bucket].append(f"- {msg} ({sha[:7]})")
    
    return _render_changelog(groups)
```

Parses conventional commit prefixes (feat, fix, refactor, etc.), groups by type, renders markdown.

---

## 4. API Docs & Architecture Diagrams

### API docs

Auto-run after milestone completes:

- Python projects: `sphinx-apidoc -o docs/api src/` then `sphinx-build`
- Alternative: `mkdocs build` with `mkdocstrings` plugin

Config selects the tool:

```json
{
  "docs": {
    "api": {
      "tool": "sphinx",
      "output_dir": "docs/api"
    }
  }
}
```

### Architecture diagrams (deterministic)

Parse Python imports from all `.py` files in `src/`, generate Mermaid graph:

```python
def generate_mermaid(src_dir: Path) -> str:
    edges = set()
    for py_file in src_dir.rglob("*.py"):
        module = _path_to_module(py_file)
        for imp in _parse_imports(py_file):
            if imp.startswith(project_prefix):
                edges.add((module, imp))
    
    lines = ["graph TD"]
    for src, dst in sorted(edges):
        lines.append(f"    {src} --> {dst}")
    return "\n".join(lines)
```

Output written to `docs/architecture.mmd`. No AI involved.

---

## 5. Bootstrap (`sw bootstrap`)

### CLI

```
sw bootstrap                    # interactive: detect project type, prompt for options
sw bootstrap --type python      # non-interactive: Python defaults
sw bootstrap --type typescript  # non-interactive: TypeScript defaults
```

### Generated files

| File | Content |
|---|---|
| `.devcontainer/devcontainer.json` | Dev container config with language runtime + claude CLI |
| `.github/workflows/ci.yml` | CI pipeline: lint, test, coverage |
| `.pre-commit-config.yaml` | Pre-commit hooks: ruff/eslint, trailing whitespace |
| `CLAUDE.md` | Template with project structure, conventions, module map |
| `docs/` | Docs scaffold (index.md, architecture.mmd placeholder) |
| `.claude/workflow.json` | Default workflow config with quality gates enabled |

All generated from templates in `src/superpower_workflow/templates/`. Templates use Jinja2 with project-type variables.

---

## 6. Upgrade (`sw upgrade`)

### Flow

1. Detect package manager (pip/npm/cargo)
2. List outdated deps: `pip list --outdated --format=json` / `npm outdated --json`
3. For each outdated dep, check breaking changes (major version bump = breaking)
4. Generate upgrade branch per dep: `upgrade/{dep}-{old}-to-{new}`
5. For breaking changes, invoke claude -p: "Upgrade {dep} from {old} to {new}. Apply migration."
6. Run tests. If passing, create PR via SP5 integration.

Non-breaking upgrades are automatic (bump version, run tests). Breaking upgrades use AI assistance.

---

## 7. Plugin System

### Discovery (setuptools entry points)

Plugins register via `pyproject.toml`:

```toml
[project.entry-points."superpower_workflow.plugins"]
my_plugin = "sw_plugin_example:MyPlugin"
```

### Plugin interface

```python
class Plugin:
    """Base class for superpower-workflow plugins."""
    
    name: str = "unnamed"
    version: str = "0.0.0"
    
    def pre_phase(self, phase: str, milestone: dict) -> None: ...
    def post_phase(self, phase: str, milestone: dict, result: dict) -> None: ...
    def pre_commit(self, milestone: dict, files: list[str]) -> None: ...
    def post_milestone(self, milestone: dict, cost: float) -> None: ...
```

All methods are optional (default no-op). Plugins can raise `PluginVetoError` from `pre_phase` or `pre_commit` to block execution.

### Loader

```python
def load_plugins() -> list[Plugin]:
    plugins = []
    for ep in importlib.metadata.entry_points(group="superpower_workflow.plugins"):
        cls = ep.load()
        plugins.append(cls())
    return plugins
```

### Orchestrator integration

The orchestrator calls plugin hooks at each lifecycle point:

```python
for plugin in self.plugins:
    plugin.pre_phase(phase, milestone)
# ... run phase ...
for plugin in self.plugins:
    plugin.post_phase(phase, milestone, result)
```

---

## 8. Plugin CLI

```
sw plugin list              # show installed plugins
sw plugin add <name>        # pip install sw-plugin-{name}
sw plugin remove <name>     # pip uninstall sw-plugin-{name}
```

Convention: community plugins are named `sw-plugin-{name}` on PyPI. The `add` command is a thin wrapper around pip install.

---

## 9. Files Changed

| File | Change |
|---|---|
| `src/superpower_workflow/docs/__init__.py` | Package init |
| `src/superpower_workflow/docs/readme_gen.py` | README generation (AI-assisted) |
| `src/superpower_workflow/docs/changelog.py` | CHANGELOG generation (deterministic) |
| `src/superpower_workflow/docs/api_docs.py` | Sphinx/MkDocs wrapper |
| `src/superpower_workflow/docs/diagrams.py` | Mermaid dependency graph generator |
| `src/superpower_workflow/bootstrap.py` | `sw bootstrap` command implementation |
| `src/superpower_workflow/upgrade.py` | `sw upgrade` command implementation |
| `src/superpower_workflow/plugins/__init__.py` | Package init |
| `src/superpower_workflow/plugins/loader.py` | Entry-point discovery and loading |
| `src/superpower_workflow/plugins/interface.py` | Plugin base class and PluginVetoError |
| `src/superpower_workflow/cli.py` | Add bootstrap, upgrade, plugin subcommands |
| `src/superpower_workflow/orchestrator.py` | Plugin lifecycle hooks at phase boundaries |
| `src/superpower_workflow/templates/` | Bootstrap templates (devcontainer, CI, hooks, etc.) |
| `tests/test_docs.py` | Tests for changelog, diagrams (deterministic) |
| `tests/test_plugins.py` | Tests for plugin loader, interface, veto |
| `tests/test_bootstrap.py` | Tests for bootstrap template rendering |

---

## 10. Open Questions

- Should README generation be opt-out (default on) or opt-in?
- Should plugins be sandboxed (e.g., no filesystem access outside project)?
- Should `sw upgrade` create one PR per dep or batch minor upgrades?
- Should architecture diagrams include test files or only src/?
