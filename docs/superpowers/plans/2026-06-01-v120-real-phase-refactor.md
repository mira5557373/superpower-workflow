# v1.2.0-real: Phase A/B/C/D/E class refactor

**Date:** 2026-06-01
**Author:** post-v1.3.x integration audit (8-agent workflow scorecard + 3-agent adversarial review)
**Status:** plan; Task 1 in progress

## Context

The v1.1.6 → v2.0.0 roadmap planned v1.2.0 as the phase-based class refactor:
extract Phase A/B/C/D into `PhaseBase` subclasses, shrink `_run_milestone`
from ~500 lines to ~80, unblock downstream features (cost-alert hooks,
intelligence layer, custom-phase plugins). The CHANGELOG entry shipped at
v1.2.0, but the headline `T2.0.1` work was deferred — the codebase pivoted
into a 13-patch v1.3.x parallel-execution hardening line instead. Result:

| | At v1.2.0 spec | At v1.3.14 reality |
|---|---|---|
| `_run_milestone` | target ≤80 lines | **657 lines** (grew from 502) |
| `orchestrator.py` total | ≤700 lines | 2316 lines |
| `phases/` package | exists | absent |
| `TrustButVerifyPipeline` | wired | **dead code** (CHANGELOG line 1168 admission) |
| Complexity ceilings | (100, 15, 4) | grandfathered at (510, 50, 7) |

This plan finishes the refactor. **Token cost is not a constraint** —
the goal is the most exhaustive, correct landing.

## Audit verdicts and resolutions

A 3-agent adversarial review of the initial design surfaced 2 significant
findings. Both are addressed here before any code lands.

### Finding 1 — CRITICAL: cost-accumulation granularity must not regress

**Failure mode** — the initial pseudocode had each phase locally sum
`phase_cost += r.cost_usd; phase_cost += curator_cost; ...` and the driver
called `self.orc._accumulate_cost(ctx.accumulated_cost, result.cost_usd)`
ONCE per phase boundary. That collapses ~15 in-milestone `_accumulate_cost`
sites down to 5. **The v1.3.12 in-flight budget gate depends on per-call
granularity:** sibling parallel workers read `state.total_cost_usd +
others_in_flight` to decide whether to start their next claude call. If
state lags by a whole Phase B ($50-100), siblings will exceed the cap.
Separately, **v1.3.4 #15** (retry safety) requires cost to land in state
BEFORE `_check_phase_result` can raise — the pre-v1.3.4 bug was that
retries dropped already-spent dollars.

**Resolution** — the contract is:

1. **Inside each phase**, call `self.orc._accumulate_cost(local_acc, delta)`
   after EVERY internal claude call. Primary call, curator, QG fix-loop,
   coverage, compliance, verification, strict-mode iterations, ci_fix
   retries — all of them. Each call advances `state.total_cost_usd` and
   persists state under `_state_lock`. v1.3.12 in-flight gate binds
   identically to today.
2. **`PhaseResult.cost_usd` is REPORTING-ONLY.** It's the local sum of all
   claude-call costs inside the phase, returned for golden-trace
   introspection and dashboard consumers. It is NOT what the driver passes
   to `_accumulate_cost` — the driver never calls `_accumulate_cost`.
3. **Driver does pure-local add**: `ctx = ctx.update(accumulated_cost =
   ctx.accumulated_cost + result.cost_usd, **result.extras)`. No state
   write at the driver level. The state has already been updated
   incrementally by the phase.
4. **Phase pseudocode mandates per-call accumulation** — the per-phase
   sections below show the explicit `self.orc._accumulate_cost(...)` calls
   at every claude-call boundary.
5. **Regression net** — `tests/test_v1312_in_flight_budget.py` keeps its
   existing assertions. Add a new test:
   `test_v1312_in_flight_gate_binds_during_phase_b_fix_loop` that puts the
   budget cap at a value reachable AFTER the primary Phase B call but
   BEFORE the QG fix-loop call, and asserts the second parallel worker is
   rejected on the fix-loop attempt.

### Finding 2 — HIGH: golden trace must capture more than events

