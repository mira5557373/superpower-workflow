import subprocess
import sys
from datetime import datetime

from todo.cli import _build_parser, _format_todo, main
from todo.storage import Todo, TodoStore


def test_format_todo():
    t = Todo(id=1, text="buy milk", status="open",
             created_at="2026-01-01T00:00:00+00:00")
    assert _format_todo(t) == "1 open 2026-01-01T00:00:00+00:00 buy milk"


def test_parser_add_subcommand():
    args = _build_parser().parse_args(["add", "buy milk"])
    assert args.command == "add"
    assert args.text == "buy milk"


def test_parser_list_subcommand():
    args = _build_parser().parse_args(["list"])
    assert args.command == "list"
    assert not args.show_all


def test_parser_list_all_flag():
    args = _build_parser().parse_args(["list", "--all"])
    assert args.show_all is True


def test_parser_done_subcommand():
    args = _build_parser().parse_args(["done", "42"])
    assert args.command == "done"
    assert args.id == 42


def test_parser_remove_subcommand():
    args = _build_parser().parse_args(["remove", "7"])
    assert args.command == "remove"
    assert args.id == 7


def test_parser_rm_alias():
    args = _build_parser().parse_args(["rm", "3"])
    assert args.command == "rm"
    assert args.id == 3


def test_parser_store_option(tmp_path):
    p = str(tmp_path / "my.json")
    args = _build_parser().parse_args(["--store", p, "list"])
    assert str(args.store) == p


def test_add_prints_formatted_todo(store_path, capsys):
    ret = main(["--store", str(store_path), "add", "buy milk"])
    assert ret == 0
    out = capsys.readouterr().out.strip()
    parts = out.split(" ", 3)
    assert parts[0] == "1"
    assert parts[1] == "open"
    datetime.fromisoformat(parts[2])
    assert parts[3] == "buy milk"


def test_add_persists(store_path, capsys):
    main(["--store", str(store_path), "add", "first"])
    capsys.readouterr()
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert "first" in out


def test_add_monotonic_ids(store_path, capsys):
    for text in ("a", "b", "c"):
        main(["--store", str(store_path), "add", text])
    lines = capsys.readouterr().out.strip().split("\n")
    ids = [line.split(" ", 1)[0] for line in lines]
    assert ids == ["1", "2", "3"]


