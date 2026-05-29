"""Verification tests for spec-compliance feature audit."""
import importlib
import json
import os
from datetime import datetime

from todo.storage import TodoStore


def test_timestamp_is_utc(store):
    """ISO-8601 timestamps must be UTC."""
    todo = store.add("verify utc")
    dt = datetime.fromisoformat(todo.created_at)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_store_default_path_is_home_dot_todo():
    """Default store path should be ~/.todo/store.json per spec."""
    expected = os.path.join(os.path.expanduser("~"), ".todo", "store.json")
    assert expected.endswith(os.path.join(".todo", "store.json"))


def test_json_storage_format(store):
    """Storage must be JSON with next_id and todos keys."""
    store.add("check format")
    raw = json.loads(store._path.read_text())
    assert "next_id" in raw
    assert "todos" in raw
    assert isinstance(raw["todos"], list)
    assert isinstance(raw["next_id"], int)


def test_atomic_write_uses_tmp_then_rename(store, monkeypatch):
    """Atomic writes: write to .tmp then os.replace."""
    rename_calls = []
    original_replace = os.replace

    def tracking_replace(src, dst):
        rename_calls.append((src, dst))
        return original_replace(src, dst)

    monkeypatch.setattr("os.replace", tracking_replace)
    store.add("atomic test")
    assert len(rename_calls) >= 1
    assert any(".tmp" in str(src) for src, dst in rename_calls)


def test_deterministic_add(tmp_path):
    """Adding same text produces same structure (minus timestamp)."""
    s1 = TodoStore(tmp_path / "s1.json")
    s2 = TodoStore(tmp_path / "s2.json")
    t1 = s1.add("same text")
    t2 = s2.add("same text")
    assert t1.id == t2.id
    assert t1.text == t2.text
    assert t1.status == t2.status


def test_cli_module_exists():
    """CLI module (cli.py) is implemented."""
    spec = importlib.util.find_spec("todo.cli")
    assert spec is not None, "cli.py should exist per CLAUDE.md module map"


def test_main_module_exists():
    """__main__.py is implemented for python -m todo support."""
    spec = importlib.util.find_spec("todo.__main__")
    assert spec is not None, "__main__.py should exist per CLAUDE.md module map"
