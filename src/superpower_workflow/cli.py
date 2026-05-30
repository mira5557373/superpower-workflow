from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from superpower_workflow import __version__

# Gitignore templates — extracted as module constants so `sw migrate-gitignore`
# (T1.6.2) can apply the same set to existing projects idempotently.
SW_GITIGNORE_ENTRIES: tuple[str, ...] = (
    ".claude/workflow-state.json",
    ".claude/.workflow-phase.json",
    ".claude/.gap-report.json",
    ".claude/.gap-report.raw.json",
    ".claude/.workflow.lock",
    ".claude/.workflow.lock.json",
    ".claude/.workflow.lock.filelock",
    ".claude/workflow-complete.json",
    ".claude/workflow-*.log",
    ".claude/telemetry.jsonl",
    ".claude/audit-trail.jsonl",
    ".worktrees/",
    ".claude/.gap-validation.json",
    ".claude/.spec-compliance.json",
    ".claude/.feature-verification.json",
    ".claude/.quality-gate-results.json",
    ".claude/reports/",
)

PYTHON_GITIGNORE_ENTRIES: tuple[str, ...] = (
    ".venv/",
    "__pycache__/",
    "*.pyc",
    "dist/",
    "build/",
    "*.egg-info/",
    # Coverage + tool caches (T1.6.2: gap G1.6.5 — these have tripped the
    # orchestrator's uncommitted-changes preflight in real soaks)
    ".coverage",
    ".coverage.*",
    "htmlcov/",
    ".tox/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytest_cache/",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sw", description="Superpower Workflow Orchestrator")
    parser.add_argument("--version", action="version", version=f"sw {__version__}")
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Create .claude/workflow.json")
    init_p.add_argument(
        "--with-quality-gates",
        action="store_true",
        help="Pre-populate quality_gates with language-detected defaults "
        "(bandit/radon/pip-audit for Python, npm audit for JS/TS, etc.)",
    )
    init_p.add_argument(
        "--minimal",
        action="store_true",
        help="Skip auto-detected verify_commands and quality_gates (advanced users)",
    )
    sub.add_parser("doctor", help="Pre-flight health checks")

    lint_p = sub.add_parser(
        "lint-spec",
        help="Lint a spec.md file (zero-LLM rule-based checks)",
    )
    lint_p.add_argument("spec_path", help="Path to the spec file (markdown)")
    lint_p.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on WARN findings too (default: only FAIL is non-zero)",
    )
    lint_p.add_argument(
        "--section",
        default=None,
        help="Lint only the named section (matches heading text)",
    )

    decompose_p = sub.add_parser("decompose", help="Spec to milestone breakdown")
    decompose_p.add_argument(
        "--force",
        action="store_true",
        help="Skip spec linter blockers (use only if you know what you're doing)",
    )
    sub.add_parser("estimate", help="Cost and duration estimate")
    sub.add_parser("status", help="Show progress")
    sub.add_parser("resume", help="Resume from failure point")
    sub.add_parser("clean", help="Remove runtime files")
    sub.add_parser(
        "migrate-gitignore",
        help="Append missing sw + Python entries to .gitignore (idempotent)",
    )
    sub.add_parser(
        "verify-defaults",
        help="Audit telemetry against the default-flip eligibility framework",
    )

    onboard_p = sub.add_parser(
        "onboard",
        help="Interactive wizard to set up .claude/workflow.json (T1.9.5)",
    )
    onboard_p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use defaults without prompting (smoke-test mode)",
    )

    recmodel_p = sub.add_parser(
        "recommend-model",
        help="Suggest best model for this project from historical telemetry (T1.9.3)",
    )
    recmodel_p.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    lock_p = sub.add_parser("lock", help="Inspect or force-clean the workflow lock")
    lock_sub = lock_p.add_subparsers(dest="lock_command")
    lock_sub.add_parser("status", help="Show lock holder details")
    lock_sub.add_parser("force-clean", help="Force-remove lock (use only if you're sure)")

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

    server_p = sub.add_parser("server", help="Unified dashboard server")
    server_sub = server_p.add_subparsers(dest="server_command")

    start_p = server_sub.add_parser("start", help="Start the API server")
    start_p.add_argument("--host", default=None, help="Bind host (default: 0.0.0.0)")
    start_p.add_argument("--port", type=int, default=None, help="Port (default: 3001)")
    start_p.add_argument("--database-url", dest="database_url", default=None, help="PostgreSQL URL")

    server_sub.add_parser("stop", help="Stop the API server")
    server_sub.add_parser("init-db", help="Initialize database schema")

    sync_p = server_sub.add_parser("sync", help="Sync JSONL data to database")
    sync_p.add_argument("--project", default=None, help="Project path to sync")
    sync_p.add_argument("--all", dest="sync_all", action="store_true", help="Sync all projects")

    return parser