**Failure mode** — the initial Task 1 design appended event TYPE NAMES to
`events_emitted` by hand inside each PhaseN.run, only at the sites the
plan listed. It missed `QualityGateResult` (typed telemetry emitted by
`_verify_quality_gates`, 4 per checkpoint × 2 checkpoints = 8 per
milestone). It used one token shape across all stub `_run_claude` calls,
so a regression caching the first envelope's tokens passed. It captured
`PhaseCompleted` event payloads but never asserted `PhaseResult.tokens`
return values. It sampled `accumulated_cost` at phase boundaries — which
by definition collapses Finding 1's regression. The fixture didn't cover
fix-loop, recheck-checkpoint, or strict-mode iteration. The SwPhase DB
roundtrip surface (v1.3.14 hotfix) was not in the oracle.
`GOLDEN_TRACE_UPDATE=1` was an unguarded footgun.

**Resolution** — Task 1's parity oracle is restructured around four
recorders that together capture the load-bearing state:

1. **Universal telemetry sink** — subscribes to ALL events (not a manual
   append list). Records `(call_index, event_type, key_field_dict)` per
   event in arrival order. Key fields are stable per event type (e.g.,
   `QualityGateResult` records `checkpoint`, `gate_name`, `passed`).
2. **`_accumulate_cost` recorder** — wraps `Orchestrator._accumulate_cost`
   with a passthrough that records `(call_index, delta, resulting_total)`
   in arrival order. Captures Finding 1's regression directly.
3. **`save_state` recorder** — wraps `state.save_state` (the function) to
   record `(call_index, state_path_basename, current_step, total_cost_usd)`
   in arrival order. Captures state-transition order changes.
4. **Subprocess dispatcher** — monkeypatches `subprocess.run` with a
   cmd-prefix-aware dispatcher: `git rev-parse` → deterministic 40-char
   SHA, `git tag` → rc=0, `git push` → rc=0, gate shell commands → rc=0
   on happy fixture, rc=1 on fix-loop fixture.
5. **Two fixtures** — `golden_trace_happy.json` (all gates pass first try,
   no compliance gaps, strict mode no-op) and
   `golden_trace_fixloop.json` (one gate failure → fix-loop, one
   policy failure → `quality_check_b_recheck`, strict mode 1 residual
   iteration).
6. **Per-call token-shape variation** — `_run_claude` stub returns
   different token shapes based on `call_index` (primary calls,
   curator calls, fix-loop calls each get distinct cache_read /
   input_tokens values). This catches regressions that cache or
   mis-aggregate tokens.
7. **SwPhase DB roundtrip assertion** — after `_run_milestone` returns,
   the test queries `SwPhase` rows via `DbSyncAdapter` and asserts every
   row carries the correct `cache_creation_input_tokens`,
   `cache_read_input_tokens`, `cache_hit_rate`. Locks the v1.3.14 hotfix
   surface.
8. **PhaseResult.tokens assertion** — Tasks 2+ add a thin `PhaseBase.run`
   wrapper that records each returned `PhaseResult`; Task 1 lays out the
   recorder skeleton with placeholder entries (filled in by Task 2 when
   `PhaseBase` exists).
9. **Update gating** — `GOLDEN_TRACE_UPDATE=1` is rejected unless
   `GOLDEN_TRACE_RATIONALE` is also set (non-empty). CI fails any PR
   that modifies `tests/golden/*.json` without a `CHANGELOG.md` entry
   in the same commit (enforced by a small `tests/test_golden_rationale.py`).

### Finding 3 — MEDIUM: scope clean-ups

- **Helper placement** — Task 3 extracts `_verify_quality_gates` and
  related logic into `src/superpower_workflow/quality_gates.py` as
  module-level functions. PhaseB/PhaseC call
  `run_quality_gate_checkpoint(self.orc, ctx, checkpoint=...)`. The
  initial plan's PhaseB-method form is dropped.
- **PhaseB/TbV split** — the initial plan folded TbV stages (compliance,
  verification) into PhaseB.run() under the label "TbV setup". This
  conflates a future phase boundary. Resolution: PhaseB ends after QG#1
  + context refresh; a thin `PhaseTbV` (stage between B and C in the
  driver) owns the compliance + verification calls + curator. PhaseC
  then sees `ctx.compliance_report` + `ctx.verification_report`
  populated. Cost: ~30 LOC of plumbing, benefit: v1.2.1 wire-up of
  `TrustButVerifyPipeline` becomes a 1-line swap in the driver.
