from __future__ import annotations

import argparse
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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    project_root = Path.cwd()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "doctor":
        from superpower_workflow.doctor import run_checks

        results = run_checks(project_root)
        for r in results:
            status = "+" if r.ok else "x"
            print(f"  {status} {r.message}")
        sys.exit(0 if all(r.ok for r in results) else 1)

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
        )
        return

    print(f"Command '{args.command}' not yet implemented.")