def _cmd_init(
    project_root: Path,
    with_quality_gates: bool = False,
    minimal: bool = False,
) -> None:
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config_path = claude_dir / "workflow.json"
    if config_path.exists():
        print(f"  workflow.json already exists at {config_path}")
        return

    # v1.1.8: detect project type for per-language defaults (T1.8.4)
    profile = None
    if not minimal:
        from superpower_workflow.project_detect import detect

        profile = detect(project_root)
        if profile.languages:
            print(f"  Detected language(s): {', '.join(profile.languages)}")

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
        "verify_commands": (
            {k: v for k, v in profile.verify_commands.items()}
            if (profile and profile.verify_commands and not minimal)
            else {"test": None, "lint": None, "format": None}
        ),
        # v1.1.8: pre-populated when --with-quality-gates AND project type detected.
        # Stays empty otherwise — users opt in by setting commands here.
        "quality_gates": (
            {k: v for k, v in profile.quality_gates.items()}
            if (profile and profile.quality_gates and with_quality_gates and not minimal)
            else {}
        ),
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
                "enabled": True,
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
        "database": {
            "url_env": "SW_DATABASE_URL",
            "retention_days": 90,
            "auto_sync": True,
        },
        "server": {
            "host": "0.0.0.0",
            "port": 3001,
            "cors_origins": ["http://localhost:3001"],
        },
        "validation": {
            "gap_validator": True,
            "gap_validation_mode": "lenient",
            "spec_compliance": True,
            "feature_verification": True,
            "spec_compliance_budget": 3.0,
            "feature_verification_budget": 5.0,
            "strict_mode": False,
            "max_strict_iterations": 2,
            "strict_iteration_budget": 8.0,
            # Default flipped from False to True in v1.1.7 after the
            # 2026-05-30 A/B soak: 36.4% raw-gap attrition, zero false
            # negatives (spec compliance cross-check), 33% cost reduction
            # on M-all milestone. See soak-archive/ab-2026-05-30/REPORT.md.
            "gap_curator": True,
            "curator_budget": 1.0,
            "curator_min_gaps": 5,
            # New in v1.1.7: spec linter runs during `sw decompose`. Pure
            # text checks, zero LLM cost. Set false to disable; strict makes
            # WARN-level findings block decompose too.
            "spec_linter": True,
            "spec_linter_strict": False,
            "spec_max_words": 5000,
            "spec_min_words": 200,
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
    existing = gitignore.read_text() if gitignore.exists() else ""
    sw_new = [e for e in SW_GITIGNORE_ENTRIES if e not in existing]
    py_new = [e for e in PYTHON_GITIGNORE_ENTRIES if e not in existing]
    with open(gitignore, "a") as f:
        if sw_new:
            f.write("\n# superpower-workflow runtime files\n")
            for e in sw_new:
                f.write(f"{e}\n")
        if py_new:
            f.write("\n# Python standard ignores\n")
            for e in py_new:
                f.write(f"{e}\n")
    added = len(sw_new) + len(py_new)
    if added:
        print(f"  Added {added} entries to .gitignore")

    # Install skills, commands, and settings project-locally
    _install_project_local(claude_dir)

    try:
        from superpower_workflow.server.registry import ProjectRegistry

        reg = ProjectRegistry()
        reg.register(project_root.name, str(project_root))
    except Exception:
        pass

    print(f"  Created {config_path}")
    print("  Edit the spec path and verify_commands, then run: sw decompose")


def _assets_root() -> Path:
    """Return the bundled assets directory inside the installed package."""
    return Path(__file__).resolve().parent / "_assets"


def _install_project_local(claude_dir: Path) -> None:
    import shutil

    assets = _assets_root()

    # Copy custom skills
    skills_src = assets / "skills"
    skills_dst = claude_dir / "skills"
    if skills_src.exists():
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir():
                dst = skills_dst / skill_dir.name
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(skill_dir, dst)
                print(f"  Installed skill: {skill_dir.name}")

    # Copy commands
    cmds_src = assets / "commands"
    cmds_dst = claude_dir / "commands"
    if cmds_src.exists():
        cmds_dst.mkdir(parents=True, exist_ok=True)
        for cmd_file in cmds_src.glob("*.md"):
            shutil.copy2(cmd_file, cmds_dst / cmd_file.name)
            print(f"  Installed command: {cmd_file.name}")

    # Create project-local settings.local.json with plugins + hook
    settings_path = claude_dir / "settings.local.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            settings = {}

    # Enable superpowers plugin
    plugins = settings.setdefault("enabledPlugins", {})
    plugins["superpowers@claude-plugins-official"] = True

    # Set bypass permissions for unattended runs
    permissions = settings.setdefault("permissions", {})
    permissions["defaultMode"] = "bypassPermissions"

    # Register convergence hook project-locally
    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])
    hook_cmd = "python -m superpower_workflow.hooks.convergence_gate"
    if not any(hook_cmd in str(entry) for entry in stop_hooks):
        stop_hooks.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": hook_cmd, "timeout": 30}],
            }
        )

    settings_path.write_text(json.dumps(settings, indent=2))
    print("  Configured settings.local.json (superpowers + hook + permissions)")