- **Complexity ratchet dropped** — current ceilings (510, 50, 7)
  accommodate the post-refactor footprint trivially (`_run_milestone`
  shrinks to ~80 lines, each phase class ≤80 lines). No CI-ceiling
  bump needed. Instead Task 10 adds a NEW per-file assertion: every
  module under `src/superpower_workflow/phases/` must clear the
  v2.0.0 targets (100, 15, 4). New files cannot be silently
  grandfathered.
- **extras-splat safety** — `PhaseContext.update(**extras)` uses
  `dataclasses.replace` which raises `TypeError` on unknown keys. A unit
  test pins this contract so a Phase that adds an extras key without
  adding it to `PhaseContext` fails loudly, not silently.

## Architecture

### `PhaseBase` (abstract)

```python
from abc import ABC, abstractmethod
from typing import ClassVar

class PhaseBase(ABC):
    """Common skeleton for Phase A/B/C/D/E.

    Subclasses implement `run(ctx)` and rely on helpers on the
    orchestrator handle for the side effects that touch shared state
    (telemetry, audit, cost accumulation, state persistence).
    """

    name: ClassVar[str]                       # 'plan'|'implement'|'review'|'push'|'ci_fix'
    log_event_start: ClassVar[str]            # e.g., 'PHASE_A_START'
    log_event_complete: ClassVar[str]         # e.g., 'PHASE_A_COMPLETE'

    def __init__(self, orchestrator: "Orchestrator") -> None:
        self.orc = orchestrator

    @abstractmethod
    def run(self, ctx: "PhaseContext") -> "PhaseResult": ...

    # ---- shared helpers; not overridable in practice ----

    def _emit_phase_started(self, ctx: "PhaseContext") -> None: ...
    def _emit_phase_completed(self, ctx: "PhaseContext", r: "ClaudeResult",
                               extra_cost: float = 0.0) -> None: ...
    def _audit_complete(self, ctx: "PhaseContext", cost: float) -> None: ...
    def _set_current_step(self, ctx: "PhaseContext", step: str) -> None: ...
    def _call_pre_phase(self, ctx: "PhaseContext") -> None: ...
    def _call_post_phase(self, ctx: "PhaseContext", cost: float) -> None: ...
```

### `PhaseContext` (frozen dataclass)

```python
@dataclass(frozen=True)
class PhaseContext:
    # identity
    milestone_name: str
    milestone_dict: dict

    # config slice (read-only refs)
    spec: str
    sections: str
    model: str
    fallback_model: str | None
    budgets: dict
    effort: dict[str, str]
    verify: dict[str, str]
    convergence: dict
    validation: dict

    # cumulative work (advanced via ctx.update())
    context_summary: str
    accumulated_cost: float = 0.0
    plan_commit_sha: str | None = None

    # downstream injection (PhaseB → PhaseTbV → PhaseC)
    compliance_report: dict | None = None
    verification_report: dict | None = None

    # logger handle kept here so PhaseBase.run remains single-arg
    logger: "WorkflowLogger | None" = None

    def update(self, **kwargs) -> "PhaseContext":
        """Return a NEW PhaseContext with fields replaced.

        Phases MUST go through update(), never dataclasses.replace
        directly. update() is the single instrumentation point for
        golden-trace recording.
        """
        return dataclasses.replace(self, **kwargs)
```

### `PhaseResult`

```python
@dataclass
class PhaseResult:
    phase: str
    cost_usd: float           # REPORTING-ONLY local sum (Finding 1)
    duration_ms: int          # primary claude call duration; 0 for ci_fix
    session_id: str           # primary claude session; '' for ci_fix
    tokens: dict[str, int | float]  # keys match extract_token_usage()
    events_emitted: list[str]       # used by golden trace
    error: "_PhaseError | None" = None
    extras: dict = field(default_factory=dict)
```

### Error protocol

- Each phase's critical section wraps `PluginVetoError` → `_PhaseError(self.name, ...)`.
- `_check_phase_result` raises `_PhaseError(self.name, ...)` on `r.is_error`.
- **All cost accumulation happens BEFORE `_check_phase_result`**, so
  retries don't lose already-spent dollars (v1.3.4 #15).
