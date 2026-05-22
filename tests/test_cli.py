import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init, build_parser


def test_parser_run_command():
    parser = build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.dry_run is False


def test_parser_run_milestone_flag():
    args = build_parser().parse_args(["run", "--milestone", "p1-m2"])
    assert args.milestone == "p1-m2"


def test_parser_run_dry_run():
    args = build_parser().parse_args(["run", "--dry-run"])
    assert args.dry_run is True


def test_parser_run_phase_flag():
    args = build_parser().parse_args(["run", "--phase", "p1"])
    assert args.phase == "p1"


def test_parser_estimate_command():
    args = build_parser().parse_args(["estimate"])
    assert args.command == "estimate"


def test_parser_doctor_command():
    args = build_parser().parse_args(["doctor"])
    assert args.command == "doctor"


def test_parser_status_command():
    args = build_parser().parse_args(["status"])
    assert args.command == "status"


def test_parser_init_command():
    args = build_parser().parse_args(["init"])
    assert args.command == "init"


def test_parser_decompose_command():
    args = build_parser().parse_args(["decompose"])
    assert args.command == "decompose"


def test_parser_resume_command():
    args = build_parser().parse_args(["resume"])
    assert args.command == "resume"


def test_init_creates_workflow_json(tmp_path: Path):
    _cmd_init(tmp_path)
    config_path = tmp_path / ".claude" / "workflow.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["schema_version"] == 1


def test_init_auto_discovers_spec(tmp_path: Path):
    specs_dir = tmp_path / "docs" / "superpowers" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "2026-05-22-my-spec.md").write_text("# Spec")
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "my-spec" in config["spec"]


def test_init_adds_gitignore_entries(tmp_path: Path):
    _cmd_init(tmp_path)
    gitignore = (tmp_path / ".gitignore").read_text()
    assert ".claude/workflow-state.json" in gitignore
    assert ".claude/.workflow.lock" in gitignore


def test_init_skips_if_exists(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "workflow.json").write_text('{"existing": true}')
    _cmd_init(tmp_path)
    config = json.loads((claude_dir / "workflow.json").read_text())
    assert config.get("existing") is True
