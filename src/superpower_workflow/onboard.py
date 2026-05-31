"""Interactive `sw onboard` wizard for first-time setup (T1.9.5).

Walks a new user through the most common config decisions:
 1. Detect project type (uses project_detect from v1.1.8)
 2. Choose model (opus/sonnet/haiku)
 3. Set budgets based on size (rough estimate)
 4. Toggle trust-but-verify features (defaults from A/B soak data)
 5. Set up CI integration
 6. Run `sw lint-spec` against the chosen spec

Idempotent (per G1.9.6): detects existing workflow.json and offers
merge/replace/abort. Writes only when user confirms.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_MODELS = ["opus", "sonnet", "haiku"]
SIZE_PRESETS = {
    "small": {"plan": 3, "implement": 8, "review": 4, "push": 1, "max_total_budget_usd": 50},
    "medium": {"plan": 8, "implement": 25, "review": 10, "push": 1, "max_total_budget_usd": 250},
    "large": {"plan": 25, "implement": 100, "review": 40, "push": 3, "max_total_budget_usd": 1000},
}


@dataclass
class OnboardConfig:
    """Choices captured during onboarding. Used to construct workflow.json."""

    spec_path: str = ""
    model: str = "opus"
    fallback_model: str = "haiku"
    project_type: str = "generic"
    size_preset: str = "medium"
    enable_gap_curator: bool = True
    enable_strict_mode: bool = False
    enable_spec_linter: bool = True
    enable_quality_gates: bool = True
    enable_ci_integration: bool = False
    accept_existing: str = "abort"  # "abort" | "replace" | "merge"
    summary_only: bool = False


def _ask(prompt: str, default: str = "", choices: list[str] | None = None) -> str:
    if choices:
        hint = f" [{'/'.join(choices)}]"
    elif default:
        hint = f" [{default}]"
    else:
        hint = ""
    sys.stdout.write(f"  {prompt}{hint}: ")
    sys.stdout.flush()
    answer = sys.stdin.readline().strip()
    if not answer:
        return default
    if choices and answer not in choices:
        return default
    return answer


def _ask_yn(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    sys.stdout.write(f"  {prompt} [{default_str}]: ")
    sys.stdout.flush()
    answer = sys.stdin.readline().strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


def detect_existing_specs(project_root: Path) -> list[Path]:
    """Find candidate spec.md files. Looks in docs/superpowers/specs/ first, then root."""
    candidates: list[Path] = []
    sp_dir = project_root / "docs" / "superpowers" / "specs"
    if sp_dir.exists():
        candidates.extend(sorted(sp_dir.glob("*.md")))
    candidates.extend(sorted(project_root.glob("spec*.md")))
    candidates.extend(sorted(project_root.glob("SPEC*.md")))
    # Dedupe while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def run_onboard(project_root: Path, interactive: bool = True) -> OnboardConfig:
    """Run the onboarding wizard. When interactive=False, returns defaults
    without prompting (useful for tests). The caller writes workflow.json."""
    from superpower_workflow.project_detect import detect

    cfg = OnboardConfig()

    profile = detect(project_root)
    cfg.project_type = profile.primary_language

    # v1.3.1 — failed validation fix: existing-workflow detection MUST run
    # before the non-interactive early-return. Pre-fix, `_cmd_onboard` aborted
    # in non-interactive mode because the default `accept_existing="abort"`
    # was never cleared. New convention: empty sentinel means "no decision
    # needed", "abort"/"replace"/"merge" are explicit user choices.
    existing_path = project_root / ".claude" / "workflow.json"
    existing_present = existing_path.exists()

    if not interactive:
        # In non-interactive (smoke-test) mode: if a workflow.json already
        # exists, we MUST NOT overwrite silently — fail closed.
        cfg.accept_existing = "abort" if existing_present else ""
        # Also auto-pick a spec when not provided interactively, so downstream
        # commands don't get an empty spec_path.
        if not cfg.spec_path:
            specs = detect_existing_specs(project_root)
            cfg.spec_path = str(specs[0].relative_to(project_root)) if specs else "spec.md"
        return cfg

    print()
    print("  Welcome to superpower-workflow onboarding.")
    print("  This wizard sets up .claude/workflow.json for your project.")
    print(f"  Project root: {project_root}")
    if profile.languages:
        print(f"  Detected language(s): {', '.join(profile.languages)}")
    print()

    if existing_present:
        print("  Existing workflow.json detected.")
        action = _ask(
            "  How to handle?",
            default="abort",
            choices=["abort", "replace", "merge"],
        )
        cfg.accept_existing = action
        if action == "abort":
            return cfg

    specs = detect_existing_specs(project_root)
    if specs:
        print("  Found spec(s):")
        for i, s in enumerate(specs, 1):
            rel = s.relative_to(project_root)
            print(f"    {i}. {rel}")
        choice = _ask(
            "  Choose a spec (number or path)",
            default=str(specs[0].relative_to(project_root)),
        )
        try:
            n = int(choice)
            cfg.spec_path = str(specs[n - 1].relative_to(project_root))
        except (ValueError, IndexError):
            cfg.spec_path = choice
    else:
        cfg.spec_path = _ask(
            "Path to your spec.md (relative to project root)",
            default="spec.md",
        )

    cfg.model = _ask("Primary model", default="opus", choices=DEFAULT_MODELS)
    cfg.size_preset = _ask(
        "Project size",
        default="medium",
        choices=list(SIZE_PRESETS.keys()),
    )
    cfg.enable_gap_curator = _ask_yn(
        "Enable gap_curator (recommended — soak shows 33% cost reduction)",
        default=True,
    )
    cfg.enable_strict_mode = _ask_yn(
        "Enable strict_mode (re-loops Phase C on residual missing/broken)",
        default=False,
    )
    cfg.enable_spec_linter = _ask_yn(
        "Enable spec_linter (auto-runs during sw decompose)",
        default=True,
    )
    cfg.enable_quality_gates = _ask_yn(
        f"Pre-populate quality_gates for {cfg.project_type}?",
        default=True,
    )
    cfg.enable_ci_integration = _ask_yn(
        "Enable GitHub CI integration (sw monitors PR checks)",
        default=False,
    )
    return cfg


def build_workflow_config(project_root: Path, choices: OnboardConfig) -> dict:
    """Compose the workflow.json dict from onboard choices.

    v1.3.3 #7: routes through the shared `default_workflow_config` so
    onboard automatically inherits every top-level key init writes. Pre-fix
    onboard emitted 15 keys vs init's 27, and the 12 missing
    (dashboard/database/parallel/plugins/policies/secrets/security/server/
    model_routing/docs/git_strategy/notification_webhook/delay_between_phases_seconds)
    silently fell back to orchestrator hardcoded defaults.
    """
    from superpower_workflow.cli import default_workflow_config
    from superpower_workflow.project_detect import detect

    profile = detect(project_root)
    size = SIZE_PRESETS[choices.size_preset]

    # Start from the shared default. Then layer onboard's user choices on top.
    config = default_workflow_config(
        profile=profile,
        with_quality_gates=choices.enable_quality_gates,
        minimal=False,
    )

    # Apply onboard's user-choice overrides
    config["spec"] = choices.spec_path
    config["model"] = choices.model
    config["fallback_model"] = choices.fallback_model
    config["budgets"] = {
        "plan": size["plan"],
        "implement": size["implement"],
        "review": size["review"],
        "push": size["push"],
    }
    config["max_total_budget_usd"] = size["max_total_budget_usd"]
    # Toggle validation flags from user choices (other validation keys
    # already populated by default_workflow_config).
    config["validation"]["gap_curator"] = choices.enable_gap_curator
    config["validation"]["strict_mode"] = choices.enable_strict_mode
    config["validation"]["spec_linter"] = choices.enable_spec_linter
    # CI integration toggle
    config["integrations"]["ci"]["enabled"] = choices.enable_ci_integration
    # Capture the onboard choices for audit
    config["_onboard"] = asdict(choices)
    return config


def write_config(project_root: Path, config: dict) -> Path:
    """Atomic write of workflow.json. Returns the path."""
    import os

    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    path = claude_dir / "workflow.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return path
