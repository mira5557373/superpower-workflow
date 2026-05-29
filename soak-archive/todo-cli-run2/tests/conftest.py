from pathlib import Path

import pytest

from todo.storage import TodoStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "store.json"


@pytest.fixture
def store(tmp_path: Path) -> TodoStore:
    return TodoStore(tmp_path / "store.json")