def test_list_shows_open_only(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    main(["--store", str(store_path), "add", "b"])
    capsys.readouterr()
    TodoStore(store_path).done(2)
    ret = main(["--store", str(store_path), "list"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "a" in out
    assert "b" not in out


def test_list_all_includes_done(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    TodoStore(store_path).done(1)
    ret = main(["--store", str(store_path), "list", "--all"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "a" in out
    assert "done" in out


def test_list_empty(store_path, capsys):
    ret = main(["--store", str(store_path), "list"])
    assert ret == 0
    out = capsys.readouterr().out
    assert out == ""


def test_done_marks_todo(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    ret = main(["--store", str(store_path), "done", "1"])
    assert ret == 0
    assert capsys.readouterr().out == ""
    main(["--store", str(store_path), "list", "--all"])
    out = capsys.readouterr().out
    assert "done" in out
    assert "a" in out


def test_done_preserves_fields(store_path, capsys):
    main(["--store", str(store_path), "add", "buy milk"])
    add_out = capsys.readouterr().out.strip()
    _, _, created_at, text = add_out.split(" ", 3)
    main(["--store", str(store_path), "done", "1"])
    main(["--store", str(store_path), "list", "--all"])
    list_out = capsys.readouterr().out.strip()
    parts = list_out.split(" ", 3)
    assert parts[1] == "done"
    assert parts[2] == created_at
    assert parts[3] == text


def test_done_hides_from_default_list(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    main(["--store", str(store_path), "add", "b"])
    capsys.readouterr()
    ret = main(["--store", str(store_path), "done", "1"])
    assert ret == 0
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert "a" not in out
    assert "b" in out


def test_done_unknown_id(store_path, capsys):
    ret = main(["--store", str(store_path), "done", "999"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "999" in captured.err
    assert captured.out == ""


def test_remove_deletes(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    ret = main(["--store", str(store_path), "remove", "1"])
    assert ret == 0
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert out == ""


def test_full_lifecycle(store_path, capsys):
    ret = main(["--store", str(store_path), "add", "task"])
    assert ret == 0
    capsys.readouterr()
    ret = main(["--store", str(store_path), "done", "1"])
    assert ret == 0
    main(["--store", str(store_path), "list"])
    assert capsys.readouterr().out == ""
    main(["--store", str(store_path), "list", "--all"])
    out = capsys.readouterr().out
    assert "done" in out
    assert "task" in out
    ret = main(["--store", str(store_path), "rm", "1"])
    assert ret == 0
    main(["--store", str(store_path), "list", "--all"])
    assert capsys.readouterr().out == ""


def test_remove_unknown_id(store_path, capsys):
    ret = main(["--store", str(store_path), "remove", "999"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "999" in captured.err
    assert captured.out == ""


def test_rm_alias_deletes(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    ret = main(["--store", str(store_path), "rm", "1"])
    assert ret == 0
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert out == ""


def test_rm_alias_unknown_id(store_path, capsys):
    ret = main(["--store", str(store_path), "rm", "999"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "999" in captured.err
    assert captured.out == ""


def test_done_already_done_idempotent(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    ret1 = main(["--store", str(store_path), "done", "1"])
    ret2 = main(["--store", str(store_path), "done", "1"])
    assert ret1 == 0
    assert ret2 == 0


def test_remove_done_todo(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    ret = main(["--store", str(store_path), "done", "1"])
    assert ret == 0
    ret = main(["--store", str(store_path), "rm", "1"])
    assert ret == 0
    main(["--store", str(store_path), "list", "--all"])
    out = capsys.readouterr().out
    assert out == ""


def test_remove_preserves_other_todos(store_path, capsys):
    main(["--store", str(store_path), "add", "first"])
    main(["--store", str(store_path), "add", "second"])
    main(["--store", str(store_path), "add", "third"])
    capsys.readouterr()
    main(["--store", str(store_path), "rm", "2"])
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert "first" in out
    assert "second" not in out
    assert "third" in out
    lines = out.strip().split("\n")
    assert len(lines) == 2


def test_done_corrupted_store(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{{")
    ret = main(["--store", str(bad), "done", "1"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_remove_corrupted_store(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{{")
    ret = main(["--store", str(bad), "remove", "1"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_done_on_removed_todo(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    main(["--store", str(store_path), "rm", "1"])
    ret = main(["--store", str(store_path), "done", "1"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert captured.out == ""


def test_rm_already_removed(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    ret1 = main(["--store", str(store_path), "rm", "1"])
    assert ret1 == 0
    ret2 = main(["--store", str(store_path), "rm", "1"])
    assert ret2 == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err


def test_no_command_returns_usage_error(store_path):
    ret = main(["--store", str(store_path)])
    assert ret == 2


def test_corrupted_store_shows_clean_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{{")
    ret = main(["--store", str(bad), "list"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_deterministic_output(store_path, capsys):
    main(["--store", str(store_path), "add", "x"])
    main(["--store", str(store_path), "add", "y"])
    capsys.readouterr()
    main(["--store", str(store_path), "list"])
    first = capsys.readouterr().out
    main(["--store", str(store_path), "list"])
    second = capsys.readouterr().out
    assert first == second
    assert len(first.strip().split("\n")) == 2


def test_corrupted_store_on_add(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{{")
    ret = main(["--store", str(bad), "add", "x"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_store_init_error(tmp_path, capsys):
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file")
    bad_path = blocker / "store.json"
    ret = main(["--store", str(bad_path), "list"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_output_format_one_line_per_todo(store_path, capsys):
    main(["--store", str(store_path), "add", "first"])
    main(["--store", str(store_path), "add", "second"])
    capsys.readouterr()
    main(["--store", str(store_path), "list"])
    lines = capsys.readouterr().out.strip().split("\n")
    assert len(lines) == 2


def test_python_m_todo():
    result = subprocess.run(
        [sys.executable, "-m", "todo", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "todo" in result.stdout.lower()
