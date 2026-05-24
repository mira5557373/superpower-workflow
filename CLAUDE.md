# superpower-workflow — Project Instructions

## What this project is

CLI tool (`sw`) that automates post-brainstorming development lifecycle for Claude Code. Drives `claude -p` per phase per milestone. 90 tests, proven on 35 milestones ($665, zero failures).

## Module map

```
src/superpower_workflow/
  cli.py              — sw command routing (init, doctor, decompose, estimate, run, status, resume)
  orchestrator.py     — Core milestone loop, pre-flight checks, 4-layer resilience
  runner.py           — claude -p subprocess wrapper (retry 30s/2min/5min, JSON parse, timeout)
  state.py            — WorkflowState/PhaseState dataclasses, atomic JSON I/O, lockfile
  prompts.py          — Phase A/B/C/D prompt templates
  context.py          — Git-based milestone context (module paths, exports, test counts)
  decomposer.py       — Two-pass spec → milestone decomposition
  estimator.py        — Cost/duration estimates
  doctor.py           — Pre-flight health checks
  logger.py           — Structured file logging [timestamp] EVENT key=value
  hooks/
    convergence_gate.py — Stop hook: exit 0 (allow stop) or exit 2 (block stop)

skills/
  ultrathink-gap-analysis/SKILL.md + references/heuristics.md
  post-impl-review/SKILL.md
  production-readiness-review/SKILL.md

commands/ultrathink.md
templates/workflow.json
install.py
```

## Conventions

- Python 3.11+, hatchling build
- `from __future__ import annotations` in every source file
- Atomic JSON writes via `_atomic_write()` (write to .tmp, os.replace)
- Hook returns only 0 or 2
- Prompts under 500 words
- Mock `subprocess.run` in tests — never call real `claude -p`
- All subprocess calls use `timeout` parameter
- ruff for lint + format (E, F, I, B, UP, SIM rules)
- pytest for tests, conventional commits

## Existing implementation plan

The SP1 plan is at `docs/superpowers/plans/2026-05-24-sp1-quality-gates.md`. It has 9 tasks with full code. Follow it.