- PhaseE never raises on `ci_success=False` — sets state.current_step='ci_fix_failed' and returns.
- Other phases let `_PhaseError` propagate to the orchestrator retry loop.
- Phases MUST NOT swallow non-`_PhaseError` exceptions.

## Per-phase designs

### PhaseA — Plan

**Source**: lifts orchestrator.py lines 1099-1158.

**Side effects**: writes `pre-impl/{name}` git tag, records `plan_commit_sha`.

```python
class PhaseA(PhaseBase):
    name = "plan"
    log_event_start = "PHASE_A_START"
    log_event_complete = "PHASE_A_COMPLETE"

    def run(self, ctx):
        events = []
        self._call_pre_phase(ctx)
        self._set_current_step(ctx, "plan")

        save_phase_state(self.orc.claude_dir, PhaseState(
            phase="ultrathink",
            max_iterations=ctx.convergence.get("max_iterations", 5),
        ))
        ctx.logger.log("PHASE_A_START")
        self._emit_phase_started(ctx); events.append("PhaseStarted")

        r = self.orc._run_claude(
            phase_a_prompt(ctx.milestone_name, ctx.context_summary, ctx.spec, ctx.sections),
            model=ctx.model,
            effort=ctx.effort.get("plan", "max"),
            budget=ctx.budgets.get("plan", 25),
            cwd=self.orc.cwd,
            system_prompt=self.orc.sys_prompt,
            fallback_model=ctx.fallback_model,
        )
        # Per-call accumulate — preserves v1.3.12 + v1.3.4 #15.
        local_acc = self.orc._accumulate_cost(0.0, r.cost_usd)
        phase_cost = r.cost_usd

        curator_cost = self.orc._run_gap_curator(ctx.milestone_name, "plan")
        local_acc = self.orc._accumulate_cost(local_acc, curator_cost)
        phase_cost += curator_cost

        self.orc._emit_gap_report(ctx.milestone_name, "plan"); events.append("GapReport")
        self.orc._emit_gap_validation(ctx.milestone_name); events.append("GapValidationEvent")

        archive_reports(self.orc.claude_dir, ctx.milestone_name, "plan")
        clear_phase_state(self.orc.claude_dir)

        self.orc._check_phase_result(r, "Phase A")  # cost is already in state
        self._emit_phase_completed(ctx, r); events.append("PhaseCompleted")
        ctx.logger.log("PHASE_A_COMPLETE", cost=round(r.cost_usd, 2))
        self._audit_complete(ctx, r.cost_usd)
        self._call_post_phase(ctx, r.cost_usd)

        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=self.orc.cwd,
        ).stdout.strip()
        self.orc.state.plan_commit_sha = sha
        self.orc.state.last_phase_session_id = r.session_id
        save_state(self.orc._state_dir, self.orc.state)

        subprocess.run(
            ["git", "tag", f"pre-impl/{ctx.milestone_name}"],
            capture_output=True, cwd=self.orc.cwd,
        )

        return PhaseResult(
            phase="plan",
            cost_usd=phase_cost,
            duration_ms=r.duration_ms,
            session_id=r.session_id,
            tokens=extract_token_usage(r.raw),
            events_emitted=events,
            extras={"plan_commit_sha": sha},
        )
```

**Gotchas**:
1. `cwd=self.orc.cwd` is **always** the thread-local property — preserves
   v1.3.13 #3 parallel worker isolation.
2. `save_phase_state` writes BEFORE the claude call (convergence hook
   reads it during the call); `clear_phase_state` AFTER.
3. `_check_phase_result` raises AFTER `_accumulate_cost` — preserves
   v1.3.4 #15 retry safety.
4. `extract_token_usage` runs at emission time, not cached.

### PhaseB — Implement (+ QG#1 + context refresh)

**Source**: lifts orchestrator.py lines ~1170-1267 (implement + QG#1
+ context refresh). Does NOT own TbV (compliance + verification) —
those move to PhaseTbV.

