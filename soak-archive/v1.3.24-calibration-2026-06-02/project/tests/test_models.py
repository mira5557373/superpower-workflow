from __future__ import annotations

from todo.models import Status, Todo, TodoList


class TestStatus:
    """Tests for Status enum."""

    def test_status_open_value(self):
        """Test Status.OPEN has correct string value."""
        assert Status.OPEN == "open"

    def test_status_done_value(self):
        """Test Status.DONE has correct string value."""
        assert Status.DONE == "done"

    def test_status_membership(self):
        """Test enum membership."""
        assert "open" in Status.__members__.values()
        assert "done" in Status.__members__.values()

    def test_status_string_representation(self):
        """Test that Status enums can be used as strings."""
        status = Status.OPEN
        assert isinstance(status, str)
        assert status == "open"


class TestTodo:
    """Tests for Todo dataclass."""

    def test_todo_fields(self):
        """Test Todo dataclass has required fields."""
        import dataclasses

        fields = {f.name for f in dataclasses.fields(Todo)}
        assert "id" in fields
        assert "status" in fields
        assert "created" in fields
        assert "text" in fields

    def test_todo_creation(self):
        """Test creating a Todo instance."""
        todo = Todo(id=1, status=Status.OPEN, created="2026-06-02T10:00:00+00:00", text="hello")
        assert todo.id == 1
        assert todo.status == Status.OPEN
        assert todo.created == "2026-06-02T10:00:00+00:00"
        assert todo.text == "hello"

    def test_todo_str_format(self):
        """Test Todo __str__ format: <id> <status> <created> <text>."""
        todo = Todo(id=1, status=Status.OPEN, created="2026-06-02T10:00:00+00:00", text="hello")
        expected = "1 open 2026-06-02T10:00:00+00:00 hello"
        assert str(todo) == expected

    def test_todo_asdict(self):
        """Test dataclasses.asdict() works for JSON serialization."""
        import dataclasses

        todo = Todo(id=1, status=Status.OPEN, created="2026-06-02T10:00:00+00:00", text="hello")
        d = dataclasses.asdict(todo)
        assert d == {
            "id": 1,
            "status": "open",
            "created": "2026-06-02T10:00:00+00:00",
            "text": "hello",
        }


class TestTodoList:
    """Tests for TodoList dataclass."""

    def test_empty_list(self):
        """Test empty TodoList initialization."""
        tl = TodoList()
        assert len(tl.todos) == 0

    def test_add_todo(self):
        """Test add_todo creates a Todo with new id."""
        tl = TodoList()
        todo = tl.add_todo("hello")
        assert todo.id == 1
        assert todo.text == "hello"
        assert todo.status == Status.OPEN

    def test_add_todo_sequential_ids(self):
        """Test add_todo generates sequential ids."""
        tl = TodoList()
        t1 = tl.add_todo("first")
        t2 = tl.add_todo("second")
        t3 = tl.add_todo("third")
        assert t1.id == 1
        assert t2.id == 2
        assert t3.id == 3

    def test_add_todo_no_id_reuse(self):
        """Test that deleted todos don't cause id reuse."""
        tl = TodoList()
        tl.add_todo("first")  # id=1
        tl.todos.pop(1, None)  # delete first
        t2 = tl.add_todo("second")  # id should be 2, not 1
        assert t2.id == 2

    def test_get_todo_exists(self):
        """Test get_todo returns Todo if exists."""
        tl = TodoList()
        tl.add_todo("hello")
        result = tl.get_todo(1)
        assert result is not None
        assert result.id == 1
        assert result.text == "hello"

    def test_get_todo_not_exists(self):
        """Test get_todo returns None if not found."""
        tl = TodoList()
        result = tl.get_todo(999)
        assert result is None

    def test_get_todos_default_open_only(self):
        """Test get_todos default filters to open only."""
        tl = TodoList()
        tl.add_todo("open todo")
        tl.add_todo("done todo")
        tl.todos[2].status = Status.DONE
        result = tl.get_todos(include_done=False)
        assert len(result) == 1
        assert result[0].id == 1

    def test_get_todos_include_done(self):
        """Test get_todos with include_done=True returns all."""
        tl = TodoList()
        tl.add_todo("open todo")
        tl.add_todo("done todo")
        tl.todos[2].status = Status.DONE
        result = tl.get_todos(include_done=True)
        assert len(result) == 2

    def test_next_id_empty(self):
        """Test next_id is 1 when empty."""
        tl = TodoList()
        assert tl.next_id == 1

    def test_next_id_with_todos(self):
        """Test next_id is max+1."""
        tl = TodoList()
        tl.add_todo("first")
        tl.add_todo("second")
        assert tl.next_id == 3

    def test_todolist_asdict(self):
        """Test dataclasses.asdict() for TodoList."""
        import dataclasses

        tl = TodoList()
        tl.add_todo("hello")
        d = dataclasses.asdict(tl)
        assert "todos" in d
        assert isinstance(d["todos"], dict)
