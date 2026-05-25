from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from superpower_workflow import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sw", description="Superpower Workflow Orchestrator")
    parser.add_argument("--version", action="version", version=f"sw {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create .claude/workflow.json")
    sub.add_parser("doctor", help="Pre-flight health checks")
    sub.add_parser("decompose", help="Spec to milestone breakdown")
    sub.add_parser("estimate", help="Cost and duration estimate")
    sub.add_parser("status", help="Show progress")
    sub.add_parser("resume", help="Resume from failure point")

    metrics_p = sub.add_parser("metrics", help="Show telemetry metrics")
    metrics_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    dash_p = sub.add_parser("dashboard", help="Start web dashboard")
    dash_p.add_argument(
        "--host", default=None, help="Bind host (default: from config or localhost)"
    )
    dash_p.add_argument(
        "--port", type=int, default=None, help="Port (default: from config or 3000)"
    )

    watch_p = sub.add_parser("watch", help="Terminal watch mode (TUI)")
    watch_p.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Refresh interval in seconds (default: from config or 2)",
    )

    audit_p = sub.add_parser("audit", help="Audit trail commands")
    audit_sub = audit_p.add_subparsers(dest="audit_command")
    audit_sub.add_parser("verify", help="Verify audit trail chain integrity")
    sig_p = audit_sub.add_parser("verify-sig", help="Verify artifact signature")
    sig_p.add_argument("tag", help="Git tag to verify")
    sig_p.add_argument("--public-key", help="Ed25519 public key (hex)")

    run_p = sub.add_parser("run", help="Execute milestones")
    run_p.add_argument("--milestone", help="Run a specific milestone")
    run_p.add_argument("--from", dest="from_ms", help="Start from milestone")
    run_p.add_argument("--to", dest="to_ms", help="End at milestone")
    run_p.add_argument("--phase", help="Run milestones matching phase prefix")
    run_p.add_argument("--dry-run", action="store_true", help="Preview without executing")
    run_p.add_argument(
        "--from-issue", dest="from_issue", help="GitHub issue number or owner/repo#N"
    )
    run_p.add_argument(
        "--from-ticket", dest="from_ticket", help="Tracker ticket ID (e.g. LIN-42, PROJ-123)"
    )
    run_p.add_argument(
        "--parallel", action="store_true", default=False, help="Enable parallel execution"
    )
    run_p.add_argument("--workers", type=int, default=4, help="Max parallel workers (default: 4)")
    run_p.add_argument("--remote", default=None, help="Remote execution URL (ssh://...)")
    run_p.add_argument(
        "--best-of-n", dest="best_of_n", type=int, default=1, help="Run N copies, pick best"
    )
    run_p.add_argument(
        "--model-override",
        dest="model_override",
        default=None,
        help="Override model for all milestones",
    )

    bootstrap_p = sub.add_parser("bootstrap", help="One-command project setup")
    bootstrap_p.add_argument(
        "--type",
        dest="project_type",
        default=None,
        help="Project type (python, typescript). Auto-detected if omitted.",
    )

    upgrade_p = sub.add_parser("upgrade", help="Detect and upgrade outdated dependencies")
    upgrade_p.add_argument(
        "--dry-run", action="store_true", help="List outdated deps without upgrading"
    )

    plugin_p = sub.add_parser("plugin", help="Manage plugins")
    plugin_sub = plugin_p.add_subparsers(dest="plugin_command")
    plugin_sub.add_parser("list", help="Show installed plugins")
    add_p = plugin_sub.add_parser("add", help="Install a plugin")
    add_p.add_argument("plugin_name", help="Plugin name (installs sw-plugin-{name})")
    remove_p = plugin_sub.add_parser("remove", help="Remove a plugin")
    remove_p.add_argument("plugin_name", help="Plugin name (uninstalls sw-plugin-{name})")

    return parser