**Helpers used**:
- `quality_gates.run_quality_gate_checkpoint(orc, ctx, checkpoint="quality_check_b")` (module-level, Task 3)
- Primary claude call, then QG#1 (which may invoke fix-loop), then context refresh.

```python
class PhaseB(PhaseBase):
    name = "implement"

    def run(self, ctx):
        events = []
        self._call_pre_phase(ctx)
        self._set_current_step(ctx, "implement")
        ctx.logger.log("PHASE_B_START")
        self._emit_phase_started(ctx); events.append("PhaseStarted")

        r = self.orc._run_claude(phase_b_prompt(...), ...)
        local_acc = self.orc._accumulate_cost(0.0, r.cost_usd)
        phase_cost = r.cost_usd

        # QG#1: gates + policies + coverage + secret scan + dep audit.
        # Helper records gate verdicts, runs fix-loop on failure (which
        # itself calls _accumulate_cost per claude call), returns
        # (extra_cost, events_appended).
        qg_cost, qg_events = run_quality_gate_checkpoint(
            self.orc, ctx,
            checkpoint="quality_check_b",
            local_acc=local_acc,
        )
        local_acc += qg_cost
        phase_cost += qg_cost
        events.extend(qg_events)

        # Context refresh — picks up new files Phase B may have created.
        ctx = ctx.update(context_summary=build_context_summary(self.orc.cwd, ctx.milestone_name))

        self.orc._check_phase_result(r, "Phase B")
        self._emit_phase_completed(ctx, r, extra_cost=qg_cost)
        events.append("PhaseCompleted")
        ctx.logger.log("PHASE_B_COMPLETE", cost=round(phase_cost, 2))
        self._audit_complete(ctx, phase_cost)
        self._call_post_phase(ctx, phase_cost)

        return PhaseResult(
            phase="implement",
            cost_usd=phase_cost,
            duration_ms=r.duration_ms,
            session_id=r.session_id,
            tokens=extract_token_usage(r.raw),
            events_emitted=events,
            extras={"context_summary": ctx.context_summary},
        )
```

**Gotchas**:
1. Asymmetric checkpoint label for policies: `quality_check_b` on first
   pass, `quality_check_b_recheck` on policy fix-loop. The helper
   handles this; PhaseB just passes the base checkpoint.
2. Fix-loop calls `_accumulate_cost` per claude call internally — sites
   must be inside the helper, not in PhaseB.
3. Context refresh happens AFTER QG so refreshed context reflects any
   fixes the gates applied.

### PhaseTbV — Trust-but-verify (compliance + verification + curator)

**New phase introduced by Finding 3 resolution.** Owns the two TbV stages
that previously sat ad-hoc between B and C in `_run_milestone`. Splitting
them out keeps PhaseB at "implement + QG", makes the v1.2.1
`TrustButVerifyPipeline` wire-up a 1-line driver swap.

```python
class PhaseTbV(PhaseBase):
    name = "trust_but_verify"

    def run(self, ctx):
        events = []
        if not ctx.validation.get("spec_compliance", False) and \
           not ctx.validation.get("feature_verification", False):
            return PhaseResult(phase="trust_but_verify", cost_usd=0.0,
                               duration_ms=0, session_id="",
                               tokens={"input_tokens": 0, "output_tokens": 0,
                                       "cache_creation_input_tokens": 0,
                                       "cache_read_input_tokens": 0,
                                       "cache_hit_rate": 0.0},
                               events_emitted=events,
                               extras={"compliance_report": None,
                                       "verification_report": None})

        phase_cost = 0.0
        local_acc = ctx.accumulated_cost

        if ctx.validation.get("spec_compliance", False):
            comp_cost, comp_report = self.orc._run_spec_compliance(ctx.milestone_name)
            local_acc = self.orc._accumulate_cost(local_acc, comp_cost)
            phase_cost += comp_cost
            events.append("SpecComplianceCompleted")
        else:
            comp_report = None

        if ctx.validation.get("feature_verification", False):
            verif_cost, verif_report = self.orc._run_feature_verification(ctx.milestone_name)
            local_acc = self.orc._accumulate_cost(local_acc, verif_cost)
            phase_cost += verif_cost
            events.append("FeatureVerificationCompleted")
        else:
            verif_report = None

        # Curator runs against both reports.
        curator_cost = self.orc._run_gap_curator(ctx.milestone_name, "tbv")
        local_acc = self.orc._accumulate_cost(local_acc, curator_cost)
        phase_cost += curator_cost

        return PhaseResult(
            phase="trust_but_verify",
            cost_usd=phase_cost,
            duration_ms=0,  # no primary claude call
            session_id="",
            tokens={"input_tokens": 0, "output_tokens": 0,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                    "cache_hit_rate": 0.0},
            events_emitted=events,
            extras={"compliance_report": comp_report,
                    "verification_report": verif_report},
        )
```

