# sw Cookbook (v1.4.0)

Recipe-style guide to common `sw` workflows. Each recipe is grouped as
**Goal → Steps → Verify → Pitfalls**.

For background on what runs when, see [`architecture.md`](architecture.md).
For schema/exit-code changes between releases, see [`migration.md`](migration.md).

---

## 1. Set up sw on a fresh project

**Goal:** From an empty git repo with a spec, get to "`sw run` is the next
command I should type."

**Steps:**
```bash
cd /path/to/your-project           # must be a git repo (sw verifies)
sw init                            # writes .claude/workflow.json + skills
sw doctor                          # verifies claude, git, lint/test commands
sw lint-spec docs/spec.md          # scores spec quality 0-100
sw decompose                       # spec → milestones, writes back to workflow.json
sw estimate                        # banded cost + duration forecast
```

Edit `.claude/workflow.json` to set `model`, `budgets`, and
`verify_commands.{test, lint}` to your project's commands.

**Verify:**
- `sw status` shows 0 completed milestones, current_step is empty
- `sw doctor` returns exit 0 with all checks `+`
- `.claude/workflow.json` has `milestones: [...]` (non-empty)

**Pitfalls:**
- `sw run` aborts immediately with `FATAL: Uncommitted changes detected.`
  Commit or stash anything `git status` shows before running.
- `verify_commands.test` failing in preflight aborts the run before any
  claude call. Either fix the failing test command or remove the gate.
- `sw lint-spec` blockers prevent `sw decompose`. Use `sw decompose --force`
  only when you've reviewed the warnings.

---

## 2. Read what just happened

**Goal:** After a run completes (or fails), get a quick picture.

**Steps:**
```bash
sw status                          # completed/failed/skipped + total cost
sw metrics                         # per-phase + per-model breakdown
sw triage                          # classify every failure with evidence
sw drift                           # per-bucket baselines + recent assessments
sw budget show                     # rolling-window spend + headroom
sw breaker status                  # rolling failure window + counter
```

**Verify:**
- `sw triage` output ends with "No failures" if every milestone passed,
  otherwise prints per-failure class + confidence + evidence chain
- `sw drift --baseline --json` lists buckets with `n` (sample count) and
  `meets_floor` flag

**Pitfalls:**
- `sw triage` exits 2 if `.claude/sw-telemetry.jsonl` is missing. This is
  expected on a fresh project.
- `sw drift` defaults `baseline_floor=15`. On a small project (one or two
  runs) you'll see `meets_floor: false` everywhere — that's correct.

---

## 3. Recover from a failed milestone

**Goal:** A milestone failed; recover without losing prior milestone work.

**Steps:**
```bash
sw status                          # confirm which milestone failed
sw triage --milestone NAME         # deep view with full evidence chain
                                   # fix the underlying issue per the recommendation
sw resume                          # picks up from state.current_milestone_index
```

If state appears corrupt or you want to re-run cleanly from a specific
milestone:
```bash
sw run --milestone NAME            # run JUST this milestone
sw run --from NAME                 # run from this milestone forward
```

**Verify:**
- `sw status` after resume shows the previously-failed milestone in
  `completed` (or `failed` again with a different reason)
- `.claude/sw-telemetry.jsonl` has a new `RunStarted` event with a fresh
  `run_id`

**Pitfalls:**
- `sw clean` deletes `workflow-state.json` and `sw-telemetry.jsonl` but
  **NOT** `audit-trail.jsonl`. Use sparingly — you lose calibration data.
- A stuck `.claude/.workflow.lock` survives crashes; use
  `sw lock force-clean` if a `sw resume` reports "Another orchestration
  is running" and `ps` shows no live process.

---

## 4. Switch models mid-project

**Goal:** Change `model` in `workflow.json` from haiku to opus (or vice versa)
without losing the calibration history.

