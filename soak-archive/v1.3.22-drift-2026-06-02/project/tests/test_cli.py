from __future__ import annotations

from click.testing import CliRunner
from freezegun import freeze_time

from todo.cli import cli
from todo.store import JsonStore


class TestCliAdd:
    """Tests for todo add command."""

    @freeze_time("2026-06-02T10:00:00+00:00")
    def test_add_creates_todo(self, clean_store):
        """Test todo add creates a todo with correct fields."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "hello"])
        assert result.exit_code == 0
        store = JsonStore()
        tl = store.load()
        assert len(tl.todos) == 1
        assert tl.todos[1].text == "hello"
        assert tl.todos[1].status == "open"
        assert tl.todos[1].created == "2026-06-02T10:00:00+00:00"

    @freeze_time("2026-06-02T10:00:00+00:00")
    def test_add_empty_text(self, clean_store):
        """Test todo add with empty text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", ""])
        assert result.exit_code == 0
        store = JsonStore()
        tl = store.load()
        assert len(tl.todos) == 1
        assert tl.todos[1].text == ""

    @freeze_time("2026-06-02T10:00:00+00:00")
    def test_add_sequential_ids(self, clean_store):
        """Test multiple adds have sequential ids."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "first"])
        runner.invoke(cli, ["add", "second"])
        runner.invoke(cli, ["add", "third"])
        store = JsonStore()
        tl = store.load()
        assert len(tl.todos) == 3
        assert tl.todos[1].text == "first"
        assert tl.todos[2].text == "second"
        assert tl.todos[3].text == "third"

    @freeze_time("2026-06-02T10:00:00+00:00")
    def test_add_output(self, clean_store):
        """Test add output message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "hello"])
        assert result.exit_code == 0
        # Output should contain some confirmation


class TestCliList:
    """Tests for todo list command."""

    def test_list_empty(self, clean_store):
        """Test todo list with empty list."""
        runner = CliRunner()
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_list_open_only_default(self, clean_store):
        """Test todo list default filters to open only."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "open todo"])
        runner.invoke(cli, ["add", "done todo"])
        runner.invoke(cli, ["done", "2"])
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert "1 open" in lines[0]

    def test_list_all_flag(self, clean_store):
        """Test todo list --all includes done todos."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "open todo"])
        runner.invoke(cli, ["add", "done todo"])
        runner.invoke(cli, ["done", "2"])
        result = runner.invoke(cli, ["list", "--all"])
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().split("\n") if line]
        assert len(lines) == 2

    def test_list_output_format(self, clean_store):
        """Test list output format: <id> <status> <created> <text>."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "hello"])
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        parts = lines[0].split()
        assert parts[0] == "1"
        assert parts[1] == "open"

    def test_list_multiple_todos(self, clean_store):
        """Test list with multiple todos."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "first"])
        runner.invoke(cli, ["add", "second"])
        runner.invoke(cli, ["add", "third"])
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().split("\n") if line]
        assert len(lines) == 3


class TestCliErrorHandling:
    """Tests for error messages."""

    def test_done_unknown_id_error(self, clean_store):
        """Test done with unknown id outputs error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["done", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output or "error" in result.output.lower()

    def test_rm_unknown_id_error(self, clean_store):
        """Test rm with unknown id outputs error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["rm", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output or "error" in result.output.lower()


class TestCliDone:
    """Tests for todo done command."""

    def test_done_flips_status(self, clean_store):
        """Test todo done flips status from open to done."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "hello"])
        runner.invoke(cli, ["done", "1"])
        store = JsonStore()
        tl = store.load()
        assert tl.todos[1].status == "done"

    def test_done_unknown_id_exits_1(self, clean_store):
        """Test todo done unknown id exits 1."""
        runner = CliRunner()
        result = runner.invoke(cli, ["done", "999"])
        assert result.exit_code == 1

    def test_done_already_done_toggles(self, clean_store):
        """Test done on already-done todo toggles back to open."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "hello"])
        runner.invoke(cli, ["done", "1"])
        runner.invoke(cli, ["done", "1"])
        store = JsonStore()
        tl = store.load()
        assert tl.todos[1].status == "open"


class TestCliRm:
    """Tests for todo rm command."""

    def test_rm_removes_todo(self, clean_store):
        """Test todo rm removes the todo."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "hello"])
        runner.invoke(cli, ["rm", "1"])
        store = JsonStore()
        tl = store.load()
        assert 1 not in tl.todos

    def test_rm_unknown_id_exits_1(self, clean_store):
        """Test todo rm unknown id exits 1."""
        runner = CliRunner()
        result = runner.invoke(cli, ["rm", "999"])
        assert result.exit_code == 1

    def test_rm_persistence(self, clean_store):
        """Test rm persists after command exits."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "hello"])
        runner.invoke(cli, ["rm", "1"])
        result = runner.invoke(cli, ["list"])
        assert result.output.strip() == ""


class TestCliIntegration:
    """Integration tests for full workflows."""

    def test_full_workflow_add_list_done_rm(self, clean_store):
        """Test full workflow: add → list → done → list → rm → list."""
        runner = CliRunner()
        # Add
        r = runner.invoke(cli, ["add", "hello"])
        assert r.exit_code == 0
        # List
        r = runner.invoke(cli, ["list"])
        assert r.exit_code == 0
        assert "open" in r.output
        # Done
        r = runner.invoke(cli, ["done", "1"])
        assert r.exit_code == 0
        # List all
        r = runner.invoke(cli, ["list", "--all"])
        assert r.exit_code == 0
        assert "done" in r.output
        # Rm
        r = runner.invoke(cli, ["rm", "1"])
        assert r.exit_code == 0
        # List
        r = runner.invoke(cli, ["list", "--all"])
        assert r.exit_code == 0
        assert r.output.strip() == ""

    def test_multiple_todos_workflow(self, clean_store):
        """Test workflow with multiple todos."""
        runner = CliRunner()
        runner.invoke(cli, ["add", "first"])
        runner.invoke(cli, ["add", "second"])
        runner.invoke(cli, ["add", "third"])
        runner.invoke(cli, ["done", "2"])
        r = runner.invoke(cli, ["list"])
        lines = [line for line in r.output.strip().split("\n") if line]
        assert len(lines) == 2
        assert "first" in lines[0]
        assert "third" in lines[1]

    def test_help_output(self, clean_store):
        """Test that help output works."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "add" in result.output or "Usage" in result.output
