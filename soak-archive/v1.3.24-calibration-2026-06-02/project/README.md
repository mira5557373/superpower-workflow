# todo-cli

A minimal command-line todo manager written in Python.

## Usage

```bash
todo add "Buy groceries"
todo list
todo done 1
todo rm 1
```

## Requirements

- Python 3.11+
- Click for CLI framework

## Installation

```bash
pip install -e .
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

## Quality Gates & Validation

All commits must pass these automated checks:
- **Linting:** `ruff check .` and `ruff format --check .` (no violations)
- **Coverage:** `pytest --cov=todo` minimum ≥90% per spec (M2 baseline: 98.06%)
- **Tests:** All 51+ tests passing via `pytest -q`

Lines 10, 71 in cli.py use `# pragma: no cover` (Click entry point scaffolding, not logic).
