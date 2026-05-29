import subprocess
import sys

from todo.cli import main


def test_add_prints_formatted_todo(store_path, capsys):
    ret = main(["--store", str(store_path), "add", "buy milk"])
    assert ret == 0
    out = capsys.readouterr().out.strip()
    parts = out.split(" ", 3)
    assert parts[0] == "1"
    assert parts[1] == "open"
    assert parts[3] == "buy milk"


def test_add_persists(store_path, capsys):
    main(["--store", str(store_path), "add", "first"])
    capsys.readouterr()
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert "first" in out


def test_list_shows_open_only(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    main(["--store", str(store_path), "add", "b"])
    main(["--store", str(store_path), "done", "2"])
    capsys.readouterr()
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert "a" in out
    assert "b" not in out


def test_list_all_includes_done(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    main(["--store", str(store_path), "done", "1"])
    capsys.readouterr()
    main(["--store", str(store_path), "list", "--all"])
    out = capsys.readouterr().out
    assert "a" in out
    assert "done" in out


def test_list_empty(store_path, capsys):
    ret = main(["--store", str(store_path), "list"])
    assert ret == 0
    out = capsys.readouterr().out
    assert out == ""


def test_done_unknown_id(store_path, capsys):
    ret = main(["--store", str(store_path), "done", "999"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "999" in err


def test_remove_deletes(store_path, capsys):
    main(["--store", str(store_path), "add", "a"])
    capsys.readouterr()
    ret = main(["--store", str(store_path), "remove", "1"])
    assert ret == 0
    main(["--store", str(store_path), "list"])
    out = capsys.readouterr().out
    assert out == ""


def test_remove_unknown_id(store_path, capsys):
    ret = main(["--store", str(store_path), "remove", "999"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "999" in err


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
