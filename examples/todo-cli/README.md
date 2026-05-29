# Example: todo-cli

A minimal example showing the end-to-end superpower-workflow loop on a tiny project.

## What you get

- One spec file (`spec.md`) describing a CLI todo app
- The expected milestone decomposition (`expected-milestones.json`)
- A sample dry-run trace (`dry-run-output.txt`)

## Run it yourself

```bash
cd examples/todo-cli/project
git init && git commit --allow-empty -m "init"
sw init
# Edit .claude/workflow.json: set spec_path = "../spec.md"
sw decompose ../spec.md
sw run --dry-run        # preview plan + cost forecast (no LLM spend)
sw run                  # full execution (~$10-25, 4 milestones)
```

## What this demonstrates

1. **Decomposition** — a 1-paragraph spec → 4 concrete milestones
2. **Dry-run** — exact plan and forecast before any LLM spend
3. **Trust-but-verify** — gap validator runs between phases
4. **Conventional commits** — each milestone produces one signed commit

The full execution typically converges within 1 ultrathink pass per milestone
because the spec is intentionally small and unambiguous.