def _cmd_init(project_root: Path) -> None:
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config_path = claude_dir / "workflow.json"
    if config_path.exists():
        print(f"  workflow.json already exists at {config_path}")
        return

    default_config = {
        "schema_version": 1,
        "spec": "",
        "model": "opus",
        "fallback_model": "haiku",
        "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "max_total_budget_usd": 500,
        "delay_between_phases_seconds": 10,
        "convergence": {
            "max_iterations": 5,
            "min_gaps_for_substantial": 20,
            "persistent_gap_downgrade_after": 3,
        },
        "verify_commands": {"test": "python -m pytest -q", "lint": None, "format": None},
        "git_strategy": "main",
        "telemetry": {
            "enabled": True,
            "path": ".claude/telemetry.jsonl",
        },
        "dashboard": {
            "host": "localhost",
            "port": 3000,
            "watch_interval": 2,
        },
        "security": {
            "audit_trail": False,
            "sign_artifacts": False,
            "sbom_tool": "",
            "sbom_output": ".claude/sbom-{milestone}.json",
            "public_key": "",
        },
        "secrets": {},
        "policies": {},
        "integrations": {
            "github": {
                "default_repo": "",
                "auto_pr": False,
                "issue_label_map": {"bug": "fix", "feature": "feature", "refactor": "refactor"},
            },
            "slack": {
                "webhook_url_env": "",
                "events": ["milestone_start", "milestone_complete", "milestone_failed", "ci_fix"],
            },
            "ci": {
                "enabled": False,
                "max_fix_attempts": 3,
                "wait_timeout_seconds": 600,
                "poll_interval_seconds": 30,
            },
            "tracker": {},
        },
        "model_routing": {
            "enabled": False,
            "default_model": "opus",
            "rules": [
                {"threshold": 0.7, "model": "opus"},
                {"threshold": 0.3, "model": "sonnet"},
                {"threshold": 0.0, "model": "haiku"},
            ],
        },
        "parallel": {
            "enabled": False,
            "max_workers": 4,
            "best_of_n": 1,
            "agent_teams_count": 0,
            "remote": None,
            "worktree_dir": ".worktrees",
        },
        "docs": {
            "readme": {
                "enabled": False,
                "template": None,
                "sections": ["overview", "quickstart", "architecture", "contributing"],
            },
            "changelog": {
                "enabled": True,
            },
            "api": {
                "tool": "sphinx",
                "output_dir": "docs/api",
            },
            "diagrams": {
                "enabled": True,
                "output": "docs/architecture.mmd",
            },
        },
        "plugins": {
            "enabled": True,
            "blocked": [],
        },
        "notification_webhook": None,
        "milestones": [],
    }
    config_path.write_text(json.dumps(default_config, indent=2))

    specs_dir = project_root / "docs" / "superpowers" / "specs"
    if specs_dir.exists():
        specs = sorted(specs_dir.glob("*.md"))
        if specs:
            config = json.loads(config_path.read_text())
            config["spec"] = str(specs[-1].relative_to(project_root))
            config_path.write_text(json.dumps(config, indent=2))
            print(f"  Auto-discovered spec: {config['spec']}")

    gitignore = project_root / ".gitignore"
    entries = [
        ".claude/workflow-state.json",
        ".claude/.workflow-phase.json",
        ".claude/.gap-report.json",
        ".claude/.workflow.lock",
        ".claude/workflow-*.log",
        ".claude/telemetry.jsonl",
        ".claude/audit-trail.jsonl",
        ".worktrees/",
    ]
    existing = gitignore.read_text() if gitignore.exists() else ""
    new_entries = [e for e in entries if e not in existing]
    if new_entries:
        with open(gitignore, "a") as f:
            f.write("\n# superpower-workflow runtime files\n")
            for e in new_entries:
                f.write(f"{e}\n")
        print(f"  Added {len(new_entries)} entries to .gitignore")

    print(f"  Created {config_path}")
    print("  Edit the spec path and verify_commands, then run: sw decompose")


