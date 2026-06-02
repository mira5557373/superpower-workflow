from __future__ import annotations

import click

from todo.models import Status
from todo.store import JsonStore


@click.group(name="todo")
def cli() -> None:  # pragma: no cover
    """Minimal command-line todo manager."""
    pass


@cli.command()
@click.argument("text")
def add(text: str) -> None:
    """Add a new todo."""
    try:
        store = JsonStore()
        tl = store.load()
        todo = tl.add_todo(text)
        store.save(tl)
        click.echo(f"Added: {todo}")
    except (OSError, ValueError) as e:
        click.echo(f"Error: Failed to add todo: {e}", err=True)
        raise SystemExit(1) from None


@cli.command()
@click.option("--all", "include_done", is_flag=True, help="Include done todos")
def list(include_done: bool) -> None:
    """List todos."""
    try:
        store = JsonStore()
        tl = store.load()
        todos = tl.get_todos(include_done=include_done)
        for todo in todos:
            click.echo(str(todo))
    except (OSError, ValueError) as e:
        click.echo(f"Error: Failed to list todos: {e}", err=True)
        raise SystemExit(1) from None


@cli.command()
@click.argument("todo_id", type=int)
def done(todo_id: int) -> None:
    """Mark a todo as done or toggle status."""
    try:
        store = JsonStore()
        tl = store.load()
        todo = tl.get_todo(todo_id)
        if todo is None:
            click.echo(f"Error: todo {todo_id} not found", err=True)
            raise SystemExit(1)
        # Toggle status
        if todo.status == Status.OPEN:
            todo.status = Status.DONE
        else:
            todo.status = Status.OPEN
        store.save(tl)
        click.echo(f"Updated: {todo}")
    except (OSError, ValueError) as e:
        click.echo(f"Error: Failed to update todo: {e}", err=True)
        raise SystemExit(1) from None


@cli.command()
@click.argument("todo_id", type=int)
def rm(todo_id: int) -> None:
    """Remove a todo."""
    try:
        store = JsonStore()
        tl = store.load()
        todo = tl.get_todo(todo_id)
        if todo is None:
            click.echo(f"Error: todo {todo_id} not found", err=True)
            raise SystemExit(1)
        tl.todos.pop(todo_id)
        store.save(tl)
        click.echo(f"Removed: {todo}")
    except (OSError, ValueError) as e:
        click.echo(f"Error: Failed to remove todo: {e}", err=True)
        raise SystemExit(1) from None


def main() -> None:  # pragma: no cover
    """Main entry point."""
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
