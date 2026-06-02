# Architecture (v1.4.0)

This is the one-page mental model of `superpower-workflow`. After reading it
you should be able to answer: what runs when, where state lives, and how the
five telemetry features compose.

## The big picture

`sw` is a deterministic Python orchestrator around `claude -p`. It reads a
spec, decomposes it into milestones, and drives each milestone through a fixed
phase pipeline. Each phase invokes Claude as a fresh subprocess with a curated
prompt; nothing about the phase pipeline is stateful inside Claude.

State lives in `.claude/`:

- `sw-telemetry.jsonl` — append-only event log, single source of truth for
  every observability feature
- `workflow-state.json` — mutable run state (current milestone, completed
  list, accumulated cost, breaker window)
- `workflow.json` — declarative config (milestones, budgets, model, feature
  toggles)
- `audit-trail.jsonl` — optional HMAC-chained audit log
- `workflow-complete.json` — terminal summary written once a run finishes

The orchestrator is the only writer of any of these files (with a per-file
threading lock + optional file lock). Every CLI subcommand that mutates state
goes through the same atomic-write code path.

## The phase pipeline

A milestone walks **four core phases** plus **two optional phases**:

| Phase | Class | Purpose | Telemetry emitted |
|---|---|---|---|
| A — Plan | `PhaseA` | Generate an implementation plan (file edits, tests, risks) | `PhaseStarted` / `PhaseCompleted` |
| B — Implement | `PhaseB` | Write code TDD-style; run lint + tests + coverage + SAST | same |
| TbV — Trust-but-Verify | `PhaseTbV` | Optional: spec-compliance + feature-verification independent passes | `SpecComplianceCompleted`, `FeatureVerificationCompleted` |
| C — Review | `PhaseC` | Post-impl review; loops with strict-mode fixes until clean | `GapReport`, `StrictModeIteration` |
| D — Push | `PhaseD` | Conventional commit + push (or worktree merge in parallel mode) | `WorktreeMerged` (parallel only) |
| E — CI Fix | `PhaseE` | Optional: watch CI, auto-fix on failure | runs only if CI integration configured |

`orchestrator.py:_run_milestone` walks these in order. Each `claude -p` call
goes through `runner.run_claude` which handles retry (delays 30s/2m/5m),
timeout (default 2h), and parses JSON output for cost + session id.

Between phases the orchestrator may run code-enforced **gap validation** and
emit `GapValidationEvent` — this is local Python code over the gap-report
artifact, not another Claude call.

A milestone retry loop (`max_retries=3`, delays 120/300/600s) wraps the whole
A→E sequence. The class-aware Circuit Breaker (v1.3.26) decides whether the
NEXT milestone runs; the retry loop decides whether THIS milestone retries.
The two layers are independent.

## The five telemetry features

All five read `.claude/sw-telemetry.jsonl`. None mutate each other's data.
Each has a kill switch.

### 1. Drift Detector (v1.3.19)

**Question:** Is this run abnormal compared to the project's own baseline?

**How:** Rolling baseline of 5 metrics computed per `(phase, model_id)` bucket
for per-phase metrics (cost_usd, duration_ms, cache_hit_rate) and per
`(model_id)` bucket for per-milestone metrics (gap_attrition_pct,
strict_iterations). Cost and duration use log1p transforms (heavy-tailed
distributions). Sigma floor at 5% of mean prevents zero-variance blowups.

Emits `DriftDetected` when |z-score| crosses 2σ (INFO), 3σ (WARN), or 4σ
(CRITICAL). INFO suppressed under `observation_only` mode (default).

**Configuration:** `drift_detection.{enabled, mode, baseline_floor,
sample_cap, emit_info}`. Default `baseline_floor=15` — no events fire below
that sample count per bucket.

**Source:** `src/superpower_workflow/drift.py`. CLI: `sw drift`.

### 2. Cost Ceilings (v1.3.20)

**Question:** Did we exceed a rolling cross-run budget envelope?