**Steps:**
```bash
# Inspect current calibration before swap
sw estimate --calibration

# Edit .claude/workflow.json: change "model": "claude-opus-4-7"
sw estimate --calibration          # shows new model's cold-start prior

sw run --milestone NAME            # runs the next milestone on opus
sw drift                           # opus samples land in their own bucket
```

**Verify:**
- After 1+ opus milestone, `sw estimate --calibration` shows a separate
  `opus-4-7` row with `tier=partial` (1 sample) — independent of the haiku bucket
- `sw drift --baseline --json` confirms `(phase, opus-4-7)` buckets exist
  alongside `(phase, haiku-4-5)` buckets

**Pitfalls:**
- Pre-v1.3.24 `MilestoneCompleted` events have no `model_id` and are
  SKIPPED by calibration (not pooled into a phantom "unknown" bucket).
  This is correct behavior; expect a log line stating skip count.
- Drift baselines do not transfer across models — each model's bucket
  builds from scratch.
- If you set `fallback_model`, runner retries fall to that model. Telemetry
  records the model that ACTUALLY ran each phase.

---

## 5. Set up rolling cost ceilings

**Goal:** Cap total claude spend across runs (day/week/month) so an
overnight retry storm cannot drain the team budget.

**Steps:**
```bash
sw budget set --daily 25 --weekly 100 --monthly 350 --mode warn
sw budget show                     # verify current rolling spend vs ceiling
sw run                             # CostCeilingEvaluated events emit at 3 gates
```

Once you trust the warn-mode signal, flip the mode to block:
```bash
sw budget set --daily 25 --mode block
```

To override a block-mode ceiling for one run (audit-logged):
```bash
SW_ALLOW_CEILING_BYPASS=1 sw run --ignore-ceiling
```

**Verify:**
- `sw budget show --json` reports `current_spend_usd`, `headroom_usd`,
  `source` (`telemetry` | `partial_history` | `no_history`)
- After a `block`-mode run that would exceed the ceiling: exit 7,
  `CostCeilingBlocked` event in telemetry, `CEILING_BLOCK` entry in audit
- `sw audit verify` returns "Audit trail OK" with the new entries

**Pitfalls:**
- Bare `sw run --ignore-ceiling` (no env var, no TTY) exits 8 — by design.
- Ceilings read `RunCompleted` events only. Mid-run spend doesn't count
  until the run completes (use `max_total_budget_usd` for intra-run cap).
- `sw budget reset --window day --confirm` writes a checkpoint that
  excludes earlier events; it does NOT delete telemetry.

---

## 6. Inspect the Circuit Breaker

**Goal:** See whether the breaker is about to trip + understand its state.

**Steps:**
```bash
sw breaker status                  # window + per-class counter + TRIP/ok flag
sw breaker status --json           # machine-readable, includes thresholds
```

Reset after a deliberate intervention:
```bash
sw breaker reset                   # DRY-RUN — prints what would change
sw breaker reset --confirm         # actually clears + emits CIRCUIT_BREAKER_RESET audit
```

**Verify:**
- On a fresh install: `Circuit Breaker: enabled=true mode=observation_only`,
  empty window, no failures
- After failures: per-class counter rows show `n / threshold` with `TRIP` or
  `ok` flag. In observation-only mode, even when classes show `TRIP`, the
  run continues but `CircuitBreakerWouldTrip` events are emitted.

**Pitfalls:**
- Default mode is **`observation_only=true`**. The breaker won't actually
  abort; it emits `CircuitBreakerWouldTrip` events for telemetry analysis.
  Flip `circuit_breaker.observation_only=false` in `workflow.json` only
  after observing the trip rules behave as expected in your project.
- Low-confidence triage results (confidence < 0.7) do NOT advance the
  same-class counter — the chain is broken by uncertainty.
- The legacy class-blind `consecutive_failures >= 3` fallback remains as
  a safety net when triage is disabled (`SW_TRIAGE_OFF=1`).

---

## 7. Use `sw triage --reclassify` when rules evolve

