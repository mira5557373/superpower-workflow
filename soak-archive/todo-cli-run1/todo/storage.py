from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Todo:
    id: int
    text: str
    status: str = "open"
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Todo:
        return cls(
            id=d["id"],
            text=d["text"],
            status=d["status"],
            created_at=d["created_at"],
        )


_EMPTY_STORE = {"next_id": 1, "todos": []}


class TodoStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write_initial_store()

    def _write_initial_store(self) -> None:
        content = json.dumps(_EMPTY_STORE, indent=2)
        fd = os.open(
            str(self._path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(fd, content.encode())
        finally:
            os.close(fd)

    def _read_store(self) -> dict:
        return json.loads(self._path.read_text())

    def load(self) -> list[Todo]:
        data = self._read_store()
        return [Todo.from_dict(t) for t in data["todos"]]

    def save(self, todos: list[Todo], next_id: int | None = None) -> None:
        if next_id is None:
            next_id = self._read_store()["next_id"]
        data = {"next_id": next_id, "todos": [t.to_dict() for t in todos]}
        content = json.dumps(data, indent=2)
        tmp_path = self._path.with_suffix(".json.tmp")
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, content.encode())
        finally:
            os.close(fd)
        os.replace(str(tmp_path), str(self._path))

    def add(self, text: str) -> Todo:
        data = self._read_store()
        todo = Todo(id=data["next_id"], text=text)
        data["next_id"] += 1
        todos = [Todo.from_dict(t) for t in data["todos"]]
        todos.append(todo)
        self.save(todos, next_id=data["next_id"])
        return todo

    def done(self, todo_id: int) -> None:
        data = self._read_store()
        todos = [Todo.from_dict(t) for t in data["todos"]]
        for t in todos:
            if t.id == todo_id:
                t.status = "done"
                self.save(todos, next_id=data["next_id"])
                return
        raise KeyError(todo_id)

    def remove(self, todo_id: int) -> None:
        data = self._read_store()
        todos = [Todo.from_dict(t) for t in data["todos"]]
        original_len = len(todos)
        todos = [t for t in todos if t.id != todo_id]
        if len(todos) == original_len:
            raise KeyError(todo_id)
        self.save(todos, next_id=data["next_id"])

    def list_todos(self, include_done: bool = False) -> list[Todo]:
        todos = self.load()
        if include_done:
            return todos
        return [t for t in todos if t.status != "done"]
