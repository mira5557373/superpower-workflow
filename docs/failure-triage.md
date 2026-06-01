# Failure Triage Classifier (v1.3.21)

Pure-functional rule-only classifier that maps every terminal sw failure
into a typed `FailureClass` with confidence + evidence chain +
recommendation. Zero LLM calls. Deterministic. Replayable offline.

## What it solves

`sw` already had failure plumbing — `_PhaseError` names the failing
phase, `MilestoneFailed` carries a `reason` string, the audit trail logs
`MILESTONE_START` without a matching completion. But none of that tells
you *why* — the kind that maps to a specific user action.

Failure Triage closes that gap: it reads the existing telemetry +
audit + state and outputs a typed FailureClass with the recommendation
template attached.

## 14 failure classes

| # | Class | Trigger (first match wins) | Conf |
|---|---|---|---|
| 1 | `COST_CEILING_BLOCKED` | `CostCeilingBlocked` event OR `CEILING_BLOCK` audit | 1.0 |
| 2 | `BUDGET_EXCEEDED` | `BudgetAlert.threshold=100` | 1.0 |
| 3 | `MERGE_CONFLICT` | `WorktreeMerged.success=false` OR `conflicts>0` | 1.0 |
| 4 | `PLUGIN_VETO` | `PluginVetoed` matching anchor.phase | 1.0 |
| 5 | `POLICY_VIOLATION` | `POLICY_VIOLATION` audit entry | 1.0 |
| 6 | `COVERAGE_BELOW_THRESHOLD` | `CoverageResult.passed=false` | 1.0 |
| 7 | `QUALITY_GATE_FAIL` | any `QualityGateResult.passed=false` | 1.0 |
| 8 | `CLAUDE_SUBPROCESS_TIMEOUT` | `ClaudeInvocationFailed.error_kind=timeout` (or regex fallback) | 1.0 / 0.7 |
| 9 | `CLAUDE_SUBPROCESS_ERROR` | `ClaudeInvocationFailed.error_kind in {is_error,nonzero_exit,mcp_crash,auth}` | 0.7 |
| 10 | `STRICT_MODE_NON_CONVERGE` | `StrictModeIteration.iteration==max AND converged=false` | 1.0 |
| 11 | `SPEC_FEATURE_GAP` | `SpecComplianceCompleted.missing>0` OR `FeatureVerificationCompleted.broken>0` | 1.0 |
| 12 | `GAP_NON_CONVERGE` | `GapReport.converged=false` on Phase C | 0.7 |
| 13 | `CI_FIX_FAIL` | `reason ~= CI_FIX_FAILED` OR `state.current_step=ci_fix_failed` | 1.0 |
| 14 | `UNKNOWN` | nothing matched | 0.4 |

Plus one secondary tag (never primary): `DRIFT_CORRELATED` — appended
when `DriftDetected.severity=critical` for cost/duration. Drift is
correlation, not cause.

## CLI

```bash
sw triage                                    # all failures in current project
sw triage --milestone p4-m1-monaco           # deep view + evidence chain
sw triage --json                             # machine-readable
```

Exit codes:
- `0` — any output (including zero failures)
- `2` — telemetry file missing / unreadable
- `3` — `--milestone` specified but not found

## Composite-failure semantics (independence rule)

When multiple rules fire for the same failure, the result is:
- `primary_class` = the first matching rule in `RULES` registration order
- `secondary_classes` = subsequent matches whose `trigger_seq > primary.trigger_seq`
  AND which are not in `IMPLIES[primary]`

The `IMPLIES` graph captures rule-level subsumption (POLICY_VIOLATION
implies QUALITY_GATE_FAIL — both fire on the same QG check, but
POLICY_VIOLATION is the more specific finding).

This makes composite output deterministic across rule reorderings.

## Determinism invariant

Two `classify_run()` calls on the same telemetry produce byte-identical
JSON. Verified by `test_classify_run_idempotent` and the CLI smoke test
`test_two_invocations_identical_json`.

## Verification without labels

A common adversarial critique of any classifier: "you can't claim
accuracy without ground-truth labels." We address this by making the
test fixtures *be* the ground truth — each test in `test_failure_triage.py`
constructs a synthetic event sequence from a documented narrative
(e.g., "strict-mode hit max iter with non-convergence") and asserts
the classifier matches. The narrative is independently readable; a
reviewer can predict the class without looking at the rule code.

## Adding a new rule

1. Write the predicate function in `failure_triage.py`:
   ```python
   def _rule_15_my_new_failure(bundle: BundleWindow) -> RuleMatch | None:
       for ev in bundle.events_of("my_event_type"):
           if some_condition(ev):
               return RuleMatch(
                   primary=FailureClass.MY_NEW_FAILURE,
                   confidence=1.0,
                   evidence=(_ev(ev, "detail=..."),),
                   trigger_seq=int(ev.get("seq", 0)),
               )
       return None
   ```
2. Add `MY_NEW_FAILURE = "my_new_failure"` to the `FailureClass` enum.
3. Add a recommendation to `RECOMMENDATIONS`.
4. Append the rule to `RULES` in priority order.
5. Write a test class `TestRule15...` mirroring the others.
6. If the new class implies another, update `IMPLIES`.

## Kill switches

- **Per-project**: `triage.enabled = false` in workflow.json.
- **Per-session**: `SW_TRIAGE_OFF=1` env var (CLI and orchestrator hook both honor).
- **Per-codepath**: triage hook is wrapped in try/except — any internal
  failure produces a missing event, never a broken run.

## Performance

Online hook budget: ≤200ms per failure (verdict revision #6). The
classifier itself is microseconds; the budget covers the JSONL read.
For projects with >10k events the reader cache (passed via
`read_events`/`read_audit` callbacks) avoids re-parsing on subsequent
failures within the same run.

## Distinct from neighboring features

| Feature | Question it answers |
|---|---|
| Drift Detector (v1.3.19) | Is this run abnormal vs baseline? (correlation) |
| Cost Ceilings (v1.3.20) | Did we exceed a cross-run budget envelope? (boundary) |
| Strict Mode | Are residual findings actionable for one more loop? (iteration) |
| Gap Curator | Which gap-report items deserve attention? (filter) |
| **Failure Triage (v1.3.21)** | **Why did this milestone fail?** (cause) |

Drift answers "abnormal"; triage answers "why". They compose: a drift
event in the failure bundle becomes `DRIFT_CORRELATED` secondary on the
TriageResult.