def _cmd_migrate_gitignore(project_root: Path) -> None:
    """T1.6.2 / G1.6.6 — idempotently add missing sw + Python entries to an
    existing project's .gitignore.

    Reads the file (creates empty if absent), checks each constant against
    the current content with substring match, appends only the missing ones
    under labeled sections. Safe to re-run; no changes if everything is
    already present.
    """
    gitignore = project_root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    sw_new = [e for e in SW_GITIGNORE_ENTRIES if e not in existing]
    py_new = [e for e in PYTHON_GITIGNORE_ENTRIES if e not in existing]

    if not sw_new and not py_new:
        print("  .gitignore is up to date (no entries missing)")
        return

    lines: list[str] = []
    if sw_new:
        lines.append("")
        lines.append("# superpower-workflow runtime files")
        lines.extend(sw_new)
    if py_new:
        lines.append("")
        lines.append("# Python standard ignores")
        lines.extend(py_new)

    if existing and not existing.endswith("\n"):
        existing += "\n"
    gitignore.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Added {len(sw_new) + len(py_new)} entries to {gitignore}")
    if sw_new:
        print(f"    sw entries: {len(sw_new)}")
    if py_new:
        print(f"    python entries: {len(py_new)}")


def _cmd_verify_defaults(project_root: Path) -> None:
    """T1.6.4 / G1.6.8 — audit telemetry against the default-flip framework.

    The rule (documented in CHANGELOG): an opt-in feature flag flips from
    `false` → `true` only after >=3 milestones of data showing positive ROI
    (attrition >= 30% AND no quality regression).

    This command reads `.claude/telemetry.jsonl` and tells you whether each
    currently-off feature qualifies to be turned on by default in the next
    release.
    """
    telemetry = project_root / ".claude" / "telemetry.jsonl"
    if not telemetry.exists():
        print(f"  No telemetry found at {telemetry}")
        print("  Run at least 3 milestones before verify-defaults will be useful.")
        return

    curation_events: list[dict] = []
    strict_events: list[dict] = []
    milestone_count = 0
    try:
        for line in telemetry.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("type", "")
            if t == "gap_curation_completed":
                curation_events.append(e)
            elif t == "strict_mode_iteration":
                strict_events.append(e)
            elif t == "milestone_completed":
                milestone_count += 1
    except OSError as err:
        print(f"  Could not read telemetry: {err}")
        return

    print(f"\n  Milestones completed: {milestone_count}")
    print(f"  Curation events:      {len(curation_events)}")
    print(f"  Strict iterations:    {len(strict_events)}")
    print()

    if milestone_count < 3:
        print("  STATUS: insufficient data (need >= 3 completed milestones).")
        return

    # gap_curator default-flip check
    if curation_events:
        attritions = [e.get("attrition_pct", 0.0) for e in curation_events]
        avg_attrition = sum(attritions) / len(attritions) if attritions else 0.0
        passes = avg_attrition >= 30.0
        verdict = "QUALIFIES" if passes else "INSUFFICIENT"
        print(
            f"  validation.gap_curator default-flip: {verdict} "
            f"(avg attrition {avg_attrition:.1f}%, target >= 30%)"
        )
    else:
        print("  validation.gap_curator default-flip: no curation data collected")

    # strict_mode default-flip check
    if strict_events:
        converged = sum(1 for e in strict_events if e.get("converged"))
        conv_rate = converged / len(strict_events) * 100.0
        passes = conv_rate >= 80.0
        verdict = "QUALIFIES" if passes else "INSUFFICIENT"
        print(
            f"  validation.strict_mode default-flip: {verdict} "
            f"(convergence {conv_rate:.0f}%, target >= 80%)"
        )
    else:
        print(
            "  validation.strict_mode default-flip: no strict iterations observed "
            "(may be already-clean output)"
        )


