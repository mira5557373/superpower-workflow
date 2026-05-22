# superpower-workflow

Automated post-brainstorming development lifecycle for Claude Code.

After `superpowers:brainstorming` produces a spec, `sw` handles everything:
milestone decomposition → plan writing → TDD implementation → ultrathink review loops → push.

## Quick Start

```bash
pip install -e .
python install.py

cd /path/to/your-project
sw init
sw decompose
sw estimate
sw run
```

## Documentation

See `docs/superpowers/specs/2026-05-22-superpower-workflow-design.md` for the full design spec.