**Goal:** When `failure_triage.RULES` gains a new rule, find out what
historical failures would have classified differently.

**Steps:**
```bash
sw triage --reclassify             # writes .claude/.triage-replay.jsonl
sw triage --reclassify --json      # machine-readable count + sidecar path
```

Compare the sidecar against the live telemetry's `FailureTriaged` events to
spot reclassifications. The live telemetry is NEVER mutated.

**Verify:**
- `.claude/.triage-replay.jsonl` exists after the command
- Number of replayed events matches `MilestoneFailed` count
- Replayed `primary_class` values reflect the CURRENT rule set

**Pitfalls:**
- The sidecar is overwritten each time. Move it elsewhere if you need a
  historical snapshot.
- `--reclassify` does not retroactively change anything the orchestrator
  acted on (e.g., a circuit-breaker decision from a prior run stands).

---

## 8. Explain a `FailureClass` or check triage health

**Goal:** Understand WHY a class fires + monitor classifier quality.

**Steps:**
```bash
sw triage --explain quality_gate_fail
sw triage --explain policy_violation --json
sw triage --health                  # UNKNOWN rate over last 30 failures
```

**Verify:**
- `--explain` prints the rule id, recommendation, and IMPLIES subsumption
  list. Unknown class → exit 3 with valid options listed.
- `--health` reports OK (UNKNOWN ≤ 15%) or DEGRADED (above), plus per-class
  distribution. Degraded → inspect raw_reason fields in recent
  `FailureTriaged` events to identify pattern.

**Pitfalls:**
- `FailureClass` values are lowercase (matching enum `.value`):
  `quality_gate_fail`, NOT `QUALITY_GATE_FAIL`. The CLI does not currently
  case-fold.

---

## 9. Verify audit trail integrity

**Goal:** Cryptographically confirm the audit chain hasn't been tampered with.

**Steps:**
```bash
# Audit must be enabled at run start. Set in workflow.json:
#   "security": {"audit_trail": true}
# AND set the HMAC key:
export SW_AUDIT_KEY="some-strong-secret-32-plus-chars"
sw run                              # entries hash-chain into audit-trail.jsonl
sw audit verify                     # walks the chain
```

**Verify:**
- Output: `Audit trail OK. N entries verified.` (where N matches the line
  count of `audit-trail.jsonl`)
- Exit 0

**Pitfalls:**
- `sw audit verify` on a missing or empty `audit-trail.jsonl` returns exit
  0 with `No audit trail found.` This is NOT cryptographic attestation —
  to require a real chain, assert exit 0 AND that stdout starts with
  `Audit trail OK.`
- Without `SW_AUDIT_KEY` set or `security.audit_trail=true`, no audit
  entries are written and `verify` has nothing to validate.
- `sw clean` does NOT delete `audit-trail.jsonl` (by design). To purge
  audit history, delete the file by hand and document it.

---

## 10. Migrate from a pre-v1.3.x telemetry log

**Goal:** Run sw against a project whose `sw-telemetry.jsonl` was written
by a pre-v1.3.x version.

**Steps:**
```bash
sw drift --baseline                # reads pre-v1.3.x events (they're additive)
sw triage                          # classifies anchored failures
sw estimate --calibration          # may report "skipped N pre-v1.3.24
                                   # sample(s) with no model_id"
```

**Verify:**
- No crashes — all v1.3.x readers handle missing fields with defaults
- Calibration skip count logged at INFO

**Pitfalls:**
- Pre-v1.3.24 `MilestoneCompleted` events have NO `model_id` and are skipped
  by calibration. This is correct: pooling them under "unknown" would
  inflate that bucket forever and never warm a real per-model bucket.
- Pre-v1.3.26 `workflow-state.json` files have NO `breaker_window`. State
  loader defaults the field to `[]` (regression-tested).
- See [`migration.md`](migration.md) for the per-release schema bumps.