**How:** Reads `RunCompleted` events from telemetry, sums `total_cost_usd`
over three rolling windows ending now-UTC: **24h** (day), **7d** (week),
**30d** (month). Evaluated at **three preflight gates**: `run_start`,
`milestone_start`, and `phase_e_retry`. Each evaluation emits one
`CostCeilingEvaluated` event per configured window, stamped with the gate.

`mode=warn` emits telemetry and continues. `mode=block` emits
`CostCeilingBlocked`, records `CEILING_BLOCK` in the audit, and exits 7.

Concurrency: a separate `.claude/.ceiling.lock` held only for the
evaluate→decide→emit window. Stale locks (>30s) auto-reclaim. Sample loading
is single-pass over the JSONL.

**Configuration:** `cost_ceilings.{daily, weekly, monthly}` each with
`{usd, mode}`. Bypass: `sw run --ignore-ceiling` requires
`SW_ALLOW_CEILING_BYPASS=1` env var or interactive TTY confirmation.

**Distinct from BudgetAlert** (v1.3.17), which is WITHIN-run percent-of-cap
crossings on `max_total_budget_usd`. Both fire independently when both
conditions trip.

**Source:** `src/superpower_workflow/budget_ceiling.py`. CLI: `sw budget`.

### 3. Failure Triage (v1.3.21)

**Question:** Why did this milestone fail?

**How:** Pure-functional rule-only classifier. 13 numbered rules walked in
priority order; first match wins primary class. Secondary classes are
later-seq matches not in the `IMPLIES` subsumption graph (e.g.,
POLICY_VIOLATION subsumes QUALITY_GATE_FAIL). 14th class `UNKNOWN` is the
fallback at confidence 0.4.

Anchors on `MilestoneFailed`, `CostCeilingBlocked`. The `FailureClass` enum
has **14 values** + the `DRIFT_CORRELATED` secondary-only tag.

Rules read **typed events where possible** to avoid regex-on-free-text
fragility. The orchestrator emits a typed `ClaudeInvocationFailed`
(`error_kind ∈ {timeout, is_error, nonzero_exit, mcp_crash, auth, unknown}`)
which rules 08/09 consume instead of grepping `MilestoneFailed.reason`.

Hooked into the orchestrator post-`MilestoneFailed` emit. Best-effort —
classification failure never breaks the run loop.

**Source:** `src/superpower_workflow/failure_triage.py`,
`src/superpower_workflow/hooks/triage_hook.py`. CLI: `sw triage`.

### 4. Calibration Loop (v1.3.24)

**Question:** What will the next run cost on this model?

**How:** Reads `MilestoneCompleted` events with `model_id` from telemetry,
partitions by canonical model id (`_model_key.canonicalize`), and produces
per-model bands. Three tiers based on per-model sample count:

- **`cold_start`** (n=0): published `DEFAULT_TABLE` prior
- **`partial`** (1 ≤ n < 5): blend of table + telemetry, small-n widened
- **`warm`** (n ≥ 5): pure log1p-EWMA + percentiles

Emits one `EstimateCalibrated` per `status=complete` run with
`(predicted, actual, error_ratio)`. Failed/cancelled runs are excluded so the
error_ratio reflects successful-run distribution only.

Math is shared with the Drift Detector via `_stats.py` (log1p_ewma +
log1p_percentiles + small_n_widen). Cross-module consistency is asserted by
a dedicated test.

**Configuration:** mostly automatic. Kill switch:
`SW_CALIBRATION_DISABLE=1`. CLI overrides: `sw estimate --legacy`.

**Source:** `src/superpower_workflow/calibration.py`,
`src/superpower_workflow/_stats.py`, `src/superpower_workflow/_model_key.py`.
CLI: `sw estimate`, `sw estimate --calibration`, `sw estimate --json`.

### 5. Circuit Breaker (v1.3.26)

**Question:** Should the next milestone even run?

**How:** Class-aware accumulator that consumes `FailureTriaged` events.
**Two trip rules:**

1. **same_class_repeat** — N back-to-back failures of the same `FailureClass`,
   where the `FailureClass.value` of the most recent N entries in
   `state.breaker_window` all match. Deterministic classes default to N=2;
   transient classes default to N=3. UNKNOWN is excluded.
