from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Status(StrEnum):
    """Status enum for todos."""

    OPEN = "open"
    DONE = "done"


@dataclass
class Todo:
    """A single todo item."""

    id: int
    status: Status
    created: str
    text: str

    def __str__(self) -> str:
        """Return string representation: <id> <status> <created> <text>."""
        return f"{self.id} {self.status} {self.created} {self.text}"


@dataclass
class TodoList:
    """A list of todos."""

    todos: dict[int, Todo] = field(default_factory=dict)
    _next_id: int = field(default=1, init=False, repr=False)

    def add_todo(self, text: str) -> Todo:
        """Add a new todo and return it."""
        todo_id = self._next_id
        todo = Todo(
            id=todo_id,
            status=Status.OPEN,
            created=datetime.now(UTC).isoformat(),
            text=text,
        )
        self.todos[todo_id] = todo
        self._next_id += 1
        return todo

    def get_todo(self, todo_id: int) -> Todo | None:
        """Get a todo by id, or None if not found."""
        return self.todos.get(todo_id)

    def get_todos(self, include_done: bool = False) -> list[Todo]:
        """Get todos, optionally filtering by status."""
        todos = list(self.todos.values())
        if include_done:
            return todos
        return [t for t in todos if t.status == Status.OPEN]

    @property
    def next_id(self) -> int:
        """Get the next sequential id."""
        return self._next_id
