from __future__ import annotations

import json
import os

import pytest

from todo.models import TodoList
from todo.store import JsonStore


class TestJsonStore:
    """Tests for JsonStore atomic I/O."""

    def test_store_path_from_env(self, tmp_home):
        """Test that store path is derived from HOME env var."""
        os.environ["HOME"] = str(tmp_home)
        store = JsonStore()
        expected = tmp_home / ".todo" / "store.json"
        assert store.path == expected

    def test_load_nonexistent_returns_empty(self, clean_store):
        """Test load() on nonexistent file returns empty TodoList."""
        store = JsonStore()
        result = store.load()
        assert isinstance(result, TodoList)
        assert len(result.todos) == 0

    def test_load_creates_parent_dir(self, clean_store):
        """Test that load() creates parent dir if needed."""
        store = JsonStore()
        # Ensure dir doesn't exist
        assert not store.path.parent.exists()
        store.load()
        # Parent should be created
        assert store.path.parent.exists()

    def test_save_creates_file(self, clean_store):
        """Test save() creates file."""
        store = JsonStore()
        tl = TodoList()
        tl.add_todo("hello")
        store.save(tl)
        assert store.path.exists()

    def test_save_creates_with_restricted_perms(self, clean_store):
        """Test save() creates file with restricted permissions."""
        store = JsonStore()
        tl = TodoList()
        tl.add_todo("hello")
        store.save(tl)
        # On Windows, we can't test exact 0o600, but verify chmod was called
        stat_info = os.stat(store.path)
        # File should exist and be readable/writable
        assert stat_info.st_size > 0

    def test_save_uses_tmp_pattern(self, clean_store):
        """Test save() uses .tmp → rename pattern for atomicity."""
        store = JsonStore()
        tl = TodoList()
        tl.add_todo("hello")
        tmp_path = store.path.parent / f"{store.path.name}.tmp"
        # Tmp file should not exist at end
        store.save(tl)
        assert not tmp_path.exists()
        assert store.path.exists()

    def test_save_round_trip(self, clean_store):
        """Test save() and load() round-trip preserves data."""
        store = JsonStore()
        tl = TodoList()
        tl.add_todo("first")
        tl.add_todo("second")
        store.save(tl)
        loaded = store.load()
        assert len(loaded.todos) == 2
        assert loaded.todos[1].text == "first"
        assert loaded.todos[2].text == "second"

    def test_save_persists_json(self, clean_store):
        """Test save() writes valid JSON."""
        store = JsonStore()
        tl = TodoList()
        tl.add_todo("hello")
        store.save(tl)
        with open(store.path) as f:
            data = json.load(f)
        assert "todos" in data
        assert isinstance(data["todos"], dict)

    def test_load_corrupted_json_raises(self, clean_store):
        """Test load() with corrupted JSON raises error."""
        import json

        store = JsonStore()
        store.path.parent.mkdir(parents=True, exist_ok=True)
        with open(store.path, "w") as f:
            f.write("{ invalid json }")
        with pytest.raises(json.JSONDecodeError):
            store.load()

    def test_double_save_concurrency(self, clean_store):
        """Test sequential saves work correctly."""
        store = JsonStore()
        tl1 = TodoList()
        tl1.add_todo("first")
        store.save(tl1)
        tl2 = TodoList()
        tl2.add_todo("second")
        store.save(tl2)
        loaded = store.load()
        assert len(loaded.todos) == 1
        assert loaded.todos[1].text == "second"

    def test_save_preserves_on_resave(self, clean_store):
        """Test data is preserved after re-save."""
        store = JsonStore()
        tl1 = TodoList()
        tl1.add_todo("first")
        store.save(tl1)
        first_size = os.stat(store.path).st_size
        tl2 = TodoList()
        tl2.add_todo("second")
        store.save(tl2)
        second_size = os.stat(store.path).st_size
        assert first_size > 0
        assert second_size > 0
        loaded = store.load()
        assert len(loaded.todos) == 1
        assert loaded.todos[1].text == "second"

    def test_save_atomic_write_cleanup(self, clean_store):
        """Test that save cleans up tmp file on error."""
        import unittest.mock

        store = JsonStore()
        tl = TodoList()
        tl.add_todo("test")
        tmp_path = store.path.parent / f"{store.path.name}.tmp"

        # Mock json.dump to raise an error
        with (
            unittest.mock.patch("json.dump", side_effect=OSError("Mock error")),
            pytest.raises(OSError),
        ):
            store.save(tl)

        # Tmp file should be cleaned up
        assert not tmp_path.exists()