def _cmd_metrics(project_root: Path, json_output: bool = False) -> None:
    from superpower_workflow.telemetry import TelemetryReader

    telemetry_rel = ".claude/telemetry.jsonl"
    config_path = project_root / ".claude" / "workflow.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            telemetry_rel = config.get("telemetry", {}).get("path", telemetry_rel)
        except (json.JSONDecodeError, OSError):
            pass
    path = project_root / telemetry_rel
    reader = TelemetryReader(path)
    events = reader.events()

    if not events:
        print("  No telemetry data. Run: sw run")
        return

    if json_output:
        metrics = {
            "total_cost": reader.total_cost(),
            "cost_per_task": reader.cost_per_successful_task(),
            "cost_by_milestone": reader.cost_by_milestone(),
            "cost_by_phase": reader.cost_by_phase(),
            "duration_by_milestone": reader.duration_by_milestone(),
            "duration_by_phase": reader.duration_by_phase(),
            "rework_rate": reader.rework_rate(),
            "defect_density": reader.defect_density(),
            "quality_trend": reader.quality_trend(),
            "total_duration": reader.total_duration(),
        }
        print(json.dumps(metrics, indent=2))
        return

    run_id = reader.latest_run_id()
    completed = reader.events_by_type("run_completed")
    latest = completed[-1] if completed else {}

    print(f"  Status: {latest.get('status', 'unknown')}")
    print(f"  Total cost: ${reader.total_cost():.2f}")
    print(f"  Cost per task: ${reader.cost_per_successful_task():.2f}")
    print(f"  Total duration: {reader.total_duration():.0f}s")
    print(f"  Rework rate: {reader.rework_rate():.1%}")
    print(f"  Defect density: {reader.defect_density():.1%}")

    cost_ms = reader.cost_by_milestone(run_id=run_id)
    if cost_ms:
        print("  Cost by milestone:")
        for name, cost in cost_ms.items():
            print(f"    {name}: ${cost:.2f}")

    cost_ph = reader.cost_by_phase(run_id=run_id)
    if cost_ph:
        print("  Cost by phase:")
        for phase, cost in cost_ph.items():
            print(f"    {phase}: ${cost:.2f}")


