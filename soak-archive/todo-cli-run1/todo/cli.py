from __future__ import annotations

import argparse
import sys
from pathlib import Path

from todo.storage import TodoStore

DEFAULT_STORE_PATH = Path.home() / ".todo" / "store.json"


def _format_todo(todo) -> str:
    return f"{todo.id} {todo.status} {todo.created_at} {todo.text}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo", description="A tiny todo manager")
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="path to store.json",
    )
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="add a new todo")
    add_p.add_argument("text", help="todo text")

    done_p = sub.add_parser("done", help="mark a todo as done")
    done_p.add_argument("id", type=int, help="todo ID")

    remove_p = sub.add_parser("remove", help="remove a todo")
    remove_p.add_argument("id", type=int, help="todo ID")

    list_p = sub.add_parser("list", help="list todos")
    list_p.add_argument("--all", action="store_true", dest="show_all", help="include done")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    try:
        store = TodoStore(args.store)
    except (OSError, ValueError) as exc:
        print(f"error: cannot open store: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "add":
            todo = store.add(args.text)
            print(_format_todo(todo))
        elif args.command == "done":
            try:
                store.done(args.id)
            except KeyError:
                print(f"error: no todo with id {args.id}", file=sys.stderr)
                return 1
        elif args.command == "remove":
            try:
                store.remove(args.id)
            except KeyError:
                print(f"error: no todo with id {args.id}", file=sys.stderr)
                return 1
        elif args.command == "list":
            for t in store.list_todos(include_done=args.show_all):
                print(_format_todo(t))
    except (OSError, ValueError) as exc:
        print(f"error: store operation failed: {exc}", file=sys.stderr)
        return 1

    return 0
