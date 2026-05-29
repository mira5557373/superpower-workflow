import json
import os
from datetime import datetime

import pytest

from todo.storage import Todo, TodoStore


def test_todo_has_required_fields():
    t = Todo(id=1, text="buy milk")
    assert t.id == 1
    assert t.text == "buy milk"
    assert t.status == "open"
    assert isinstance(t.created_at, str) and len(t.created_at) > 0


def test_todo_created_at_is_iso8601():
    t = Todo(id=1, text="x")
    datetime.fromisoformat(t.created_at)


def test_todo_to_dict():
    t = Todo(id=1, text="x", status="open", created_at="2026-01-01T00:00:00+00:00")
    d = t.to_dict()
    assert d == {"id": 1, "text": "x", "status": "open", "created_at": "2026-01-01T00:00:00+00:00"}


def test_todo_round_trip():
    t = Todo(id=1, text="buy milk")
    assert Todo.from_dict(t.to_dict()) == t


def test_from_dict_ignores_extra_keys():
    d = {
        "id": 1,
        "text": "x",
        "status": "open",
        "created_at": "2026-01-01T00:00:00+00:00",
        "extra": "ignored",
    }
    t = Todo.from_dict(d)
    assert t.id == 1
    assert not hasattr(t, "extra")


def test_store_creates_directory(tmp_path):
    store_path = tmp_path / "sub" / "store.json"
    TodoStore(store_path)
    assert store_path.parent.is_dir()


def test_store_creates_file_with_empty_schema(tmp_path):
    store_path = tmp_path / "store.json"
    TodoStore(store_path)
    data = json.loads(store_path.read_text())
    assert data == {"next_id": 1, "todos": []}


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_store_file_permissions(tmp_path):
    store_path = tmp_path / "store.json"
    TodoStore(store_path)
    mode = store_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_load_empty_store(store):
    assert store.load() == []


def test_load_populated_store(tmp_path):
    store_path = tmp_path / "store.json"
    data = {
        "next_id": 2,
        "todos": [
            {
                "id": 1,
                "text": "buy milk",
                "status": "open",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    }
    store_path.write_text(json.dumps(data))
    store = TodoStore(store_path)
    todos = store.load()
    assert len(todos) == 1
    assert todos[0].text == "buy milk"


def test_save_and_load_round_trip(store):
    todos = [Todo(id=1, text="x"), Todo(id=2, text="y")]
    store.save(todos)
    loaded = store.load()
    assert len(loaded) == 2
    assert loaded[0].text == "x"


def test_save_atomic_no_tmp_remains(tmp_path):
    store_path = tmp_path / "store.json"
    store = TodoStore(store_path)
    store.save([Todo(id=1, text="x")])
    assert not (store_path.parent / "store.json.tmp").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_save_preserves_permissions(tmp_path):
    store_path = tmp_path / "store.json"
    store = TodoStore(store_path)
    store.save([Todo(id=1, text="x")])
    mode = store_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_add_returns_todo(store):
    todo = store.add("buy milk")
    assert todo.id == 1
    assert todo.text == "buy milk"
    assert todo.status == "open"


def test_add_persists(store):
    store.add("buy milk")
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].text == "buy milk"


def test_add_generates_iso8601_timestamp(store):
    todo = store.add("x")
    datetime.fromisoformat(todo.created_at)


def test_done_flips_status(store):
    t = store.add("a")
    store.done(t.id)
    loaded = store.load()
    assert loaded[0].status == "done"


def test_done_unknown_id_raises(store):
    with pytest.raises(KeyError):
        store.done(999)


def test_done_already_done_is_idempotent(store):
    t = store.add("a")
    store.done(t.id)
    store.done(t.id)
    loaded = store.load()
    assert loaded[0].status == "done"


def test_remove_deletes_todo(store):
    t = store.add("a")
    store.remove(t.id)
    assert store.load() == []


def test_remove_unknown_id_raises(store):
    with pytest.raises(KeyError):
        store.remove(999)


def test_remove_middle(store):
    store.add("a")
    t2 = store.add("b")
    store.add("c")
    store.remove(t2.id)
    loaded = store.load()
    assert len(loaded) == 2
    assert all(t.id != t2.id for t in loaded)


def test_ids_increment(store):
    t1 = store.add("a")
    t2 = store.add("b")
    t3 = store.add("c")
    assert (t1.id, t2.id, t3.id) == (1, 2, 3)


def test_ids_no_reuse_after_partial_remove(store):
    store.add("a")
    store.add("b")
    store.remove(1)
    t3 = store.add("c")
    assert t3.id == 3


def test_ids_no_reuse_after_full_remove(store):
    t1 = store.add("a")
    store.remove(t1.id)
    t2 = store.add("b")
    assert t2.id == 2


def test_list_default_open_only(store):
    store.add("a")
    store.add("b")
    t = store.add("c")
    store.done(t.id)
    result = store.list_todos()
    assert len(result) == 2
    assert all(t.status == "open" for t in result)


def test_list_all(store):
    store.add("a")
    t = store.add("b")
    store.done(t.id)
    result = store.list_todos(include_done=True)
    assert len(result) == 2


def test_list_empty_store(store):
    assert store.list_todos() == []


def test_empty_text(store):
    t = store.add("")
    assert t.text == ""


def test_long_text(store):
    long = "x" * 10000
    store.add(long)
    loaded = store.load()
    assert loaded[0].text == long


def test_extra_json_fields_ignored(tmp_path):
    store_path = tmp_path / "store.json"
    data = {
        "next_id": 2,
        "todos": [
            {
                "id": 1,
                "text": "a",
                "status": "open",
                "created_at": "2026-01-01T00:00:00+00:00",
                "extra": "field",
            }
        ],
    }
    store_path.write_text(json.dumps(data))
    store = TodoStore(store_path)
    todos = store.load()
    assert len(todos) == 1


def test_corrupted_json_raises(tmp_path):
    store_path = tmp_path / "store.json"
    store_path.write_text("not valid json{{{")
    store = TodoStore(store_path)
    with pytest.raises((json.JSONDecodeError, ValueError)):
        store.load()


def test_atomic_write_preserves_data_on_failure(tmp_path, monkeypatch):
    store_path = tmp_path / "store.json"
    store = TodoStore(store_path)
    store.add("original")

    original_os_open = os.open

    def bad_open(path, flags, mode=0o777, *a, **kw):
        if ".tmp" in str(path):
            raise OSError("disk full")
        return original_os_open(path, flags, mode, *a, **kw)

    monkeypatch.setattr("os.open", bad_open)

    with pytest.raises(OSError):
        store.save([Todo(id=99, text="corrupt")])

    monkeypatch.undo()
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].text == "original"