def _cmd_onboard(project_root: Path, interactive: bool = True) -> None:
    """T1.9.5 — interactive `sw onboard` wizard."""
    from superpower_workflow.onboard import build_workflow_config, run_onboard, write_config

    choices = run_onboard(project_root, interactive=interactive)
    if choices.accept_existing == "abort":
        print("  Aborted. No changes written.")
        return

    config = build_workflow_config(project_root, choices)

    if interactive:
        print()
        print("  Proposed workflow.json:")
        print(f"    spec:                  {config['spec']}")
        print(f"    model:                 {config['model']}")
        print(
            f"    budgets/cap:           plan ${config['budgets']['plan']} "
            f"/ implement ${config['budgets']['implement']} "
            f"/ review ${config['budgets']['review']} "
            f"/ push ${config['budgets']['push']}  cap ${config['max_total_budget_usd']}"
        )
        print(f"    gap_curator:           {config['validation']['gap_curator']}")
        print(f"    strict_mode:           {config['validation']['strict_mode']}")
        print(f"    spec_linter:           {config['validation']['spec_linter']}")
        print(f"    quality_gates:         {len(config['quality_gates'])} preset gate(s)")
        sys.stdout.write("\n  Write this configuration? [Y/n]: ")
        sys.stdout.flush()
        answer = sys.stdin.readline().strip().lower()
        if answer and not answer.startswith("y"):
            print("  Aborted. No changes written.")
            return

    path = write_config(project_root, config)
    print(f"  Wrote {path}")
    print("  Next: edit your spec, then run `sw lint-spec` and `sw decompose`.")


