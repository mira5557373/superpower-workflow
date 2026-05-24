#!/usr/bin/env python3
"""Add SP2-SP7 milestones to workflow.json and launch sw run."""
import json
from pathlib import Path

config_path = Path(".claude/workflow.json")
config = json.loads(config_path.read_text())

new_milestones = [
    {
        "name": "sp2-telemetry",
        "spec_sections": "all",
        "description": "Structured JSONL telemetry, quality trends, rework rate, cost-per-task, sw analytics command.",
        "depends_on": ["sp1-quality-gates"],
        "budget_override": None,
    },
    {
        "name": "sp3-dashboard",
        "spec_sections": "all",
        "description": "Web dashboard (localhost:3000, SSE), terminal TUI (sw watch), optional Prometheus metrics.",
        "depends_on": ["sp2-telemetry"],
        "budget_override": None,
    },
    {
        "name": "sp4-security",
        "spec_sections": "all",
        "description": "HMAC audit trail, CycloneDX SBOM, Ed25519 signing, secrets broker, policy engine.",
        "depends_on": ["sp1-quality-gates"],
        "budget_override": None,
    },
    {
        "name": "sp5-integrations",
        "spec_sections": "all",
        "description": "GitHub Issues, Linear/Jira, CI self-correction, Slack notifications, PR auto-creation.",
        "depends_on": ["sp2-telemetry"],
        "budget_override": None,
    },
    {
        "name": "sp6-parallel",
        "spec_sections": "all",
        "description": "Git worktree isolation, multi-model routing, best-of-N, remote SSH execution, Agent Teams.",
        "depends_on": ["sp1-quality-gates"],
        "budget_override": None,
    },
    {
        "name": "sp7-docs-dx-plugins",
        "spec_sections": "all",
        "description": "Auto README/CHANGELOG/API docs/diagrams, sw bootstrap, sw upgrade, plugin system with entry points.",
        "depends_on": ["sp2-telemetry", "sp4-security", "sp5-integrations", "sp6-parallel"],
        "budget_override": None,
    },
]

# Update spec to point to roadmap (covers all SPs)
config["spec"] = "docs/superpowers/specs/roadmap.md"

# Add new milestones (keep SP1 for dependency resolution)
existing_names = {m["name"] for m in config["milestones"]}
for ms in new_milestones:
    if ms["name"] not in existing_names:
        config["milestones"].append(ms)

config_path.write_text(json.dumps(config, indent=2))
print(f"Added {len(new_milestones)} milestones. Total: {len(config['milestones'])}")
print("Milestones:")
for ms in config["milestones"]:
    print(f"  - {ms['name']}")
