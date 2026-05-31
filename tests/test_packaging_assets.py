"""v1.3.2 #22: every named skill/command/hook the wheel-asset CI gate
enumerates MUST also be present on disk. This local mirror lets the test
fail before CI runs.

Whenever a new skill ships (e.g., a v1.3.3 addition), it MUST be added to
both lists here AND in .github/workflows/test.yml — they're the dual
guard against accidentally dropping an asset from a release.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Mirror of .github/workflows/test.yml "Verify assets in wheel" required list.
REQUIRED_SKILLS = [
    "ultrathink-gap-analysis",
    "post-impl-review",
    "production-readiness-review",
    "spec-quality-check",
    "code-quality-loop",
    "cost-investigator",
    "convergence-coach",
]
REQUIRED_COMMANDS = [
    "ultrathink",
    "sw-status",
    "sw-dry-run",
    "sw-curate",
    "sw-soak-summary",
]


class TestEverySkillIsPackagedAndDocumented:
    def test_every_required_skill_has_skill_md(self):
        for name in REQUIRED_SKILLS:
            skill_md = (
                ROOT / "src" / "superpower_workflow" / "_assets" / "skills" / name / "SKILL.md"
            )
            assert skill_md.exists(), (
                f"Skill {name} is in the CI wheel-asset gate but SKILL.md is "
                f"missing at {skill_md.relative_to(ROOT)}. Either restore it or "
                "remove it from .github/workflows/test.yml + this list."
            )

    def test_every_required_command_has_md(self):
        for name in REQUIRED_COMMANDS:
            cmd_md = ROOT / "src" / "superpower_workflow" / "_assets" / "commands" / f"{name}.md"
            assert cmd_md.exists(), (
                f"Slash command {name}.md is missing at {cmd_md.relative_to(ROOT)}."
            )

    def test_convergence_gate_hook_exists(self):
        hook = ROOT / "src" / "superpower_workflow" / "hooks" / "convergence_gate.py"
        assert hook.exists()

    def test_workflow_template_exists(self):
        tmpl = ROOT / "src" / "superpower_workflow" / "_assets" / "templates" / "workflow.json"
        assert tmpl.exists()


class TestCIWheelGateMentionsAllSkills:
    """If the workflow file's required list isn't in sync with REQUIRED_SKILLS
    above, the two guards have drifted — fail loudly so the maintainer
    updates both."""

    def test_workflow_yaml_includes_every_required_skill(self):
        yml = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        for name in REQUIRED_SKILLS:
            assert f"_assets/skills/{name}/SKILL.md" in yml, (
                f"CI wheel gate must pin skill `{name}` by exact SKILL.md path. "
                "Add it to .github/workflows/test.yml's required list."
            )

    def test_workflow_yaml_includes_every_required_command(self):
        yml = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        for name in REQUIRED_COMMANDS:
            assert f"_assets/commands/{name}.md" in yml, (
                f"CI wheel gate must pin command `{name}` by exact path."
            )
