from __future__ import annotations

import contextlib
import dataclasses
import json
import os
from pathlib import Path

from todo.models import TodoList


class JsonStore:
    """JSON storage for TodoList with atomic writes."""

    def __init__(self) -> None:
        """Initialize store with path derived from HOME."""
        home = Path(os.environ.get("HOME", Path.home()))
        self.path = home / ".todo" / "store.json"

    def load(self) -> TodoList:
        """Load TodoList from JSON file or return empty list if not found."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return TodoList()
        try:
            with open(self.path) as f:
                data = json.load(f)
            return self._deserialize(data)
        except json.JSONDecodeError:
            raise

    def save(self, tl: TodoList) -> None:
        """Save TodoList to JSON file using atomic .tmp → rename pattern."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.parent / f"{self.path.name}.tmp"
        data = dataclasses.asdict(tl)
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
        except Exception:
            with contextlib.suppress(OSError):
                os.close(fd)
            tmp_path.unlink(missing_ok=True)
            raise
        tmp_path.replace(self.path)

    def _deserialize(self, data: dict) -> TodoList:
        """Deserialize JSON data to TodoList."""
        from todo.models import Status, Todo

        tl = TodoList()
        todos_data = data.get("todos", {})
        for todo_id_str, todo_data in todos_data.items():
            todo_id = int(todo_id_str)
            todo = Todo(
                id=todo_id,
                status=Status(todo_data["status"]),
                created=todo_data["created"],
                text=todo_data["text"],
            )
            tl.todos[todo_id] = todo
            tl._next_id = max(tl._next_id, todo_id + 1)
        return tl