**Gotcha**: `extras` must include `compliance_report` and `verification_report`
even when None — PhaseContext's frozen-dataclass replacement still
requires the field name. The driver-level `ctx.update(**extras)` will
pass them through; PhaseC reads them.

### PhaseC — Review (+ QG#2 + strict mode)

**Source**: lifts orchestrator.py lines ~1280-1430.

```python
class PhaseC(PhaseBase):
    name = "review"

    def run(self, ctx):
        events = []
        self._call_pre_phase(ctx)
        self._set_current_step(ctx, "review")
        ctx.logger.log("PHASE_C_START")
        self._emit_phase_started(ctx); events.append("PhaseStarted")

        r = self.orc._run_claude(
            phase_c_prompt(
                ctx.milestone_name,
                ctx.context_summary,
                compliance_report=ctx.compliance_report,
                verification_report=ctx.verification_report,
            ),
            ...,
        )
        local_acc = self.orc._accumulate_cost(0.0, r.cost_usd)
        phase_cost = r.cost_usd

        qg_cost, qg_events = run_quality_gate_checkpoint(
            self.orc, ctx,
            checkpoint="quality_check_c",
            local_acc=local_acc,
        )
        local_acc += qg_cost
        phase_cost += qg_cost
        events.extend(qg_events)

        # Strict mode loop — internal _accumulate_cost calls per iteration.
        if ctx.validation.get("strict_mode", False):
            strict_cost, strict_events = self.orc._run_strict_mode_loop(
                ctx.milestone_name,
                compliance=ctx.compliance_report,
                verification=ctx.verification_report,
                local_acc=local_acc,
            )
            local_acc += strict_cost
            phase_cost += strict_cost
            events.extend(strict_events)

        self.orc._check_phase_result(r, "Phase C")
        self._emit_phase_completed(ctx, r, extra_cost=phase_cost - r.cost_usd)
        events.append("PhaseCompleted")
        ctx.logger.log("PHASE_C_COMPLETE", cost=round(phase_cost, 2))
        self._audit_complete(ctx, phase_cost)
        self._call_post_phase(ctx, phase_cost)

        return PhaseResult(
            phase="review", cost_usd=phase_cost,
            duration_ms=r.duration_ms, session_id=r.session_id,
            tokens=extract_token_usage(r.raw),
            events_emitted=events,
            extras={},
        )
```

### PhaseD — Push

**Source**: orchestrator.py lines ~1430-1480.

**Critical ordering** (per Finding 1 verdict point 4):
1. Primary claude call
2. `_accumulate_cost`
3. `_check_phase_result`
4. `_emit_phase_completed` + `_audit_complete`
5. **`_call_post_phase` (BEFORE SBOM/sign — matches current source)**
6. SBOM
7. Sign

### PhaseE — CI fix

**Source**: orchestrator.py lines 1480-1532; `ci_fix.ci_fix_loop` is reused as-is.

**Critical ordering** (per Finding 1 verdict point 3):
```python
self._set_current_step(ctx, "ci_wait")
save_state(self.orc._state_dir, self.orc.state)
ctx.logger.log("PHASE_E_START")
self._emit_phase_started(ctx); events.append("PhaseStarted")
self._set_current_step(ctx, "ci_fix")
save_state(self.orc._state_dir, self.orc.state)
# ... ci_fix_loop call ...
```

`ci_fix_loop` returns `(success, total_cost, aggregated_tokens)`.
Per-iteration `_accumulate_cost` happens INSIDE the loop (already does).
PhaseE returns `PhaseResult(cost_usd=ci_total, ..., tokens=ci_tokens,
extras={"ci_success": success})`.