def _cmd_recommend_model(project_root: Path, json_output: bool = False) -> None:
    """T1.9.3 — analyze telemetry and recommend the best model/cost tradeoff."""
    from superpower_workflow.recommender import recommend

    telemetry_path = project_root / ".claude" / "telemetry.jsonl"
    report = recommend(telemetry_path)

    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
        return

    if not report.models:
        print("  No model data — run at least one milestone first.")
        return

    print()
    print(f"  Recommended model: {report.recommended}")
    print(f"  Rationale: {report.rationale}")
    print()
    print(f"  {'Model':<10} {'#ms':>4} {'$avg':>7} {'compliance':>12} {'quality':>9}")
    for m in report.models:
        print(
            f"  {m.model:<10} {m.milestone_count:>4} "
            f"${m.avg_cost_per_milestone:>5.2f} "
            f"{m.spec_compliance_rate:>11.1%} {m.quality_score:>9.3f}"
        )


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
        run_id_for_tokens = reader.latest_run_id()
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
            "tokens": _aggregate_token_stats(events, run_id_for_tokens),
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

    # v1.1.7.3 — token analytics, available after the v1.1.6 fix
    token_stats = _aggregate_token_stats(events, run_id)
    if token_stats["total_input"] or token_stats["total_output"]:
        print("  Tokens (latest run):")
        print(
            f"    input:           {token_stats['total_input']:>10}  "
            f"output: {token_stats['total_output']:>10}"
        )
        print(
            f"    cache_creation:  {token_stats['total_cache_creation']:>10}  "
            f"cache_read: {token_stats['total_cache_read']:>10}"
        )
        print(
            f"    cache_hit_rate:  {token_stats['cache_hit_rate']:>10.3f}  "
            f"tokens/$: {token_stats['tokens_per_dollar']:>10.0f}"
        )
        if token_stats["per_phase"]:
            print("  Cache hit rate by phase:")
            for phase, rate in token_stats["per_phase"].items():
                print(f"    {phase:<10} {rate:.3f}")


def _aggregate_token_stats(events: list[dict], run_id: str = "") -> dict:
    """Aggregate token counts across PhaseCompleted events.

    Cache hit rate = cache_read / (input + cache_creation + cache_read), per the
    helper in runner.extract_token_usage. tokens_per_dollar = (input + output)
    / total_cost_usd (proxy for efficiency).
    """
    phase_events = [
        e
        for e in events
        if e.get("type") == "phase_completed" and (not run_id or e.get("run_id") == run_id)
    ]
    total_input = sum(int(e.get("input_tokens", 0) or 0) for e in phase_events)
    total_output = sum(int(e.get("output_tokens", 0) or 0) for e in phase_events)
    total_cc = sum(int(e.get("cache_creation_input_tokens", 0) or 0) for e in phase_events)
    total_cr = sum(int(e.get("cache_read_input_tokens", 0) or 0) for e in phase_events)
    total_cost = sum(float(e.get("cost_usd", 0.0) or 0.0) for e in phase_events)

    denom = total_input + total_cc + total_cr
    cache_hit_rate = round(total_cr / denom, 4) if denom > 0 else 0.0
    tokens_per_dollar = round((total_input + total_output) / total_cost) if total_cost > 0 else 0

    per_phase: dict[str, float] = {}
    for phase in ("plan", "implement", "review", "push", "ci_fix"):
        phase_evs = [e for e in phase_events if e.get("phase") == phase]
        if not phase_evs:
            continue
        i = sum(int(e.get("input_tokens", 0) or 0) for e in phase_evs)
        cc = sum(int(e.get("cache_creation_input_tokens", 0) or 0) for e in phase_evs)
        cr = sum(int(e.get("cache_read_input_tokens", 0) or 0) for e in phase_evs)
        d = i + cc + cr
        per_phase[phase] = round(cr / d, 4) if d > 0 else 0.0

    return {
        "total_input": total_input,
        "total_output": total_output,
        "total_cache_creation": total_cc,
        "total_cache_read": total_cr,
        "cache_hit_rate": cache_hit_rate,
        "tokens_per_dollar": tokens_per_dollar,
        "per_phase": per_phase,
    }


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