def _cmd_dashboard(project_root: Path, host: str | None = None, port: int | None = None) -> None:
    import time

    from superpower_workflow.dashboard.data import DashboardData
    from superpower_workflow.dashboard.server import DashboardServer

    config_path = project_root / ".claude" / "workflow.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            dash_cfg = config.get("dashboard", {})
            if host is None:
                host = dash_cfg.get("host", "localhost")
            if port is None:
                port = dash_cfg.get("port", 3000)
        except (json.JSONDecodeError, OSError):
            pass
    host = host or "localhost"
    port = port or 3000

    data = DashboardData(project_root)
    server = DashboardServer(data, host=host, port=port)
    try:
        server.start()
    except OSError as e:
        print(f"  Error: {e}")
        print(f"  Port {port} may be in use. Try: sw dashboard --port <other>")
        sys.exit(1)
    print(f"  Dashboard running at http://{host}:{server.port}/")
    print("  Press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("\n  Dashboard stopped")


def _cmd_watch(project_root: Path, interval: float | None = None) -> None:
    from superpower_workflow.dashboard.data import DashboardData
    from superpower_workflow.dashboard.watch import TerminalWatch

    if interval is None:
        config_path = project_root / ".claude" / "workflow.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                interval = config.get("dashboard", {}).get("watch_interval", 2.0)
            except (json.JSONDecodeError, OSError):
                pass
    interval = interval or 2.0

    data = DashboardData(project_root)
    watch = TerminalWatch(data, interval=interval)
    watch.start()


def _cmd_audit_verify(project_root: Path) -> None:
    from superpower_workflow.audit import AuditTrail, derive_key

    audit_path = project_root / ".claude" / "audit-trail.jsonl"
    if not audit_path.exists():
        print("  No audit trail found.")
        return
    key = derive_key()
    if not key:
        print("  Error: SW_AUDIT_KEY not set. Cannot verify.")
        return
    trail = AuditTrail(audit_path, key=key)
    valid, last_seq = trail.verify()
    if valid:
        print(f"  Audit trail OK. {last_seq + 1} entries verified.")
    else:
        print(f"  INVALID: chain broken after seq {last_seq}. Possible tampering.")
        sys.exit(1)


def _cmd_audit_verify_sig(project_root: Path, tag: str, public_key: str | None) -> None:
    from superpower_workflow.security import verify_signature

    if not public_key:
        config_path = project_root / ".claude" / "workflow.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                public_key = config.get("security", {}).get("public_key", "")
            except (json.JSONDecodeError, OSError):
                pass
    if not public_key:
        print("  Error: No public key. Use --public-key or set security.public_key in config.")
        return
    valid = verify_signature(tag=tag, public_key_hex=public_key, cwd=str(project_root))
    if valid:
        print(f"  Signature valid for {tag}.")
    else:
        print(f"  Signature INVALID or missing for {tag}.")
        sys.exit(1)


def _cmd_decompose(project_root: Path) -> None:
    from superpower_workflow.decomposer import decompose
    from superpower_workflow.state import load_config

    config = load_config(project_root / ".claude")
    spec_path = config.get("spec", "")
    if not spec_path or not (project_root / spec_path).exists():
        print(f"  Error: spec not found at '{spec_path}'. Update .claude/workflow.json")
        sys.exit(1)

    print(f"  Decomposing spec: {spec_path}")
    milestones = decompose(
        spec_path=spec_path,
        model=config.get("model", "opus"),
        cwd=str(project_root),
        fallback_model=config.get("fallback_model"),
    )
    if not milestones:
        print("  Error: decomposition returned no milestones")
        sys.exit(1)

    config["milestones"] = milestones
    config_path = project_root / ".claude" / "workflow.json"
    config_path.write_text(json.dumps(config, indent=2))
    print(f"  Wrote {len(milestones)} milestones to workflow.json:")
    for ms in milestones:
        print(f"    - {ms['name']}: {ms.get('description', '')}")


_PLUGIN_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _validate_plugin_name(name: str) -> bool:
    return bool(_PLUGIN_NAME_RE.match(name)) and len(name) <= 64


def _cmd_plugin_add(name: str) -> None:
    if not _validate_plugin_name(name):
        print(f"  Invalid plugin name: {name!r}. Must be alphanumeric with hyphens/underscores.")
        return
    package = f"sw-plugin-{name}"
    result = subprocess.run(
        ["pip", "install", package],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0:
        print(f"  Installed {package}")
    else:
        print(f"  Failed to install {package}: {result.stderr.strip()}")


def _cmd_plugin_remove(name: str) -> None:
    if not _validate_plugin_name(name):
        print(f"  Invalid plugin name: {name!r}. Must be alphanumeric with hyphens/underscores.")
        return
    package = f"sw-plugin-{name}"
    result = subprocess.run(
        ["pip", "uninstall", "-y", package],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        print(f"  Removed {package}")
    else:
        print(f"  Failed to remove {package}: {result.stderr.strip()}")


def _cmd_resume(project_root: Path) -> None:
    from superpower_workflow.orchestrator import Orchestrator
    from superpower_workflow.state import load_state

    state = load_state(project_root / ".claude")
    if not state.current_step and not state.completed:
        print("  Nothing to resume. Run: sw run")
        return

    step = state.current_step
    idx = state.current_milestone_index
    print(f"  Resuming from milestone #{idx}, step={step or 'next milestone'}")
    if step == "implement":
        print("  Phase B was interrupted. Checking git for partial progress...")

    orch = Orchestrator(project_root)
    orch.run()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    project_root = Path.cwd()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "init":
        _cmd_init(project_root)
        return

    if args.command == "audit":
        if args.audit_command == "verify":
            _cmd_audit_verify(project_root)
        elif args.audit_command == "verify-sig":
            _cmd_audit_verify_sig(
                project_root,
                tag=args.tag,
                public_key=getattr(args, "public_key", None),
            )
        else:
            parser.parse_args(["audit", "--help"])
        return

    if args.command == "doctor":
        from superpower_workflow.doctor import run_checks

        results = run_checks(project_root)
        for r in results:
            status = "+" if r.ok else "x"
            print(f"  {status} {r.message}")
        sys.exit(0 if all(r.ok for r in results) else 1)

    if args.command == "metrics":
        _cmd_metrics(project_root, json_output=getattr(args, "json_output", False))
        return

    if args.command == "decompose":
        _cmd_decompose(project_root)
        return

    if args.command == "estimate":
        from superpower_workflow.estimator import estimate
        from superpower_workflow.state import load_config

        config = load_config(project_root / ".claude")
        est = estimate(config)
        print(f"  Milestones: {est['milestone_count']}")
        print(f"  Cost: ${est['cost_optimistic']}-${est['cost_pessimistic']}")
        print(f"  Duration: {est['duration_optimistic_min']}-{est['duration_pessimistic_min']} min")
        return

    if args.command == "status":
        from superpower_workflow.state import load_state

        state = load_state(project_root / ".claude")
        print(f"  Completed: {len(state.completed)} milestones")
        print(f"  Cost so far: ${state.total_cost_usd:.2f}")
        if state.current_step:
            print(
                f"  Current: milestone #{state.current_milestone_index}, step={state.current_step}"
            )
        for m in state.completed:
            print(f"    + {m}")
        for m in state.failed:
            print(f"    x {m} (FAILED)")
        for m in state.skipped:
            print(f"    - {m} (skipped)")
        return

    if args.command == "dashboard":
        _cmd_dashboard(project_root, host=args.host, port=args.port)
        return

    if args.command == "watch":
        _cmd_watch(project_root, interval=args.interval)
        return

    if args.command == "run":
        from superpower_workflow.orchestrator import Orchestrator

        orch = Orchestrator(project_root)
        orch.run(
            dry_run=args.dry_run,
            milestone_filter=args.milestone,
            from_ms=args.from_ms,
            to_ms=args.to_ms,
            phase_prefix=getattr(args, "phase", None),
            from_issue=getattr(args, "from_issue", None),
            from_ticket=getattr(args, "from_ticket", None),
            parallel=getattr(args, "parallel", False),
            max_workers=getattr(args, "workers", 4),
            remote_url=getattr(args, "remote", None),
            best_of_n=getattr(args, "best_of_n", 1),
            model_override=getattr(args, "model_override", None),
        )
        return

    if args.command == "resume":
        _cmd_resume(project_root)
        return

    if args.command == "bootstrap":
        from superpower_workflow.bootstrap import bootstrap

        cwd = Path.cwd()
        created = bootstrap(cwd, project_type=args.project_type)
        if created:
            print(f"  Created {len(created)} files:")
            for f in created:
                print(f"    {f}")
        else:
            print("  All files already exist. Nothing to do.")
        return

    if args.command == "upgrade":
        from superpower_workflow.upgrade import (
            detect_package_manager,
            list_outdated,
            perform_upgrade,
        )

        cwd = Path.cwd()
        pm = detect_package_manager(cwd)
        if pm == "unknown":
            print("  Could not detect package manager.")
            sys.exit(1)
        outdated = list_outdated(pm, cwd=str(cwd))
        if not outdated:
            print("  All dependencies are up to date.")
            return
        print(f"  Found {len(outdated)} outdated dependencies:")
        for dep in outdated:
            flag = " [BREAKING]" if dep.is_breaking else ""
            print(f"    {dep.name}: {dep.current} -> {dep.latest}{flag}")
        if args.dry_run:
            return
        for dep in outdated:
            result = perform_upgrade(dep, cwd=str(cwd))
            if result.upgraded:
                branch_info = f" (branch: {result.branch})" if result.branch else ""
                print(f"    Upgraded {dep.name} to {dep.latest}{branch_info}")
            else:
                print(f"    Failed to upgrade {dep.name}: {result.error}")
        return

    if args.command == "plugin":
        if args.plugin_command == "list":
            from superpower_workflow.plugins.loader import load_plugins

            plugins = load_plugins()
            if not plugins:
                print("  No plugins installed.")
            else:
                for p in plugins:
                    print(f"  {p.name} v{p.version}")
        elif args.plugin_command == "add":
            _cmd_plugin_add(args.plugin_name)
        elif args.plugin_command == "remove":
            _cmd_plugin_remove(args.plugin_name)
        return
