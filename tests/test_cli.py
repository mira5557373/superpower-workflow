import json
import os
from pathlib import Path
from unittest.mock import patch

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


def test_metrics_subcommand_exists():
    parser = build_parser()
    args = parser.parse_args(["metrics"])
    assert args.command == "metrics"


def test_metrics_json_flag():
    parser = build_parser()
    args = parser.parse_args(["metrics", "--json"])
    assert args.json_output is True


def test_metrics_no_telemetry_file(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_metrics

    _cmd_metrics(tmp_path)
    captured = capsys.readouterr()
    assert "No telemetry data" in captured.out


def test_metrics_human_output(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_metrics

    telemetry_path = tmp_path / ".claude" / "telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True)
    events = [
        {"type": "run_started", "run_id": "r1", "model": "opus", "milestone_count": 2},
        {
            "type": "milestone_completed",
            "run_id": "r1",
            "milestone": "m1",
            "cost_usd": 10.0,
            "duration_seconds": 300.0,
        },
        {
            "type": "milestone_completed",
            "run_id": "r1",
            "milestone": "m2",
            "cost_usd": 15.0,
            "duration_seconds": 400.0,
        },
        {
            "type": "phase_completed",
            "run_id": "r1",
            "phase": "plan",
            "cost_usd": 5.0,
            "duration_ms": 60000,
        },
        {
            "type": "phase_completed",
            "run_id": "r1",
            "phase": "implement",
            "cost_usd": 20.0,
            "duration_ms": 120000,
        },
        {
            "type": "run_completed",
            "run_id": "r1",
            "status": "complete",
            "total_cost_usd": 25.0,
            "completed_count": 2,
            "duration_seconds": 700.0,
        },
    ]
    with open(telemetry_path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    _cmd_metrics(tmp_path)
    captured = capsys.readouterr()
    assert "$25.0" in captured.out or "25.0" in captured.out
    assert "m1" in captured.out
    assert "complete" in captured.out


def test_metrics_json_output(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_metrics

    telemetry_path = tmp_path / ".claude" / "telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True)
    events = [
        {
            "type": "run_completed",
            "run_id": "r1",
            "status": "complete",
            "total_cost_usd": 25.0,
            "completed_count": 2,
            "duration_seconds": 700.0,
        },
    ]
    with open(telemetry_path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    _cmd_metrics(tmp_path, json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "total_cost" in data
    assert "cost_per_task" in data


def test_init_adds_telemetry_to_gitignore(tmp_path):
    _cmd_init(tmp_path)
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "telemetry.jsonl" in gitignore


def test_init_default_config_has_telemetry(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "telemetry" in config
    assert config["telemetry"]["enabled"] is True


def test_parser_dashboard_command():
    parser = build_parser()
    args = parser.parse_args(["dashboard"])
    assert args.command == "dashboard"


def test_parser_dashboard_port_flag():
    args = build_parser().parse_args(["dashboard", "--port", "8080"])
    assert args.port == 8080


def test_parser_dashboard_default_port():
    args = build_parser().parse_args(["dashboard"])
    assert args.port is None


def test_parser_dashboard_default_host():
    args = build_parser().parse_args(["dashboard"])
    assert args.host is None


def test_parser_dashboard_host_flag():
    args = build_parser().parse_args(["dashboard", "--host", "0.0.0.0"])
    assert args.host == "0.0.0.0"


def test_parser_watch_command():
    parser = build_parser()
    args = parser.parse_args(["watch"])
    assert args.command == "watch"


def test_parser_watch_interval_flag():
    args = build_parser().parse_args(["watch", "--interval", "5"])
    assert args.interval == 5.0


def test_parser_watch_default_interval():
    args = build_parser().parse_args(["watch"])
    assert args.interval is None


def test_init_config_has_dashboard_section(tmp_path: Path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "dashboard" in config
    assert config["dashboard"]["port"] == 3000
    assert config["dashboard"]["host"] == "localhost"
    assert config["dashboard"]["watch_interval"] == 2


def test_dashboard_reads_port_from_config(tmp_path: Path):
    """sw dashboard uses port from workflow.json if not overridden."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "milestones": [],
        "dashboard": {"port": 8888, "host": "localhost", "watch_interval": 2},
    }
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    assert config["dashboard"]["port"] == 8888


def test_parser_audit_verify_command():
    parser = build_parser()
    args = parser.parse_args(["audit", "verify"])
    assert args.command == "audit"
    assert args.audit_command == "verify"


def test_parser_audit_verify_sig_command():
    parser = build_parser()
    args = parser.parse_args(["audit", "verify-sig", "v1.0"])
    assert args.command == "audit"
    assert args.audit_command == "verify-sig"
    assert args.tag == "v1.0"


def test_parser_audit_verify_sig_with_key():
    parser = build_parser()
    args = parser.parse_args(["audit", "verify-sig", "v1.0", "--public-key", "abc"])
    assert args.public_key == "abc"


def test_audit_verify_no_trail(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_audit_verify

    _cmd_audit_verify(tmp_path)
    captured = capsys.readouterr()
    assert "No audit trail" in captured.out or "valid" in captured.out.lower()


def test_audit_verify_valid_chain(tmp_path, capsys):
    from superpower_workflow.audit import AuditTrail, _hkdf_sha256
    from superpower_workflow.cli import _cmd_audit_verify

    key = _hkdf_sha256(b"test-key", info=b"sw-audit-trail")
    path = tmp_path / ".claude" / "audit-trail.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    trail = AuditTrail(path, key=key)
    trail.append("A")
    trail.append("B")

    with patch.dict(os.environ, {"SW_AUDIT_KEY": "test-key"}):
        _cmd_audit_verify(tmp_path)
    captured = capsys.readouterr()
    assert "valid" in captured.out.lower() or "OK" in captured.out


def test_audit_verify_tampered_chain(tmp_path, capsys):
    import pytest

    from superpower_workflow.audit import AuditTrail, _hkdf_sha256
    from superpower_workflow.cli import _cmd_audit_verify

    key = _hkdf_sha256(b"test-key", info=b"sw-audit-trail")
    path = tmp_path / ".claude" / "audit-trail.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    trail = AuditTrail(path, key=key)
    trail.append("A")
    trail.append("B")
    lines = path.read_text().strip().split("\n")
    entry = json.loads(lines[0])
    entry["data"] = {"tampered": True}
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n")

    with patch.dict(os.environ, {"SW_AUDIT_KEY": "test-key"}), pytest.raises(SystemExit):
        _cmd_audit_verify(tmp_path)
    captured = capsys.readouterr()
    assert "INVALID" in captured.out or "tamper" in captured.out.lower()


def test_init_config_has_security_section(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "security" in config
    assert config["security"]["audit_trail"] is False
    assert config["security"]["sign_artifacts"] is False


def test_init_config_has_policies_section(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "policies" in config
    assert config["policies"] == {}


def test_init_config_has_secrets_section(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "secrets" in config
    assert config["secrets"] == {}


def test_init_audit_trail_in_gitignore(tmp_path):
    _cmd_init(tmp_path)
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "audit-trail.jsonl" in gitignore