def _cmd_lock(project_root: Path, args) -> None:
    from superpower_workflow.state import get_lock_status, release_lock

    claude_dir = project_root / ".claude"
    sub = getattr(args, "lock_command", None)
    if sub == "status" or sub is None:
        status = get_lock_status(claude_dir)
        if status is None:
            print("  No active lock.")
            return
        print(f"  PID:       {status['pid']}")
        print(f"  Hostname:  {status['hostname']}")
        age = int(status.get("heartbeat_age_seconds", 0))
        print(f"  Heartbeat: {age}s ago")
        if status["stale"]:
            print(f"  Status:    STALE ({status['reason']})")
            print("  Hint:      sw lock force-clean   # to release")
        else:
            print("  Status:    ACTIVE")
        return
    if sub == "force-clean":
        release_lock(claude_dir)
        print("  Lock force-removed.")
        return


def _cmd_clean(project_root: Path) -> None:
    claude_dir = project_root / ".claude"
    removed = 0
    fixed_files = [
        "workflow-state.json",
        ".workflow-phase.json",
        ".gap-report.json",
        ".workflow.lock",
        "workflow-complete.json",
    ]
    for name in fixed_files:
        path = claude_dir / name
        if path.exists():
            path.unlink()
            removed += 1
            print(f"  Removed .claude/{name}")
    for path in claude_dir.glob("workflow-*.log"):
        path.unlink()
        removed += 1
        print(f"  Removed .claude/{path.name}")
    telemetry_path = claude_dir / "telemetry.jsonl"
    config_path = claude_dir / "workflow.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            rel = config.get("telemetry", {}).get("path", ".claude/telemetry.jsonl")
            telemetry_path = project_root / rel
        except (json.JSONDecodeError, OSError):
            pass
    if telemetry_path.exists():
        telemetry_path.unlink()
        removed += 1
        print(f"  Removed {telemetry_path.name}")
    if removed == 0:
        print("  Nothing to clean.")
    else:
        print(f"  Cleaned {removed} runtime file(s).")


_FAIL_GLYPH = "x"
_WARN_GLYPH = "!"
_PASS_GLYPH = "+"


def _print_spec_lint_report(report) -> None:
    """Pretty-print SpecLintReport to stdout (T1.7.2)."""
    from superpower_workflow.validation.spec_linter import CheckState

    print(f"\n  Spec lint: {report.spec_path}")
    print(
        f"  Score: {report.score}/100  ({report.blocker_count} FAIL, {report.warning_count} WARN)\n"
    )
    for c in report.checks:
        if c.state == CheckState.PASS:
            glyph = _PASS_GLYPH
        elif c.state == CheckState.WARN:
            glyph = _WARN_GLYPH
        else:
            glyph = _FAIL_GLYPH
        print(f"  [{glyph}] {c.state.value:<4} {c.name:<26} {c.reason}")
        if c.suggestion and c.state != CheckState.PASS:
            print(f"           hint: {c.suggestion}")
    print()


def _emit_spec_lint_event(claude_dir: Path, report, run_id: str = "") -> None:
    """Append a SpecLintCompleted event to telemetry.jsonl if it exists."""
    from superpower_workflow.validation.spec_linter import CheckState

    telemetry_path = claude_dir / "telemetry.jsonl"
    if not claude_dir.exists():
        return
    event = {
        "type": "spec_lint_completed",
        "run_id": run_id,
        "spec_path": report.spec_path,
        "score": report.score,
        "checks_passed": sum(1 for c in report.checks if c.state == CheckState.PASS),
        "checks_warned": report.warning_count,
        "checks_failed": report.blocker_count,
        "blocker_count": report.blocker_count,
    }
    try:
        with telemetry_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass


