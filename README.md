# superpower-workflow

[![Status](https://img.shields.io/badge/status-feature--complete-brightgreen)](CHANGELOG.md)
[![Version](https://img.shields.io/badge/version-1.4.0-blue)](CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-1953%20passing-brightgreen)](#)
[![Distribution](https://img.shields.io/badge/distribution-internal--only-lightgrey)](#honest-scope--what-sw-is-not)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

A Python CLI (`sw`) that orchestrates `claude -p` subprocesses to drive a software
project from spec to pushed commits through verifiable Plan / Implement / Review /
Push phases — with cost ceilings, drift detection, failure triage, calibration,
and a class-aware circuit breaker built in.

---

## Status

**v1.4.0 — feature-complete, API frozen for the 1.x line.** 1953 tests passing.
Distributed internally only (no PyPI). Five telemetry features finished in the
1.3.x series; 1.4.0 is the stabilization release.

No new public surface is planned for 1.x. Bug fixes and security patches will
continue on the 1.x branch; behavioral changes belong to 2.x.

---

## Why sw exists

Claude Code on its own is a capable interactive assistant. It is not, on its
own, a development lifecycle.

`sw` is the deterministic Python controller around `claude -p` that turns a
spec into committed code without a human babysitting every prompt. Specifically,
`sw` provides what Claude Code alone does not:

- **Milestone decomposition.** A spec is split into milestones with explicit
  acceptance criteria, so each `claude -p` call has a tightly scoped goal
  instead of an open-ended chat.
- **Four-phase per-milestone loop.** Plan → Implement → Review → Push, with
  an optional Phase E (CI Fix) when CI is wired. Each phase is a fresh
  `claude -p` invocation with a curated prompt — not a long-running
  conversation that drifts.
- **Convergence loops with hard caps.** Gap-analysis on plans, post-impl
  review on code — both bounded by configurable max iterations so they
  cannot loop forever.
- **Trust-but-verify.** Independent `claude -p` passes plus code-enforced
  checks cross-check AI claims against `ruff`, `pytest`, `pip-audit`, and
  `git diff`. Self-reported "done" is verified against reality.
- **Resilience.** Atomic file locks with PID + start-time + hostname identity,
  heartbeat-based stale detection, automatic retry, class-aware circuit
  breaker, and git-log-aware resume across crashes, terminal restarts, and
  hung claude calls.
- **Telemetry that informs decisions.** JSONL flat-file always; cost
  ceilings, drift detection, failure triage, calibration, and circuit
  breaker built in (see below).

In short: `sw` is what you wrap around Claude Code when you need a 35-milestone,
multi-week build to finish without you watching it.

---

## Quick start

```bash
pip install -e ./superpower-workflow   # internal install path
cd /path/to/your-project
sw init                                # writes .claude/workflow.json + skills
sw doctor                              # verifies claude, git, lint/test commands
sw lint-spec docs/spec.md              # optional: spec quality gate
sw decompose                           # writes milestones into workflow.json
sw estimate                            # cost band forecast (per-model calibrated)
sw run                                 # full pipeline, all milestones
sw status                              # snapshot in another terminal
sw watch                               # live TUI
```

Resume after a crash: `sw resume`. Force-clean a stuck lock: `sw lock force-clean`.

---

## The five telemetry features (1.3.x)

All five ship enabled by default, write to `.claude/sw-telemetry.jsonl`, and
respect existing budget/convergence config. Each has a per-feature env-var
kill switch.

| Feature | What it asks | How it works | Default mode |
|---|---|---|---|
| **Drift Detector** (v1.3.19) | Is this run abnormal vs baseline? | Sigma-band z-score over 5 metrics per (phase, model_id) bucket; log1p for cost/duration. Emits `DriftDetected` at 2σ/3σ/4σ. | `observation_only` (INFO suppressed); `baseline_floor=15` |
| **Cost Ceilings** (v1.3.20) | Did we exceed a rolling-window budget? | Reads `RunCompleted` events across runs, sums `total_cost_usd` over rolling 24h / 7d / 30d windows. Evaluated at run-start / milestone-start / phase-E-retry preflight gates. | `warn` mode emits telemetry; `block` mode exits 7 |
| **Failure Triage** (v1.3.21) | Why did this milestone fail? | Rule-only classifier — 14 `FailureClass` values + `UNKNOWN`. Anchors on `MilestoneFailed`. Pure-function, deterministic, zero LLM cost. | Always-on; consumed by circuit breaker |
| **Calibration Loop** (v1.3.24) | What will the next run cost? | Per-model bands (p10/p50/p90) from `MilestoneCompleted` events. Three tiers: `cold_start` (n=0), `partial` (1 ≤ n < 5), `warm` (n ≥ 5). Log1p EWMA. | Always-on; `SW_CALIBRATION_DISABLE=1` opts out |
| **Circuit Breaker** (v1.3.26) | Should the next milestone even run? | Per-`FailureClass` thresholds (deterministic=2, transient=3) + diversity overflow (3 failures in last 5 milestones regardless of class) over `state.breaker_window`. | `observation_only=true` — emits `CircuitBreakerWouldTrip` without aborting until you flip the config |

Inspect any feature on the corpus: `sw drift`, `sw budget show`, `sw triage`,
`sw breaker status`. Replay/explain: `sw triage --reclassify`,
`sw triage --explain <CLASS>`, `sw triage --health`. Reset:
`sw budget reset --window day --confirm`, `sw breaker reset --confirm`.

Telemetry rollup: `sw metrics`. Audit chain integrity: `sw audit verify`.

---

## CLI surface

Top-level commands (all support `--help`):

- **Lifecycle:** `init`, `doctor`, `lint-spec`, `decompose`, `estimate`,
  `run`, `status`, `resume`, `clean`
- **Telemetry inspection:** `drift`, `budget`, `triage`, `breaker`, `metrics`
- **Observability:** `watch`, `dashboard`, `mcp-server`, `audit verify`
- **Lock management:** `lock status`, `lock force-clean`
- **Project setup:** `bootstrap`, `upgrade`, `plugin add/list/remove`,
  `onboard`, `recommend-model`, `migrate-gitignore`
- **Optional server (`[server]` extra):** `server start/sync`

`sw run` flags worth knowing: `--dry-run`, `--milestone NAME`, `--from MS`,
`--to MS`, `--from-issue N`, `--parallel`, `--best-of-n N`,
`--ignore-ceiling` (requires `SW_ALLOW_CEILING_BYPASS=1`).

---

## Honest scope — what sw is NOT

`sw` is internal tooling that does a few things well. It is not:

- **On PyPI.** Distribution is git+ssh, wheel, or submodule. There is no
  `pip install superpower-workflow` from a public index in the 1.x line.
- **A multi-tenant SaaS.** Single-project optimized. The optional `[server]`
  extra adds a Postgres-backed dashboard for cross-project visibility on
  your own infrastructure, but there is no hosted version.
- **A replacement for Claude Code.** `sw` invokes `claude -p`. If the
  Claude Code CLI isn't installed and on PATH, `sw` does nothing.
- **A general-purpose CI runner.** It runs `ruff`, `pytest`, `pip-audit`,
  etc. via your `verify_commands` config — it does not replace CI.
- **Framework-agnostic out of the box.** Heuristics and prompts assume
  Python projects with ruff + pytest. Other stacks work but require
  `verify_commands` rewrites and possibly skill-asset changes.
- **An autonomous coding agent without supervision.** The trust-but-verify
  layer + circuit breaker exist precisely because LLMs need
  cross-checking. You should still read the diffs before merging.
- **Stable across major versions.** 1.x is frozen; 2.x may break things.
  Pin to a tag.

---

## Production track record

`sw` built `e2e_agent` end-to-end:

- **35 milestones** across phases P1 / P2 / P3 / P4
- **$665.44 total Claude API spend**
- **Zero failed runs** that required manual rescue beyond `sw resume`
- **1953 tests** in `sw` itself, all passing on the v1.4.0 release commit

This is not a synthetic benchmark. `e2e_agent` is a real Python library with a
published spec, ~10 sub-packages, and integration test suites at each phase
boundary. Every commit on its main branch was produced by `sw run` and reviewed
by the trust-but-verify pipeline before push.

Four soak archives under `soak-archive/` document the v1.3.x feature
validations on `examples/todo-cli`. Three real production bugs were caught and
fixed by those soaks (regression tests added for each).

---

## Documentation

| Doc | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Orchestrator design, phase lifecycle, how the 5 telemetry features compose |
| [`docs/cookbook.md`](docs/cookbook.md) | Recipes: set up a new project, recover a failed run, swap models, etc. |
| [`docs/migration.md`](docs/migration.md) | Schema bumps, exit-code additions, forward/backward-compat guarantees |
| [`docs/budget-ceilings.md`](docs/budget-ceilings.md) | Rolling-window cost ceiling reference (v1.3.20) |
| [`docs/calibration.md`](docs/calibration.md) | Per-model calibration reference (v1.3.24) |
| [`docs/failure-triage.md`](docs/failure-triage.md) | Failure classification taxonomy (v1.3.21) |
| [`CHANGELOG.md`](CHANGELOG.md) | Per-release detail across all 1.x releases |

For a one-page understanding of the runtime, start with `architecture.md`. For
"how do I do X", start with `cookbook.md`.

---

## License & author

MIT (see [`LICENSE`](LICENSE)). Authored and maintained for internal use;
external pull requests are not currently accepted, but issues filed by internal
consumers are welcome. Contact the maintainer through the parent project
(`e2e_agent`) for access, support, or to request a 2.x scoping conversation.
