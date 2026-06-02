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