PhaseE NEVER raises on `ci_success=False`. Driver checks
`result.extras["ci_success"]` and decides milestone-failed vs completed.

## Ordered tasks

| # | Title | Files | Test strategy | LoC |
|---|---|---|---|---|
| 1 | **Golden trace parity oracle (current behavior)** | `tests/test_v120_golden_trace.py`, `tests/golden/v120_baseline.json`, `tests/golden/v120_fixloop.json` | Records ALL events, `_accumulate_cost` calls, `save_state` calls, subprocess dispatch, SwPhase DB roundtrip. Two fixtures. CI fails on diff. Update mode gated on `GOLDEN_TRACE_RATIONALE`. | 400 |
| 2 | **PhaseBase + PhaseContext + PhaseResult skeleton** | `src/superpower_workflow/phases/{__init__.py,base.py,context.py,result.py}`, `tests/test_phases_base.py` | Unit tests for PhaseContext frozen-ness, update() with unknown key raises, PhaseResult shape, error protocol. | 250 |
| 3 | **Extract `quality_gates.run_quality_gate_checkpoint` helper** | `src/superpower_workflow/quality_gates.py`, `tests/test_quality_gate_checkpoint_helper.py` | Test fix-loop path with asymmetric `_recheck` checkpoint label. Test gate ordering (`lint, sast, secret_scan, dep_scan`). Test per-call `_accumulate_cost`. | 300 |
| 4 | **PhaseA implementation** | `src/superpower_workflow/phases/plan.py`, `tests/test_phase_a.py` | Wire into orchestrator behind a feature flag; golden trace must pass with flag on AND off. Unit test PhaseA.run on a mock orc. | 280 |
| 5 | **PhaseB + PhaseTbV implementation** | `src/superpower_workflow/phases/{implement.py,trust_but_verify.py}`, `tests/test_phase_b.py`, `tests/test_phase_tbv.py` | Same flag gate. Golden trace must still match. Unit tests cover fix-loop, context refresh, TbV None-report passthrough. New test `test_v1312_in_flight_gate_binds_during_phase_b_fix_loop`. | 380 |
| 6 | **PhaseC implementation** | `src/superpower_workflow/phases/review.py`, `tests/test_phase_c.py` | Golden trace pass. Unit tests cover strict-mode iteration, QG#2 fix-loop. | 280 |
| 7 | **PhaseD + PhaseE implementation** | `src/superpower_workflow/phases/{push.py,ci_fix.py}`, `tests/test_phase_d.py`, `tests/test_phase_e.py` | PhaseD ordering test pins `_call_post_phase` BEFORE SBOM/sign. PhaseE state-transition order test pins `ci_wait → save → log → PhaseStarted → ci_fix → save`. | 300 |
| 8 | **Driver loop in orchestrator** | edit `src/superpower_workflow/orchestrator.py` — replace `_run_milestone` body with a thin phase iterator | Golden trace must pass byte-identical with flag on. All existing 1432 tests must pass. | 150 (net: −500) |
| 9 | **Retire dead code: wire `TrustButVerifyPipeline`** | edit `src/superpower_workflow/pipelines/trust_but_verify.py` + driver — make PhaseTbV the default; pipeline can swap in via plugin | 1-line driver swap test. Existing TrustButVerifyPipeline unit tests preserved. | 80 |
| 10 | **Per-phase complexity check + plugin extension point** | `scripts/complexity_audit.py` (add `--per-module-target src/superpower_workflow/phases=100,15,4`), `src/superpower_workflow/plugins/phases.py` (registry), `examples/security_audit_phase/` (one example custom phase) | New CI assertion that `phases/*.py` clears (100, 15, 4). Plugin loads example custom phase between C and D. | 180 |

**Total LoC delta**: ~+2600 added, ~−1500 removed from orchestrator.py.
Net **+1100** spread across phases/, quality_gates.py, plugins/.
~12-15 conventional commits.

## Test strategy summary

- **Task 1** is the parity oracle — no later task lands without it
  passing identically. Pre- and post-refactor traces must deep-equal.
- **Per-phase unit tests** (Tasks 2-7) instantiate the phase against a
  mock orchestrator and assert: state transitions, event emissions,
  per-call `_accumulate_cost`, error propagation.
