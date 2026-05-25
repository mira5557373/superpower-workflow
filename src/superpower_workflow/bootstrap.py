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