def _cmd_lint_spec(project_root: Path, spec_path: str, strict: bool, section: str | None) -> int:
    """T1.7.2 — standalone `sw lint-spec` subcommand."""
    from superpower_workflow.state import load_config
    from superpower_workflow.validation.spec_linter import lint_spec

    full = (project_root / spec_path).resolve()
    if not full.is_file():
        print(f"  Error: spec not found at {full}")
        return 1

    claude_dir = project_root / ".claude"
    config: dict = {}
    if (claude_dir / "workflow.json").exists():
        try:
            config = load_config(claude_dir)
        except (OSError, FileNotFoundError):
            config = {}
    validation = config.get("validation", {}) if isinstance(config, dict) else {}
    min_words = int(validation.get("spec_min_words", 200))
    max_words = int(validation.get("spec_max_words", 5000))

    report = lint_spec(full, min_words=min_words, max_words=max_words, section=section)
    _print_spec_lint_report(report)
    _emit_spec_lint_event(claude_dir, report)

    if report.blocker_count > 0:
        return 1
    if strict and report.warning_count > 0:
        return 1
    return 0


def _cmd_decompose(project_root: Path, force: bool = False) -> None:
    from superpower_workflow.decomposer import decompose
    from superpower_workflow.state import load_config
    from superpower_workflow.validation.spec_linter import lint_spec

    claude_dir = project_root / ".claude"
    config = load_config(claude_dir)
    spec_path = config.get("spec", "")
    if not spec_path or not (project_root / spec_path).exists():
        print(f"  Error: spec not found at '{spec_path}'. Update .claude/workflow.json")
        sys.exit(1)

    # T1.7.3: auto-run spec linter before spending decomposition tokens
    validation = config.get("validation", {})
    if validation.get("spec_linter", True):
        report = lint_spec(
            project_root / spec_path,
            min_words=int(validation.get("spec_min_words", 200)),
            max_words=int(validation.get("spec_max_words", 5000)),
        )
        _print_spec_lint_report(report)
        _emit_spec_lint_event(claude_dir, report)

        if report.blocker_count > 0 and not force:
            print(
                f"  Decompose aborted: spec has {report.blocker_count} blocker(s). "
                "Fix them or rerun with --force."
            )
            sys.exit(1)
        if validation.get("spec_linter_strict", False) and report.warning_count > 0 and not force:
            print(
                f"  Decompose aborted (strict): {report.warning_count} warning(s). "
                "Fix them or rerun with --force."
            )
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


def _cmd_server_start(project_root: Path, args) -> None:
    import os

    if args.database_url:
        os.environ["SW_DATABASE_URL"] = args.database_url
    if args.host:
        os.environ["SW_SERVER_HOST"] = args.host
    if args.port:
        os.environ["SW_SERVER_PORT"] = str(args.port)

    try:
        from superpower_workflow.server.app import create_app
        from superpower_workflow.server.config import load_server_config
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        sys.exit(1)

    import contextlib

    config_path = project_root / ".claude" / "workflow.json"
    config = {}
    if config_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            config = json.loads(config_path.read_text())

    cfg = load_server_config(config)
    app = create_app(cfg)

    from fastapi.responses import HTMLResponse

    from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

    @app.get("/")
    def dashboard():
        return HTMLResponse(UNIFIED_DASHBOARD_HTML)

    import uvicorn

    pid_file = Path.home() / ".claude" / "sw-server.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    print(f"  Server starting at http://{cfg.host}:{cfg.port}/")
    try:
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    finally:
        pid_file.unlink(missing_ok=True)