- **Integration test** at Task 8 — entire 1432-test suite runs
  unchanged. No regressions allowed.
- **New v1.3.12 regression test** in Task 5 — pins per-call
  in-flight gate granularity through the refactor.
- **PhaseD/E ordering tests** in Task 7 — pin the two ordering
  invariants the adversarial review flagged.

## Risks

1. **Parallel-mode interaction** — `_state_dir` and `claude_dir` are
   thread-local properties. Every phase's pseudocode uses
   `self.orc._state_dir` for parent-state writes and `self.orc.cwd` for
   subprocess. Grep test in Task 1 enforces this — fails if any
   `self.orc.claude_dir` slips into a save_state call.

2. **KB writes** — currently happen inside `_run_milestone` at end-of-
   milestone. Stay in the driver (not in phases). Tested by golden trace.

3. **TrustButVerifyPipeline silent break** — PhaseTbV produces the same
   `compliance_report` + `verification_report` shape today. v1.2.1 swaps
   PhaseTbV for the Pipeline; that swap is a 1-line driver change
   (`tbv_phase = TrustButVerifyPipeline(...)` instead of `PhaseTbV()`).

4. **golden trace flakiness** — recorders sort by `call_index` (a
   thread-local monotonic counter). Subprocess dispatcher is purely
   stub. Telemetry sink subscribes BEFORE `_run_milestone` enters.
   Deterministic by construction.

5. **Cost-accumulation granularity (Finding 1)** — resolved by per-call
   `_accumulate_cost` in every phase. Pinned by the new
   `test_v1312_in_flight_gate_binds_during_phase_b_fix_loop` test.

6. **PhaseContext extras drift (Finding 3)** — `ctx.update(**extras)`
   uses `dataclasses.replace` which raises `TypeError` on unknown keys.
   Task 2's unit tests pin this. A phase adding an extras key without
   adding it to PhaseContext fails loudly.

## What's NOT in this release

- Cost-projection (RunCostProjection class) — slots in cleanly AFTER
  PhaseBase exists; deferred to v1.3.0 follow-ups.
- TrustButVerifyPipeline FULL integration — staged: PhaseTbV first
  (this release), pipeline wiring next.
- Intelligence layer (v1.4.0) — needs phase classes as first-class
  nouns before model-routing decisions can hang off them. Blocked on
  this release.
- MCP server + cost-alert/quality-gate hooks (v1.3.0 remainder) —
  blocked on this release (hooks specifically want stable phase-class
  extension points).
- **memory.py — DESCOPED.** The v1.3.0 plan called for a `memory.py`
  module to distill milestone learnings into cross-session memory.
  After review, [claude-mem](https://github.com/thedotmack/claude-mem)
  fulfills this need natively (5 lifecycle hooks, SQLite + Chroma
  vector DB, MCP tools + HTTP API + web UI, project-scoped). sw's
  `memory.py` would duplicate that with less integration depth.
  Users wanting structured sw-run summaries in claude-mem can add a
  thin ~30-line adapter that calls claude-mem's MCP `write_observation`
  after milestone completion. Not a module in sw.
- Complexity-ceiling ratchet from (510, 50, 7) toward (100, 15, 4)
  globally — Task 10 only checks `phases/` against (100, 15, 4); the
  monolith ceiling stays grandfathered to avoid scope creep.

## Acceptance criteria

- All 1432 existing tests pass + ~+80 new tests (~1512 total).
- `_run_milestone` body ≤100 lines.
- `tests/golden/v120_baseline.json` identical pre and post refactor.
- `phases/*.py` clears v2.0.0 ceilings (100, 15, 4).
- `TrustButVerifyPipeline` either deleted as dead code or re-wired
  (Task 9 chooses).
- New `test_v1312_in_flight_gate_binds_during_phase_b_fix_loop` passes.
- CI matrix green.

## Out-of-scope (deferred)

- Async PhaseBase — sync per ODQ-4. Async deferred to ≥v2.0.0.
- Result-types for error handling — keep exception-based until pain.
- Per-phase budget caps — phases still share `ctx.budgets` per-step;
  per-phase isolation is a v1.3.0 follow-up.
