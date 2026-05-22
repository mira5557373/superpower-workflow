from __future__ import annotations

import argparse
import json
import shutil
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

    run_p = sub.add_parser("run", help="Execute milestones")
    run_p.add_argument("--milestone", help="Run a specific milestone")
    run_p.add_argument("--from", dest="from_ms", help="Start from milestone")
    run_p.add_argument("--to", dest="to_ms", help="End at milestone")
    run_p.add_argument("--phase", help="Run milestones matching phase prefix")
    run_p.add_argument("--dry-run", action="store_true", help="Preview without executing")

    return parser


def _cmd_init(project_root: Path) -> None:
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config_path = claude_dir / "workflow.json"
    if config_path.exists():
        print(f"  workflow.json already exists at {config_path}")
        return

    template_dir = Path(__file__).resolve().parent.parent.parent / "templates"
    template = template_dir / "workflow.json"
    if template.exists():
        shutil.copy2(template, config_path)
    else:
        config_path.write_text(
            json.dumps({"schema_version": 1, "spec": "", "milestones": []}, indent=2)
        )

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
        spec_path=spec_path, model=config.get("model", "opus"), cwd=str(project_root)
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

    if args.command == "doctor":
        from superpower_workflow.doctor import run_checks

        results = run_checks(project_root)
        for r in results:
            status = "+" if r.ok else "x"
            print(f"  {status} {r.message}")
        sys.exit(0 if all(r.ok for r in results) else 1)

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
        )
        return

    if args.command == "resume":
        _cmd_resume(project_root)
        return