def _cmd_server_stop() -> None:
    pid_file = Path.home() / ".claude" / "sw-server.pid"
    if not pid_file.exists():
        print("  No server PID file found.")
        return
    try:
        import signal

        pid = int(pid_file.read_text().strip())
        import os as _os

        _os.kill(pid, signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        print(f"  Stopped server (PID {pid})")
    except (ProcessLookupError, ValueError):
        pid_file.unlink(missing_ok=True)
        print("  Server not running.")


def _cmd_server_init_db(args) -> None:
    import os

    db_url = getattr(args, "database_url", None) or os.environ.get("SW_DATABASE_URL", "")
    if not db_url:
        print("  Error: Set SW_DATABASE_URL or use --database-url")
        return
    try:
        from superpower_workflow.db.engine import create_engine_from_url
        from superpower_workflow.db.models import Base
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        return
    engine = create_engine_from_url(db_url)
    Base.metadata.create_all(engine)
    print("  Database schema created.")


def _cmd_server_sync(project_root: Path, args) -> None:
    import os

    db_url = os.environ.get("SW_DATABASE_URL", "")
    if not db_url:
        print("  Error: Set SW_DATABASE_URL")
        return
    try:
        from superpower_workflow.db.engine import create_engine_from_url
        from superpower_workflow.db.models import Base
        from superpower_workflow.db.sync_adapter import DbSyncAdapter
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        return
    engine = create_engine_from_url(db_url)
    Base.metadata.create_all(engine)
    adapter = DbSyncAdapter(engine)

    if getattr(args, "sync_all", False):
        from superpower_workflow.server.registry import ProjectRegistry

        registry = ProjectRegistry()
        for entry in registry.list_projects():
            p = Path(entry.path)
            jsonl = p / ".claude" / "telemetry.jsonl"
            if jsonl.exists():
                adapter.sync(entry.name, entry.path, jsonl)
                print(f"  Synced: {entry.name}")
    elif getattr(args, "project", None):
        p = Path(args.project)
        name = p.name
        jsonl = p / ".claude" / "telemetry.jsonl"
        adapter.sync(name, str(p), jsonl)
        print(f"  Synced: {name}")
    else:
        name = project_root.name
        config_path = project_root / ".claude" / "workflow.json"
        telemetry_rel = ".claude/telemetry.jsonl"
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text())
                telemetry_rel = cfg.get("telemetry", {}).get("path", telemetry_rel)
            except (json.JSONDecodeError, OSError):
                pass
        jsonl = project_root / telemetry_rel
        adapter.sync(name, str(project_root), jsonl)
        print(f"  Synced: {name}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    project_root = Path.cwd()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "init":
        _cmd_init(
            project_root,
            with_quality_gates=getattr(args, "with_quality_gates", False),
            minimal=getattr(args, "minimal", False),
        )
        return

    if args.command == "migrate-gitignore":
        _cmd_migrate_gitignore(project_root)
        return

    if args.command == "verify-defaults":
        _cmd_verify_defaults(project_root)
        return

    if args.command == "onboard":
        _cmd_onboard(project_root, interactive=not getattr(args, "non_interactive", False))
        return

    if args.command == "recommend-model":
        _cmd_recommend_model(project_root, json_output=getattr(args, "json_output", False))
        return

    if args.command == "clean":
        _cmd_clean(project_root)
        return

    if args.command == "lock":
        _cmd_lock(project_root, args)
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

    if args.command == "lint-spec":
        sys.exit(_cmd_lint_spec(project_root, args.spec_path, args.strict, args.section))

    if args.command == "decompose":
        _cmd_decompose(project_root, force=getattr(args, "force", False))
        return

    if args.command == "estimate":
        from superpower_workflow.estimator import estimate
        from superpower_workflow.state import load_config

        config = load_config(project_root / ".claude")
        est = estimate(config, project_root=project_root)
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

    if args.command == "server":
        if args.server_command == "start":
            _cmd_server_start(project_root, args)
        elif args.server_command == "stop":
            _cmd_server_stop()
        elif args.server_command == "init-db":
            _cmd_server_init_db(args)
        elif args.server_command == "sync":
            _cmd_server_sync(project_root, args)
        else:
            parser.parse_args(["server", "--help"])
        return
