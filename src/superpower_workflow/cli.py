from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
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
    fc_p = lock_sub.add_parser(
        "force-clean",
        help="Force-remove lock (acquires filelock first; prompts unless --yes)",
    )
    fc_p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (use only if you're certain)",
    )

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

    sub.add_parser(
        "mcp-server",
        help=(
            "Run the sw MCP server over stdio. Launched by Claude Code "
            "via .mcp.json; surfaces 7 read-only tools for inspecting "
            "workflow state, metrics, gap reports, and pre-flight health."
        ),
    )

    drift_p = sub.add_parser(
        "drift",
        help=(
            "Inspect drift baselines + recent drift events. Reads telemetry "
            "and recomputes per-metric assessments without writing anything."
        ),
    )
    drift_p.add_argument("--json", action="store_true", help="Emit JSON instead of human text")
    drift_p.add_argument(
        "--baseline",
        action="store_true",
        help="Print per-metric baseline stats only (no live assessment)",
    )
    drift_p.add_argument(
        "--metric",
        help="Filter to one metric (cost_usd | duration_ms | cache_hit_rate | gap_attrition_pct | strict_iterations)",
    )
    drift_p.add_argument(
        "--phase",
        help="Filter to one phase bucket (plan | implement | review | push)",
    )
    drift_p.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Reset state.drift_alerts_emitted_this_milestone — useful "
            "after a deliberate model swap or config change so the next "
            "phase can re-emit alerts on the new baseline."
        ),
    )

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
    run_p.add_argument(
        "--ignore-ceiling",
        dest="ignore_ceiling",
        action="store_true",
        default=False,
        help=(
            "Override rolling cost ceiling block. Requires SW_ALLOW_CEILING_BYPASS=1 "
            "env var OR interactive TTY confirmation. Audit-logged."
        ),
    )

    # v1.3.21 — sw triage subcommand: rule-only failure classifier replay.
    triage_p = sub.add_parser(
        "triage",
        help=(
            "Classify failures in the project's telemetry into typed "
            "FailureClass values with confidence + evidence + recommendation."
        ),
    )
    triage_p.add_argument(
        "--milestone",
        default=None,
        help="Show only the failure for this milestone (deep view + full evidence chain)",
    )
    triage_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")

    # v1.3.20 — sw budget subcommand for rolling cost ceiling visibility + config.
    budget_p = sub.add_parser(
        "budget",
        help="Inspect + manage rolling cost ceilings (24h / 7d / 30d).",
    )
    budget_sub = budget_p.add_subparsers(dest="budget_command")
    budget_show = budget_sub.add_parser(
        "show", help="Show current rolling spend, ceiling, headroom per window."
    )
    budget_show.add_argument(
        "--window",
        choices=["day", "week", "month", "all"],
        default="all",
        help="Filter to one window (default: all)",
    )
    budget_show.add_argument("--json", action="store_true", help="Emit JSON output")
    budget_set = budget_sub.add_parser("set", help="Set ceilings in .claude/workflow.json.")
    budget_set.add_argument("--daily", type=float, default=None, help="Daily ceiling USD")
    budget_set.add_argument("--weekly", type=float, default=None, help="Weekly ceiling USD")
    budget_set.add_argument("--monthly", type=float, default=None, help="Monthly ceiling USD")
    budget_set.add_argument(
        "--mode",
        choices=["warn", "block"],
        default="block",
        help="Default mode for newly-set ceilings (default: block)",
    )
    budget_reset = budget_sub.add_parser(
        "reset",
        help="Clear a window's accumulated spend (e.g. after incident recovery).",
    )
    budget_reset.add_argument(
        "--window",
        choices=["day", "week", "month"],
        required=True,
        help="Window to reset",
    )
    budget_reset.add_argument(
        "--confirm",
        action="store_true",
        help="Required: actually perform the reset (without it, prints what would happen)",
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


def default_workflow_config(
    profile=None,
    *,
    with_quality_gates: bool = False,
    minimal: bool = False,
) -> dict:
    """v1.3.3 #7: the single source of truth for workflow.json defaults.

    Both `_cmd_init` and `onboard.build_workflow_config` call this. Before
    v1.3.3, init wrote 27 top-level keys but build_workflow_config emitted
    only 15 — onboarded projects silently fell back to orchestrator hard-
    coded defaults for the missing 12 (dashboard, database, parallel,
    plugins, etc.). Centralizing the dict here makes drift impossible by
    construction: any new key automatically reaches both surfaces.

    Caller-specific overrides (onboard's model/budgets from user choices,
    init's verify_commands from project_detect) layer on top via
    `_shallow_merge` or direct dict update.
    """
    return {
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

    default_config = default_workflow_config(
        profile=profile,
        with_quality_gates=with_quality_gates,
        minimal=minimal,
    )
    config_path.write_text(json.dumps(default_config, indent=2))

    specs_dir = project_root / "docs" / "superpowers" / "specs"
    if specs_dir.exists():
        specs = sorted(specs_dir.glob("*.md"))
        if specs:
            config = json.loads(config_path.read_text())
            config["spec"] = str(specs[-1].relative_to(project_root))
            config_path.write_text(json.dumps(config, indent=2))
            print(f"  Auto-discovered spec: {config['spec']}")

    _postinit_setup(project_root, install_assets=not minimal)
    print(f"  Created {config_path}")
    print("  Edit the spec path and verify_commands, then run: sw decompose")


def _shallow_merge(existing: dict, overlay: dict) -> dict:
    """v1.3.2 #5: shallow merge for `sw onboard --accept-existing merge`.

    Overlay's keys win for top-level keys present in both. For nested dicts
    (one level down — e.g., `validation`, `convergence`, `quality_gates`),
    overlay's sub-keys merge over existing sub-keys rather than replacing
    the entire block. Lists and scalars from overlay replace existing
    wholesale. Keys present only in `existing` are preserved.

    Intent: the user's hand-edited additions survive, while the onboard
    answers they just typed become the authoritative defaults.
    """
    out = dict(existing)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            sub = dict(out[k])
            sub.update(v)
            out[k] = sub
        else:
            out[k] = v
    return out


def _postinit_setup(project_root: Path, install_assets: bool = True) -> None:
    """v1.3.1 HIGH #3: shared post-init setup invoked by both `sw init` and
    `sw onboard` so onboard-created projects are not missing the gitignore
    safety net, project-local skills/commands, Stop hook, or registry entry.

    `install_assets=False` skips skill/command install + settings.local.json
    write (use for `--minimal` mode).
    """
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    # 1. Gitignore append (always, regardless of minimal)
    gitignore = project_root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    existing_lines = set(existing.splitlines())
    sw_new = [e for e in SW_GITIGNORE_ENTRIES if e not in existing_lines]
    py_new = [e for e in PYTHON_GITIGNORE_ENTRIES if e not in existing_lines]
    if sw_new or py_new:
        with open(gitignore, "a", encoding="utf-8") as f:
            if sw_new:
                f.write("\n# superpower-workflow runtime files\n")
                for e in sw_new:
                    f.write(f"{e}\n")
            if py_new:
                f.write("\n# Python standard ignores\n")
                for e in py_new:
                    f.write(f"{e}\n")
        print(f"  Added {len(sw_new) + len(py_new)} entries to .gitignore")

    # 2. Project-local skills/commands/settings (only when not minimal)
    if install_assets:
        _install_project_local(claude_dir)

    # 3. Register the project with the unified server (best-effort)
    try:
        from superpower_workflow.server.registry import ProjectRegistry

        reg = ProjectRegistry()
        reg.register(project_root.name, str(project_root))
    except Exception as e:
        # Server module may not be installed in the user's environment.
        # Emit a one-line stderr warning so failures aren't fully silent
        # (per v1.3.1 review: bare except: pass was a footgun).
        print(f"  (info: project registry not updated: {type(e).__name__})", file=sys.stderr)


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


def _resolve_telemetry_path(project_root: Path) -> Path | None:
    """v1.3.1 HIGH #1/#4 + v1.3.2 #3: resolve telemetry path safely.

    Thin wrapper that loads workflow.json from disk and delegates to the
    shared `paths.resolve_telemetry_path` helper. v1.3.2 introduced the
    shared helper so the orchestrator, dashboard, `sw metrics`, and
    `sw server sync` can all share the same path-traversal guard instead
    of duplicating the resolve+check logic.

    Returns None when the configured path escapes the project root; the
    caller must treat this as a hard error (skip + warn).
    """
    from superpower_workflow.paths import resolve_telemetry_path

    config: dict | None = None
    config_path = project_root / ".claude" / "workflow.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = None
    return resolve_telemetry_path(project_root, config)


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

    # v1.3.2 #5: previously `merge` and `replace` behaved identically — both
    # silently overwrote the existing workflow.json. The `merge` menu option
    # advertised in the docstring was never implemented, silently dropping
    # any user customizations (e.g., custom `_onboard` audit, hand-edited
    # `validation` tweaks, extra `quality_gates`). Now implement merge as a
    # shallow overlay: the new config's keys overlay the existing file's
    # keys, but unknown keys in the existing file are preserved.
    if choices.accept_existing == "merge":
        existing_path = project_root / ".claude" / "workflow.json"
        if existing_path.exists():
            try:
                existing = json.loads(existing_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    config = _shallow_merge(existing, config)
                    print(
                        "  Merging onboard answers onto existing workflow.json "
                        "(your hand-edited keys are preserved; onboard keys overlay)."
                    )
            except (json.JSONDecodeError, OSError):
                print(
                    "  WARNING: existing workflow.json unreadable; falling back to replace.",
                    file=sys.stderr,
                )

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
    # v1.3.1 HIGH #3: also run the shared post-init setup so onboard-created
    # projects get the gitignore safety net, project-local skills/commands/
    # Stop hook, and ProjectRegistry registration. Pre-fix, onboarded projects
    # were missing all of these.
    _postinit_setup(project_root, install_assets=True)
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
        print("  No model data -- run at least one milestone first.")
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

    # v1.3.2 #3: route through the central resolver instead of trusting the
    # raw config string. Returns None on traversal — treat as no telemetry.
    path = _resolve_telemetry_path(project_root)
    if path is None:
        print("  No telemetry data (configured path escapes project root).")
        return
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


def _cmd_drift(project_root: Path, args) -> None:
    """v1.3.19 — inspect drift baselines + recent drift events.

    Reads telemetry.jsonl + workflow.json. Pure read-only (except for
    --reset which clears state.drift_alerts_emitted_this_milestone).
    """
    from superpower_workflow.drift import (
        BASELINE_FLOOR_DEFAULT,
        METRIC_SPECS,
        compute_baseline,
        load_samples_batched,
    )

    claude_dir = project_root / ".claude"
    cfg_path = claude_dir / "workflow.json"
    if not cfg_path.exists():
        print(f"  No workflow.json at {cfg_path}; run `sw init` first.")
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  Failed to read workflow.json: {exc}")
        return

    drift_cfg = cfg.get("drift_detection", {})
    baseline_floor = int(drift_cfg.get("baseline_floor", BASELINE_FLOOR_DEFAULT))
    model_id = cfg.get("model", "")

    # --reset clears the in-milestone dedup so next phase can re-emit.
    if getattr(args, "reset", False):
        from superpower_workflow.state import load_state, save_state

        try:
            state = load_state(claude_dir)
            count_before = len(state.drift_alerts_emitted_this_milestone)
            state.drift_alerts_emitted_this_milestone = []
            save_state(claude_dir, state)
            print(f"  Cleared {count_before} drift-alert dedup entry(ies).")
        except Exception as exc:  # noqa: BLE001
            print(f"  Failed to reset drift state: {exc}")
        return

    telemetry_path = claude_dir / "sw-telemetry.jsonl"
    samples = load_samples_batched(
        telemetry_path,
        model_id_for_phase=model_id,
        model_id_for_milestone=model_id,
    )

    metric_filter = getattr(args, "metric", None)
    phase_filter = getattr(args, "phase", None)

    # Build the rows: one per (metric, bucket).
    rows: list[dict] = []
    for spec in METRIC_SPECS:
        if metric_filter and spec.key != metric_filter:
            continue
        for (mk, bucket), bucket_samples in samples.items():
            if mk != spec.key:
                continue
            if phase_filter and not bucket.startswith(phase_filter):
                continue
            baseline = compute_baseline(bucket_samples, spec)
            baseline.bucket = bucket
            disp_mean = (
                baseline.mean if not baseline.use_log else __import__("math").expm1(baseline.mean)
            )
            rows.append(
                {
                    "metric": spec.key,
                    "aggregation": spec.aggregation,
                    "bucket": bucket,
                    "n": baseline.n,
                    "mean": round(disp_mean, 4),
                    "sigma": round(baseline.stdev, 4),
                    "meets_floor": baseline.n >= baseline_floor,
                }
            )

    if getattr(args, "json", False):
        out = {
            "project_dir": str(project_root),
            "baseline_floor": baseline_floor,
            "model": model_id,
            "rows": rows,
        }
        print(json.dumps(out, indent=2))
        return

    # Human-readable text.
    if not rows:
        print(f"  No drift baselines yet for project {project_root}.")
        print(f"  (telemetry path: {telemetry_path})")
        return
    print(f"  drift baselines (baseline_floor={baseline_floor}, model={model_id})")
    print(f"  {'-' * 76}")
    print(f"  {'metric':22s} {'bucket':22s} {'n':>5s}  {'mean':>10s}  {'sigma':>10s}  floor?")
    for r in rows:
        ok = "✓" if r["meets_floor"] else "·"
        print(
            f"  {r['metric']:22s} {r['bucket']:22s} {r['n']:>5d}  "
            f"{r['mean']:>10.4f}  {r['sigma']:>10.4f}  {ok}"
        )
    n_total = len(rows)
    n_ok = sum(1 for r in rows if r["meets_floor"])
    print()
    print(f"  {n_ok}/{n_total} baselines have reached the {baseline_floor}-sample floor.")
    print(f"  Drift events for runs in this project: see {telemetry_path}")


def _ensure_ceiling_bypass_authorized() -> None:
    """v1.3.20 — defense-in-depth for `sw run --ignore-ceiling`.

    Exits 8 BEFORE any orchestrator work happens if the flag is not
    authorized via either:
    - `SW_ALLOW_CEILING_BYPASS=1` env var (cron-safe), or
    - interactive TTY `y` confirmation.

    Prevents cron scripts from normalizing the flag as a bypass.
    """
    from superpower_workflow.budget_ceiling import (
        EXIT_BYPASS_UNAUTHORIZED,
        is_bypass_authorized,
    )

    tty = sys.stdin.isatty()
    tty_confirm: bool | None = None
    if tty and os.environ.get("SW_ALLOW_CEILING_BYPASS") != "1":
        # v1.3.21 soak finding: in a non-interactive launch (eg `nohup python
        # -c ...` or a script piped from another process), sys.stdin can
        # claim to be a TTY but input() raises EOFError because nothing is
        # listening on the other end. Treat EOFError/KeyboardInterrupt as
        # explicit non-confirmation rather than crashing through to the
        # caller — exit 8 is the right exit either way.
        try:
            resp = (
                input("  --ignore-ceiling will bypass rolling cost ceilings. Proceed? [y/N]: ")
                .strip()
                .lower()
            )
            tty_confirm = resp == "y"
        except (EOFError, KeyboardInterrupt):
            tty_confirm = False
    authorized, reason = is_bypass_authorized(
        ignore_flag=True,
        env=dict(os.environ),
        stdin_is_tty=tty,
        tty_confirm=tty_confirm,
    )
    if not authorized:
        print(
            f"  FATAL: --ignore-ceiling requires SW_ALLOW_CEILING_BYPASS=1 "
            f"env var OR interactive TTY confirmation ({reason}).",
            file=sys.stderr,
        )
        sys.exit(EXIT_BYPASS_UNAUTHORIZED)


def _cmd_triage(project_root: Path, args) -> None:
    """v1.3.21 — `sw triage` replay over .claude/sw-telemetry.jsonl.

    Reads telemetry + audit + state, classifies each terminal failure
    anchor (MilestoneFailed, CostCeilingBlocked), and prints a human-
    readable table or JSON. Pure read-only.

    Exit codes:
      0  any output (including zero failures)
      2  telemetry file missing / unreadable
      3  --milestone specified but not found in classified results
    """
    if os.environ.get("SW_TRIAGE_OFF") == "1":
        print("  triage disabled via SW_TRIAGE_OFF=1")
        return

    from superpower_workflow.failure_triage import (
        classify_run,
        summarize,
        to_event_dict,
    )

    claude_dir = project_root / ".claude"
    telemetry_path = claude_dir / "sw-telemetry.jsonl"
    audit_path = claude_dir / "audit-trail.jsonl"
    state_path = claude_dir / "workflow-state.json"

    if not telemetry_path.exists():
        if getattr(args, "json", False):
            print(json.dumps({"failures": [], "summary": summarize([])}))
            return
        print(f"  No telemetry at {telemetry_path}.")
        sys.exit(2)

    cfg_path = claude_dir / "workflow.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            triage_cfg = cfg.get("triage", {})
            if not triage_cfg.get("enabled", True):
                print("  triage disabled -- set triage.enabled=true in workflow.json")
                return
        except (json.JSONDecodeError, OSError):
            pass  # CLI keeps running even if config malformed

    results = classify_run(
        telemetry_path,
        audit_path=audit_path if audit_path.exists() else None,
        state_path=state_path if state_path.exists() else None,
    )

    milestone_filter = getattr(args, "milestone", None)
    if milestone_filter:
        filtered = [r for r in results if r.milestone == milestone_filter]
        if not filtered:
            if getattr(args, "json", False):
                print(json.dumps({"failures": [], "summary": summarize([])}))
                return
            print(f"  No failure found for milestone '{milestone_filter}'.")
            sys.exit(3)
        results = filtered

    if getattr(args, "json", False):
        out = {
            "failures": [to_event_dict(r) for r in results],
            "summary": summarize(results),
            "triage_version": 1,
        }
        print(json.dumps(out, indent=2))
        return

    if not results:
        print("  No failures in this project's telemetry.")
        return

    summary = summarize(results)
    print(
        f"  triage results: {summary['total_failures']} failure(s), "
        f"{summary['unknown_count']} unknown "
        f"({summary['unknown_pct'] * 100:.1f}%), "
        f"p50 confidence={summary['p50_confidence']:.2f}"
    )
    print(f"  {'-' * 78}")
    print(f"  {'milestone':22s} {'phase':10s} {'class':30s} {'conf':>5s}")
    for r in results:
        cls_str = r.primary_class.value
        if r.secondary_classes:
            cls_str += f" (+{len(r.secondary_classes)})"
        print(
            f"  {r.milestone[:22]:22s} {r.phase[:10]:10s} {cls_str[:30]:30s} {r.confidence:>5.2f}"
        )

    if milestone_filter and len(results) == 1:
        # Deep view.
        r = results[0]
        print()
        print(f"  Primary: {r.primary_class.value}")
        if r.secondary_classes:
            print(f"  Secondary: {', '.join(r.secondary_classes)}")
        print(f"  Confidence: {r.confidence:.2f}")
        print(f"  Anchor: {r.anchor_type} (seq={r.anchor_seq})")
        print()
        print("  Evidence:")
        for e in r.evidence:
            print(f"    - {e}")
        print()
        print(f"  Recommendation:\n    {r.recommendation}")


def _cmd_budget(project_root: Path, args) -> None:
    """v1.3.20 — `sw budget {show,set,reset}` subcommand.

    Read-only inspection except `set` (writes workflow.json) and `reset`
    (writes a reset checkpoint + emits CEILING_RESET audit, never mutates
    telemetry.jsonl).
    """
    from superpower_workflow.budget_ceiling import (
        build_reset_audit_payload,
        evaluate_ceilings,
        parse_ceilings,
    )

    claude_dir = project_root / ".claude"
    cfg_path = claude_dir / "workflow.json"
    if not cfg_path.exists():
        print(f"  No workflow.json at {cfg_path}; run `sw init` first.")
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  Failed to read workflow.json: {exc}")
        return

    sub = getattr(args, "budget_command", None)

    if sub == "set":
        ceilings = cfg.setdefault("cost_ceilings", {})
        mode = getattr(args, "mode", "block")
        for key, val in (
            ("daily", args.daily),
            ("weekly", args.weekly),
            ("monthly", args.monthly),
        ):
            if val is None:
                continue
            if val <= 0:
                print(f"  Invalid {key} value: {val} (must be > 0). Skipped.")
                continue
            ceilings[key] = {"usd": float(val), "mode": mode}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"  Updated cost_ceilings in {cfg_path}.")
        return

    if sub == "reset":
        window = args.window
        if not args.confirm:
            print(
                f"  DRY-RUN: would clear {window} window. Re-run with --confirm to actually reset."
            )
            return
        ceilings_block = cfg.setdefault("cost_ceilings", {})
        checkpoints = ceilings_block.setdefault("reset_checkpoints", {})
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Capture prior spend BEFORE writing the checkpoint.
        model = cfg.get("model", "")
        telemetry_path = claude_dir / "sw-telemetry.jsonl"
        from superpower_workflow.budget_ceiling import load_window_spend

        prior = load_window_spend(
            telemetry_path,
            now_utc=__import__("datetime").datetime.now(__import__("datetime").UTC),
            window=window,
        )
        checkpoints[window] = now_iso
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        # Audit (if audit-trail enabled in config).
        from superpower_workflow.audit import AuditTrail, derive_key

        security = cfg.get("security", {})
        if security.get("audit_trail", False):
            key = derive_key()
            if key is not None:
                audit_path = claude_dir / "audit-trail.jsonl"
                trail = AuditTrail(audit_path, key=key)
                trail.append(
                    "CEILING_RESET",
                    data=build_reset_audit_payload(
                        window=window,
                        prior_spend_usd=prior.current_spend_usd,
                        cleared_at_utc=now_iso,
                    ),
                )
        print(
            f"  Reset {window} window. Prior spend ${prior.current_spend_usd:.2f} "
            f"cleared at {now_iso}. (Model: {model})"
        )
        return

    # Default: show.
    telemetry_path = claude_dir / "sw-telemetry.jsonl"
    ceilings = parse_ceilings(cfg.get("cost_ceilings"))
    if not ceilings.any_configured():
        if getattr(args, "json", False):
            print(json.dumps({"windows": [], "configured": False}, indent=2))
            return
        print("  No cost ceilings configured.")
        print("  Set one with: sw budget set --daily 50 --mode block")
        return

    # Use evaluate_ceilings with zero projected to avoid double-counting.
    result = evaluate_ceilings(
        telemetry_path,
        ceilings=ceilings,
        projected_run_cost_usd=0.0,
    )
    target_window = getattr(args, "window", "all")
    rows: list[dict] = []
    for ev in result.evaluations:
        if target_window != "all" and ev.window != target_window:
            continue
        if ev.ceiling_usd is None:
            continue
        rows.append(
            {
                "window": ev.window,
                "window_start_utc": ev.accounting.window_start_utc,
                "window_end_utc": ev.accounting.window_end_utc,
                "current_spend_usd": ev.accounting.current_spend_usd,
                "ceiling_usd": ev.ceiling_usd,
                "headroom_usd": ev.headroom_usd,
                "mode": ev.mode,
                "source": ev.accounting.source,
                "contributing_runs": [
                    {
                        "run_id": r.run_id,
                        "total_cost_usd": r.total_cost_usd,
                        "completed_at_utc": r.completed_at_utc,
                    }
                    for r in ev.accounting.contributing_runs
                ],
            }
        )

    if getattr(args, "json", False):
        print(json.dumps({"configured": True, "windows": rows}, indent=2))
        return

    print(f"  Cost ceilings (project={project_root.name}, telemetry={telemetry_path.name})")
    print(f"  {'-' * 74}")
    print(
        f"  {'window':6s} {'mode':6s} {'spend':>10s} / {'ceiling':>10s}   {'headroom':>10s}  runs"
    )
    for r in rows:
        runs_n = len(r["contributing_runs"])
        print(
            f"  {r['window']:6s} {r['mode']:6s} "
            f"${r['current_spend_usd']:>9.2f} / ${r['ceiling_usd']:>9.2f}   "
            f"${r['headroom_usd']:>9.2f}  {runs_n:>4d}"
        )
    if not rows:
        print("  (no ceilings match the filter)")


def _cmd_watch(project_root: Path, interval: float | None = None) -> None:
    from superpower_workflow.dashboard.data import DashboardData
    from superpower_workflow.dashboard.watch import make_watch

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
    # v1.3.17 / v1.1.9.1 — auto-select rich-based TUI when available;
    # fall back to text-mode TerminalWatch otherwise. Force text via
    # SW_WATCH_NO_RICH=1 for CI/non-TTY environments.
    watch = make_watch(data, interval=interval)
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
        # v1.3.6 #10: acquire the filelock before deleting the meta files.
        # Pre-fix, force-clean did three unlink() calls while a concurrent
        # `sw run` could be holding the filelock and writing the meta — the
        # unlinks would race the writer's atomic_write, producing torn
        # state on disk and an immediate ENOENT for the legitimate holder.
        from filelock import FileLock, Timeout

        from superpower_workflow.state import LOCK_FILE

        require_confirm = getattr(args, "yes", False) is not True
        if require_confirm:
            sys.stdout.write(
                "  This will forcibly remove the workflow lock even if a sw run is "
                "currently in progress. Are you SURE? [y/N]: "
            )
            sys.stdout.flush()
            answer = sys.stdin.readline().strip().lower()
            if not answer.startswith("y"):
                print("  Aborted.")
                return

        claude_dir.mkdir(parents=True, exist_ok=True)
        fl = FileLock(str(claude_dir / LOCK_FILE) + ".filelock", timeout=5)
        try:
            fl.acquire(blocking=True)
        except Timeout:
            print(
                "  WARNING: another sw process is actively holding the lock. "
                "Wait for it to finish, or kill its PID and retry."
            )
            return
        # Release the OS file handle BEFORE calling release_lock — on
        # Windows, release_lock unlinks the .filelock file, which fails
        # with PermissionError if we still hold the handle.
        fl.release()
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
    telemetry_path = _resolve_telemetry_path(project_root)
    if telemetry_path is not None and telemetry_path.exists():
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


def _emit_spec_lint_event(project_root: Path, report, run_id: str = "") -> None:
    """Emit a SpecLintCompleted event through the proper TelemetryEmitter.

    v1.3.1 HIGH #4 fix: pre-fix this wrote raw JSON directly to
    `.claude/telemetry.jsonl`, bypassing `TelemetryEmitter`/`TelemetryDbWriter`.
    The unified server's DB writer therefore never saw spec-lint events. Also
    hardcoded the path, ignoring `config.telemetry.path`.

    Now: resolve the path via `_resolve_telemetry_path` (path-traversal safe),
    construct a `SpecLintCompleted` dataclass, and emit through
    `TelemetryEmitter` which also feeds `TelemetryDbWriter` when configured.
    Respects `config.telemetry.enabled`.
    """
    claude_dir = project_root / ".claude"
    if not claude_dir.exists():
        return

    # Respect telemetry.enabled when set to false (per-project opt-out)
    config_path = claude_dir / "workflow.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if cfg.get("telemetry", {}).get("enabled", True) is False:
                return
        except (json.JSONDecodeError, OSError):
            pass

    telemetry_path = _resolve_telemetry_path(project_root)
    if telemetry_path is None:
        return  # Path traversal — already warned by the resolver

    from superpower_workflow.telemetry import SpecLintCompleted, TelemetryEmitter
    from superpower_workflow.validation.spec_linter import CheckState

    event = SpecLintCompleted(
        spec_path=report.spec_path,
        score=report.score,
        checks_passed=sum(1 for c in report.checks if c.state == CheckState.PASS),
        checks_warned=report.warning_count,
        checks_failed=report.blocker_count,
        blocker_count=report.blocker_count,
    )

    emitter = TelemetryEmitter(telemetry_path, run_id)
    try:
        emitter.emit(event)
    finally:
        emitter.close()


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
    _emit_spec_lint_event(project_root, report)

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
        _emit_spec_lint_event(project_root, report)

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


def _server_pid_belongs_to_sw(pid: int) -> bool:
    """v1.3.1 HIGH #2 + v1.3.2 #1: verify PID-file identity before SIGTERM.

    On long-running systems, PIDs are reused. A stale pid file from a prior
    boot would otherwise let `sw server stop` SIGTERM an unrelated process.

    The v1.3.1 predicate was too loose: it accepted any cmdline containing
    `superpower_workflow` (matches editors viewing sw source files, ANY
    sibling sw subcommand like `sw run`/`sw watch`, etc.) OR any cmdline
    whose tokens included the bare 2-char token `sw` (matches
    `bash -c sw`, `git sw`, npm aliases, etc.).

    v1.3.2 tightens to require BOTH:
      1. argv[0]'s basename is the `sw` entry-point or python interpreter
      2. a high-specificity server marker is present, EITHER:
         - `superpower_workflow.server` / `superpower_workflow/server` in argv
           (when launched as `python -m superpower_workflow.server.app`), OR
         - the cmdline contains both the `sw` entry-point name AND the
           `server` subcommand (when launched as `sw server run`).

    This eliminates false positives from:
      - editors / IDEs whose argv contains a sw source file path
      - other sw subcommands (sw run/watch/dashboard) — they lack `server`
      - random argv with token `sw`

    Returns False on every error (psutil missing, NoSuchProcess, AccessDenied,
    ZombieProcess) so the caller fails closed.
    """
    try:
        import psutil
    except ImportError:
        return False
    try:
        proc = psutil.Process(pid)
        argv = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    if not argv:
        return False
    # Cross-platform basename: Path(...).name on Linux doesn't recognize
    # backslash separators, so a Windows-style argv[0] read on Linux (e.g.
    # in CI cross-checks or test fixtures) would not split correctly.
    # Replace backslashes with forward slashes first, then split.
    head_name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    is_python = head_name.startswith("python") or head_name.startswith("py")
    is_sw_entry = head_name in {"sw", "sw.exe"}
    if not (is_python or is_sw_entry):
        return False
    # Marker 1: explicit `superpower_workflow.server` / `_workflow/server` token.
    has_server_module = any(
        ("superpower_workflow.server" in a) or ("superpower_workflow/server" in a) for a in argv
    )
    if has_server_module:
        return True
    # Marker 2: `sw server` subcommand wiring (argv[0] is sw entry, argv[1] is `server`).
    return is_sw_entry and len(argv) >= 2 and argv[1] == "server"


def _cmd_server_stop() -> None:
    pid_file = Path.home() / ".claude" / "sw-server.pid"
    if not pid_file.exists():
        print("  No server PID file found.")
        return
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        print("  PID file unreadable; removed.")
        return

    # v1.3.6 #1: capture the process' create_time INSIDE the predicate so
    # we can re-verify identity just before os.kill — closes the TOCTOU
    # window where the real server exits between the cmdline check and the
    # signal, allowing the OS to reuse the PID for an unrelated process.
    create_time = _server_pid_create_time(pid)
    if not _server_pid_belongs_to_sw(pid) or create_time is None:
        # Stale PID file from a prior boot, or PID has been reused.
        # Refuse to SIGTERM an unknown process; just clean up the file.
        pid_file.unlink(missing_ok=True)
        print(
            f"  PID {pid} does not appear to be a sw server (stale PID file or reused PID); "
            "removed PID file without sending SIGTERM."
        )
        return

    # Re-verify create_time just before the signal. If the original process
    # has exited and the kernel has handed the PID to another process, that
    # new process will have a DIFFERENT create_time and we refuse.
    if not _server_pid_create_time_matches(pid, create_time):
        pid_file.unlink(missing_ok=True)
        print(
            f"  PID {pid} create_time changed between check and signal "
            f"(original process exited, PID was reused). Removed PID file "
            "without sending SIGTERM."
        )
        return

    try:
        import signal as _signal

        os.kill(pid, _signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        print(f"  Stopped server (PID {pid})")
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        print("  Server not running.")


def _server_pid_create_time(pid: int) -> float | None:
    """v1.3.6 #1: snapshot the process create_time at predicate-check time
    so the caller can re-verify identity just before signaling. Returns
    None if psutil is missing or the process doesn't exist."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _server_pid_create_time_matches(pid: int, expected: float, tolerance: float = 1.0) -> bool:
    """v1.3.6 #1: True iff the process at `pid` still has the same
    create_time as when we last checked. Tolerance accommodates the small
    clock-skew window psutil reports on Windows."""
    actual = _server_pid_create_time(pid)
    if actual is None:
        return False
    return abs(actual - expected) <= tolerance


def _cmd_server_init_db(args) -> None:
    import os

    db_url = getattr(args, "database_url", None) or os.environ.get("SW_DATABASE_URL", "")
    if not db_url:
        print("  Error: Set SW_DATABASE_URL or use --database-url")
        return
    try:
        from superpower_workflow.db.engine import create_engine_from_url, ensure_schema_current
        from superpower_workflow.db.models import Base
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        return
    engine = create_engine_from_url(db_url)
    Base.metadata.create_all(engine)
    added = ensure_schema_current(engine)
    if added:
        print(f"  Schema migration: added {len(added)} column(s): {', '.join(added)}")
    print("  Database schema created.")


def _cmd_server_sync(project_root: Path, args) -> None:
    import os

    db_url = os.environ.get("SW_DATABASE_URL", "")
    if not db_url:
        print("  Error: Set SW_DATABASE_URL")
        return
    try:
        from superpower_workflow.db.engine import create_engine_from_url, ensure_schema_current
        from superpower_workflow.db.models import Base
        from superpower_workflow.db.sync_adapter import DbSyncAdapter
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        return
    engine = create_engine_from_url(db_url)
    Base.metadata.create_all(engine)
    ensure_schema_current(engine)
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
        # v1.3.2 #3: route through the central resolver so a malicious
        # `telemetry.path` cannot redirect the DB sync at arbitrary files.
        jsonl = _resolve_telemetry_path(project_root)
        if jsonl is None:
            print(f"  Skipped: {name} (configured telemetry path escapes project root)")
            return
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

        ignore_ceiling = bool(getattr(args, "ignore_ceiling", False))
        if ignore_ceiling:
            _ensure_ceiling_bypass_authorized()

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
            ignore_ceiling=ignore_ceiling,
        )
        return

    if args.command == "resume":
        _cmd_resume(project_root)
        return

    if args.command == "mcp-server":
        from superpower_workflow.mcp_server import main as mcp_main

        mcp_main()
        return

    if args.command == "drift":
        _cmd_drift(project_root, args)
        return

    if args.command == "budget":
        _cmd_budget(project_root, args)
        return

    if args.command == "triage":
        _cmd_triage(project_root, args)
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