2. **diversity_overflow** — the last 5 entries in the rolling window contain
   ≥3 failures regardless of class. This is the legacy 3-in-5 safety net
   preserved as a backstop when same-class rule doesn't fire.

Low-confidence triage (`confidence < 0.7`) breaks the same-class chain (low
confidence is ambiguous; don't penalize uncertain data).

Ships **`observation_only=true` by default** — emits
`CircuitBreakerWouldTrip` events against real runs WITHOUT aborting. The
legacy 3-strike `consecutive_failures >= 3` fallback remains as a final
safety net when triage is disabled. After N=10 same-class trips observed in
production, the v1.x design plan is to flip `observation_only=false` to make
the breaker enforce.

Tripped (enforced mode) → `CircuitBreakerTripped` → exit code 10.

**Source:** `src/superpower_workflow/circuit_breaker.py`. CLI: `sw breaker`.

## Data model

| File | Writer | Format | Lifetime |
|---|---|---|---|
| `sw-telemetry.jsonl` | orchestrator (`TelemetryEmitter`) | append-only JSONL, one event per line | run-long; never deleted by `sw clean` |
| `workflow-state.json` | orchestrator + CLI mutators | atomic-write JSON | full lifetime; resume reads it |
| `workflow.json` | `sw init`, `sw decompose`, `sw budget set`, `sw breaker reset`, human edits | atomic-write JSON | full lifetime |
| `audit-trail.jsonl` | `AuditTrail.append` (opt-in via `security.audit_trail=true`) | HMAC-SHA256 hash-chained JSONL | full lifetime; verified by `sw audit verify` |
| `workflow-complete.json` | orchestrator end-of-run | atomic-write JSON | rewritten at each run completion |
| `.claude/.workflow.lock` | `state.acquire_lock` | identity + heartbeat | run-long; cleared by lock release |
| `.claude/.ceiling.lock` | `budget_ceiling.CeilingLock` | timestamp | preflight evaluation only |

**Telemetry events are additive.** New event types ship in releases without
removing or renaming prior ones; consumers ignore unknown types. State schema
bumps include default values for backward-compat reads (see
[`docs/migration.md`](migration.md)).

**`workflow-complete.json` status values:** `complete` (all attempted
milestones succeeded), `partial` (some succeeded, others failed but resume
is possible), or `failed` (preflight fatal or all-milestones failed).

## Configuration

`workflow.json` top-level fields (excerpt):

| Field | Default | Notes |
|---|---|---|
| `spec` | required | path to spec.md |
| `model` | required | canonical or alias; canonicalized at read by `_model_key` |
| `fallback_model` | none | used by runner on retry |
| `max_total_budget_usd` | required | per-run cap; triggers `BudgetAlert` |
| `budgets.{plan, implement, review, push}` | required | per-phase caps |
| `verify_commands.{test, lint, format, ...}` | optional | shell commands run as quality gates |
| `drift_detection.{enabled, mode, baseline_floor, sample_cap, emit_info}` | `{true, observation_only, 15, 200, false}` | drift config |
| `cost_ceilings.{daily, weekly, monthly}` | none | each `{usd, mode}` |
| `triage.{enabled}` | `{true}` | classifier toggle |
| `circuit_breaker.{enabled, observation_only, diversity_window, diversity_threshold, confidence_floor, same_class_thresholds}` | sensible defaults | breaker config |
| `security.audit_trail` | `false` | enable HMAC-chained audit |

Model aliases: `haiku` → `haiku-4-5`, `sonnet` → `sonnet-4-5`,
`opus` → `opus-4-7`. Canonicalization happens at read by
`_model_key.canonicalize`; telemetry always records the canonical form.

### Kill switches (env vars)

| Variable | Effect |
|---|---|
| `SW_DRIFT_DISABLE=1` | skip drift assessment |
| `SW_DISABLE_COST_CEILINGS=1` | short-circuit ceiling preflight |
| `SW_TRIAGE_OFF=1` | skip triage hook + CLI |
| `SW_CALIBRATION_DISABLE=1` | skip calibration emit + render |
| `SW_ALLOW_CEILING_BYPASS=1` | authorize `--ignore-ceiling` flag |
| `SW_AUDIT_KEY` | HMAC key for audit chain |
| `SW_DATABASE_URL` | optional Postgres for server-mode telemetry |

The circuit breaker has no env-var kill switch; flip
`circuit_breaker.enabled` in `workflow.json` instead.

## Module map

| Module | Responsibility |
|---|---|
| `src/superpower_workflow/orchestrator.py` | Driver loop, milestone retry, phase wiring, telemetry emit |
| `src/superpower_workflow/runner.py` | `claude -p` subprocess wrapper, retry, JSON parse, child-process-group SIGTERM safety |
| `src/superpower_workflow/state.py` | `WorkflowState` dataclass, atomic JSON I/O, lock |
| `src/superpower_workflow/phases/` | `PhaseA/B/C/D/E` + `PhaseTbV` classes |
| `src/superpower_workflow/cli.py` | argparse setup + all `_cmd_*` dispatch helpers |
| `src/superpower_workflow/telemetry.py` | `TelemetryEvent` base + 40+ event types + `TelemetryEmitter` + `TelemetryReader` |
| `src/superpower_workflow/audit.py` | HMAC-chained `AuditTrail` + `verify` |
| `src/superpower_workflow/drift.py` | Drift Detector (v1.3.19) |
| `src/superpower_workflow/budget_ceiling.py` | Cost Ceilings (v1.3.20) |
| `src/superpower_workflow/failure_triage.py` | Failure Triage (v1.3.21) |
| `src/superpower_workflow/calibration.py` | Calibration Loop (v1.3.24) |
| `src/superpower_workflow/circuit_breaker.py` | Classed Circuit Breaker (v1.3.26) |
| `src/superpower_workflow/_stats.py`, `_model_key.py` | Shared math + canonicalization (v1.3.24) |
| `src/superpower_workflow/parallel/` | Worktree-isolated parallel-mode executor |
| `src/superpower_workflow/dashboard/`, `server/` | Optional FastAPI + WebSocket dashboard |
| `src/superpower_workflow/mcp_server.py` | Optional MCP server exposing `sw_*` tools |
| `src/superpower_workflow/hooks/` | Claude Code hooks + orchestrator-side triage hook |

## What sw does NOT do

These are explicit guardrails encoded in code or policy:

- **Does not modify application source code under test.** The agent edits
  files only within the project's working tree per the milestone plan; it
  does not reach into installed dependencies or the host system.
- **Does not commit secrets.** The `SecretsHandler` redacts known patterns
  from logs and telemetry; conventional commits go through `pre-commit`
  hooks when configured.
- **Does not egress to non-allowlisted domains** when `NetworkPolicy` is
  configured.
- **`sw clean` does not delete `audit-trail.jsonl`.** Audit history is
  preserved across cleans by design.

## Concurrency model

Single-process orchestrator with these locks:

- `.claude/.workflow.lock` — per-project orchestration lock; heartbeat-based
  staleness detection at `state.HEARTBEAT_STALE_SECONDS=600`
- `.claude/.ceiling.lock` — preflight evaluation lock; stale at 30s
- per-`Path` threading lock on JSON writes (`state._get_path_lock`)
- threading.Lock inside `TelemetryEmitter.emit` and `AuditTrail.append` to
  serialize concurrent parallel-worker writes

Parallel mode (worktree-isolated, `sw run --parallel`) spawns worker threads
inside a single Python process. Each worker runs inside its own git worktree;
file locks remain in the project's `.claude/`. The triage and drift hooks
short-circuit inside parallel workers (the `_in_parallel_worker` flag) for
v1.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic failure |
| 2 | CLI argument or telemetry-missing error |
| 3 | `sw triage --milestone NAME` not found / unknown `FailureClass` for `--explain` |
| 7 | Cost ceiling enforced (v1.3.20) |
| 8 | `--ignore-ceiling` used without authorization (v1.3.20) |
| 10 | Circuit breaker tripped in enforced mode (v1.3.26) |
