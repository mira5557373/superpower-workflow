# superpower-workflow

[![Tests](https://img.shields.io/badge/tests-779%2B%20passing-brightgreen)](https://github.com/mira5557373/superpower-workflow)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-blue)](CHANGELOG.md)

**Automated post-brainstorming development lifecycle for Claude Code.**

After you've designed something (e.g., via `superpowers:brainstorming`), `sw` drives the entire build: spec → milestone decomposition → TDD implementation → ultrathink reviews → push.

Proven on 35 milestones across multiple real projects, with code-enforced gap validation, spec-compliance verification, and feature-verification testing built in.

---

## Table of Contents

- [What sw does](#what-sw-does)
- [Why it exists](#why-it-exists)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Commands](#commands)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Trust-but-verify](#trust-but-verify)
- [Lock & resume](#lock--resume)
- [Unified dashboard (optional)](#unified-dashboard-optional)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## What sw does

For each milestone in your spec, `sw run` executes four phases inside a self-correcting loop:

| Phase | Purpose | Convergence loop |
|---|---|---|
| **A — Plan** | Writes a detailed implementation plan with file edits, tests, and risk analysis. | Plan is fed to ultrathink-gap-analysis (≥20 gaps) until convergence. |
| **B — Implement** | Writes code TDD-style (red → green → refactor). | Runs lint, tests, coverage, SAST, dep scan. |
| **C — Review + Fix** | Post-implementation review across functional/security/perf/quality dimensions. | Loops with fixes until reviewer reports zero blockers. |
| **D — Push** | Commits with conventional message and pushes to the remote. | Single pass. |

Between phases, `sw` runs **gap validation** (code-enforced), **spec compliance** (independent claude pass), and **feature verification** (independent claude pass) so AI-reported "done" is checked against reality.

## Why it exists

Three pain points:

1. **Ad-hoc TDD loops break down.** Without orchestration, agents drift from the plan, skip tests, or call something "done" when half the spec is missing.
2. **AI self-review hallucinates.** A reviewer that reads its own code is too easily convinced. `sw` runs independent verification passes that cross-check claims against `ruff`, `pytest`, `pip-audit`, and `git diff`.
3. **Long-running development needs resilience.** `sw` survives terminal restarts, crashed runs, hung claude calls, PID reuse, and stale locks — and resumes from the right phase via git-log analysis.

---

## Installation

### Base install (everything except the unified dashboard server)

```bash
pip install superpower-workflow
```

or from source:

```bash
git clone https://github.com/mira5557373/superpower-workflow.git
cd superpower-workflow
pip install -e .
```

### With the unified dashboard server

```bash
pip install "superpower-workflow[server]"
```

This adds `sqlalchemy`, `alembic`, `fastapi`, `uvicorn`, and `psycopg2-binary`.

### Requirements

- Python 3.11+
- [Claude Code](https://claude.com/claude-code) CLI on PATH (`claude --version` must work)
- Git
- Optional: Docker + Docker Compose (for the unified dashboard)

---

## Quickstart

```bash
# 1. Inside the project you want to build:
cd /path/to/your-project
sw init                          # creates .claude/workflow.json + per-project skills

# 2. Health check:
sw doctor                        # verifies claude, git, lint/test commands

# 3. Break the spec into milestones:
sw decompose docs/spec.md        # writes .claude/milestones.json

# 4. (Optional) Cost/duration estimate:
sw estimate

# 5. Run it:
sw run                           # full pipeline — Plan → Implement → Review → Push, per milestone

# 6. Watch progress in another terminal:
sw status                        # one-shot snapshot
sw watch                         # live TUI
sw dashboard                     # single-project web dashboard on :3000
```

---

## Commands

### Core lifecycle

| Command | Purpose |
|---|---|
| `sw init` | Create `.claude/workflow.json` and install per-project skills + slash commands. |
| `sw doctor` | Pre-flight health checks (claude CLI, git, lint/test commands, disk, perms). |
| `sw decompose <spec>` | Two-pass spec → milestone breakdown (writes `.claude/milestones.json`). |
| `sw estimate` | Cost/duration estimate using historical telemetry when available. |
| `sw run [--from M] [--only M]` | Execute milestones with full Plan/Implement/Review/Push loop. |
| `sw status` | Show current run state, phase, retries, and progress. |
| `sw resume` | Resume from last failure point (git-log aware smart resume). |
| `sw clean` | Remove all runtime files (state, lock, gap reports, telemetry). |

### Observability

| Command | Purpose |
|---|---|
| `sw watch` | Live terminal TUI of the current run. |
| `sw dashboard [--port 3000]` | Single-project web dashboard. |
| `sw metrics` | Show cost/duration/retry telemetry summary. |
| `sw audit` | Inspect tamper-evident HMAC audit chain. |

### Lock management

| Command | Purpose |
|---|---|
| `sw lock status` | Show lock holder (PID, host, heartbeat age, stale flag). |
| `sw lock force-clean` | Release the lock when auto-recovery can't. |

### Project setup & maintenance

| Command | Purpose |
|---|---|
| `sw bootstrap` | One-command setup (devcontainer, CI, hooks, CLAUDE.md, docs). |
| `sw upgrade` | Detect outdated deps with AI-assisted migration plan. |
| `sw plugin add/list/remove` | Manage workflow plugins via setuptools entry points. |

### Unified server (optional `[server]` extra)

| Command | Purpose |
|---|---|
| `sw server init-db` | Apply schema migrations. |
| `sw server sync [--all]` | Import existing JSONL telemetry into Postgres. |
| `sw server start [--host --port]` | Start FastAPI + WebSocket on :3001. |
| `sw server stop` | Graceful shutdown via PID file. |

Run `sw <command> --help` for full options.

---

## Configuration

`sw init` writes `.claude/workflow.json`:

```jsonc
{
  "project_name": "your-project",
  "spec_path": "docs/spec.md",
  "verify_commands": {
    "lint":     "ruff check . && ruff format --check .",
    "test":     null,                          // set when you have tests
    "coverage": null,
    "sast":     null,
    "dep_scan": null
  },
  "budget": {
    "per_milestone_usd": 25.0,
    "global_usd": 250.0,
    "wall_seconds": 14400
  },
  "convergence": {
    "max_ultrathink_passes": 3,
    "max_review_passes": 3
  },
  "resilience": {
    "max_retries": 3,
    "max_milestone_retries": 2,
    "skip_and_continue_after": 5,
    "circuit_breaker_failures": 3
  },
  "trust_but_verify": {
    "gap_validator":         { "enabled": true },
    "spec_compliance":       { "enabled": true },
    "feature_verification":  { "enabled": true }
  },
  "database": {                                // optional, only with [server]
    "url_env": "SW_DATABASE_URL"               // never put the URL here directly
  },
  "docs": { "readme": { "enabled": true } }
}
```

**Secrets stay out of config files** — only env-var references are allowed.

---

## Architecture

```
sw run
  └─ Orchestrator (orchestrator.py)
       ├─ Preflight: lock, git clean, doctor
       ├─ For each milestone:
       │    ├─ Phase A — Plan          (claude -p, ultrathink convergence loop)
       │    ├─ Gap Validator           (code-enforced verification of plan gaps)
       │    ├─ Phase B — Implement     (claude -p, runs lint/test/coverage/SAST)
       │    ├─ Spec Compliance Check   (independent claude -p pass)
       │    ├─ Feature Verification    (independent claude -p pass, runs feature tests)
       │    ├─ Phase C — Review + Fix  (claude -p, loops on blockers)
       │    └─ Phase D — Push          (claude -p, conventional commit + push)
       ├─ Heartbeat updater (per-milestone, ~10min stale threshold)
       ├─ Resilience: retry / milestone-retry / skip+continue / circuit breaker
       └─ Telemetry (JSONL flat-file always; Postgres optional)

hooks/
  └─ convergence_gate.py — Stop hook (exit 2 to block stop and force another pass)
```

Subprocess orchestration of `claude -p` — `sw` is not itself an LLM agent. It's a deterministic Python controller that drives Claude Code with carefully scoped prompts, then verifies the result.

---

## Trust-but-verify

Three independent verifiers cross-check AI claims:

| Verifier | What it checks | How |
|---|---|---|
| **Gap Validator** | Every gap an ultrathink pass reports actually points at real files/lines/symbols. | Code-enforced: walks the gap report, opens the file, greps for the symbol. Three states: valid / invalid / unverifiable. |
| **Spec Compliance Checker** | Every requirement in the spec is implemented in code. | Fresh `claude -p` session with no implementation context. Reports missing features to Phase C. |
| **Feature Verification Tester** | Spec features actually *work* (not just exist). | Fresh `claude -p` session that runs verification tests/probes against the implementation. |

These run between phases. Anything they flag is fed back into Phase C as actionable context — not a rubber stamp.

---

## Lock & resume

`sw` survives interrupted runs:

- **Atomic lock** — `filelock` (`O_EXCL`) for race-free acquisition.
- **Composite identity** — PID + process `start_time` + hostname. Detects PID reuse after terminal restart.
- **Heartbeat** — orchestrator pings every milestone iteration. Locks older than 10 minutes are considered hung and reclaimed automatically.
- **Hostname check** — locks held by another machine (e.g., NFS-shared `.claude/` dirs) are respected.
- **`sw resume`** — reads `git log` since the run started, infers the last successful phase, and picks up there. Phase B crashes are recovered via diff analysis.
- **Escape hatch** — if all automation fails, `sw lock force-clean` releases the lock immediately.

```bash
sw lock status
# active  pid=24851  host=dev-box  heartbeat 32s ago  not stale
```

---

## Unified dashboard (optional)

For multi-project visibility, install the `[server]` extra and run a Postgres-backed dashboard.

```bash
pip install "superpower-workflow[server]"
docker compose -f docker/docker-compose.yml up -d   # postgres + api-server
export SW_DATABASE_URL="postgresql://sw:sw@localhost:5432/sw"
export SW_API_KEY="<generate-a-key>"
sw server init-db
sw server sync --all                                 # import existing JSONL
sw server start                                      # http://localhost:3001
```

Features:
- Cross-project overview, drill-down per project
- Real-time updates via WebSocket
- Run comparison, event search, model analytics
- REST API at `/api/v1/*` (Bearer-auth, rate-limited, paginated)
- Health check at `/api/v1/health`
- `sw run` continues to dual-write JSONL + Postgres; the dashboard is non-blocking infrastructure.

---

## Examples

### Run a single milestone

```bash
sw run --only M3
```

### Re-run from the middle after a crash

```bash
sw resume
# Or explicitly:
sw run --from M2
```

### Run from a GitHub issue

```bash
sw run --from-issue 42
```

### Force-clean a stuck lock (last resort)

```bash
sw lock status        # confirm it's actually stale
sw lock force-clean
sw resume
```

### Inspect telemetry

```bash
sw metrics                              # rollup
sw dashboard --port 3000                # single-project web UI
sw audit --verify                       # check HMAC audit chain integrity
```

---

## Troubleshooting

**"Workflow lock held by another process"**
Run `sw lock status`. If the listed PID is gone or heartbeat is >10 min old, `sw` would normally reclaim it on the next run. If it doesn't, `sw lock force-clean`.

**"claude command not found"**
`sw` shells out to `claude -p`. Install [Claude Code](https://claude.com/claude-code) and ensure `claude --version` works.

**"verify command 'lint' failed" during preflight**
Your `verify_commands.lint` produced errors before the run started. Fix lint errors first, or set the verify command to `null` if not applicable.

**Phase B crashed and resume can't find the last commit**
`sw resume` uses git log since the run started. If you've manually committed, set `--from <milestone>` explicitly.

**Tests fail with `ModuleNotFoundError: psutil`**
`pip install -e .` to pick up the new runtime deps (`filelock`, `psutil`) added in 1.1.0.

---

## Contributing

```bash
git clone https://github.com/mira5557373/superpower-workflow.git
cd superpower-workflow
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
```

779+ tests. Conventional commits. PRs welcome.

---

## License

MIT. See [LICENSE](LICENSE).

## Links

- [CHANGELOG](CHANGELOG.md)
- [Issue tracker](https://github.com/mira5557373/superpower-workflow/issues)
- [Design spec](docs/superpowers/specs/2026-05-22-superpower-workflow-design.md)
