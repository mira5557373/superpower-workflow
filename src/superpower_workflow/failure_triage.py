"""Failure Triage Classifier v1.3.21 — pure-functional rule-only classifier.

Reads existing telemetry / audit / state — emits no new instrumentation
beyond `ClaudeInvocationFailed` (added to runner.py to give rules 08/09
a typed surface instead of regex-on-free-text).

Design provenance: 3-architect + 3-verdict workflow (wor666rq9). The
rule-only proposal scored 39/60 vs runners-up 18/16 (both rejected).
Winner required 6 adversarial revisions, all baked into this module:

1. Synthetic-fixture corpus + golden-replay test as ground truth (the
   narrative IS the spec; no labels needed).
2. Success criterion rewritten: P50 confidence >= 0.7; UNKNOWN <= 15%;
   evidence completeness; not "100% confidence" (impossible by design).
3. CLI scoped to 3 flags for v1; LOC revised honestly (1720, not 1250).
4. Independence rule for composite failures: a candidate secondary is
   appended iff (a) its trigger seq > primary's seq AND (b) it is not
   in the implication graph of the primary.
5. Typed ClaudeInvocationFailed in runner.py (load-bearing upstream fix)
   instead of regex-on-MilestoneFailed.reason downstream.
6. Hook budget revised: <=200ms with shared TelemetryReader cache.

The classifier is pure-functional — `classify_failure(anchor, bundle)`
takes data in, returns FailureTriaged. No I/O inside. No mutation. No
hidden state. Deterministic byte-identical output on identical input.

`classify_run(telemetry_path, ...)` is the offline replay entry point
used by `sw triage` CLI. The orchestrator hook (hooks/triage_hook.py)
is the online path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

# ---- enums ----


class FailureClass(StrEnum):
    """14 primary failure classes + UNKNOWN fallback."""

    COST_CEILING_BLOCKED = "cost_ceiling_blocked"
    BUDGET_EXCEEDED = "budget_exceeded"
    MERGE_CONFLICT = "merge_conflict"
    PLUGIN_VETO = "plugin_veto"
    POLICY_VIOLATION = "policy_violation"
    COVERAGE_BELOW_THRESHOLD = "coverage_below_threshold"
    QUALITY_GATE_FAIL = "quality_gate_fail"
    CLAUDE_SUBPROCESS_TIMEOUT = "claude_subprocess_timeout"
    CLAUDE_SUBPROCESS_ERROR = "claude_subprocess_error"
    STRICT_MODE_NON_CONVERGE = "strict_mode_non_converge"
    SPEC_FEATURE_GAP = "spec_feature_gap"
    GAP_NON_CONVERGE = "gap_non_converge"
    CI_FIX_FAIL = "ci_fix_fail"
    UNKNOWN = "unknown"


# Secondary tags never appear as primary; they correlate but don't cause.
SECONDARY_TAG_DRIFT = "drift_correlated"


# ---- evidence + result types ----


@dataclass(frozen=True)
class EvidenceTriple:
    seq: int
    event_type: str
    detail: str  # e.g. "gate=lint:passed=false"

    def render(self) -> str:
        return f"seq={self.seq}:type={self.event_type}:{self.detail}"


@dataclass(frozen=True)
class RuleMatch:
    """Returned by a rule's predicate. None = no match."""

    primary: FailureClass
    confidence: float
    evidence: tuple[EvidenceTriple, ...]
    trigger_seq: int  # earliest matching signal seq, used for independence rule


@dataclass
class BundleWindow:
    """Events with same run_id + milestone, seq <= anchor.seq."""

    anchor: dict
    events: list[dict] = field(default_factory=list)
    audit_entries: list[dict] = field(default_factory=list)
    state_snapshot: dict | None = None

    def events_of(self, event_type: str) -> list[dict]:
        return [e for e in self.events if e.get("type") == event_type]

    def audit_of(self, event: str) -> list[dict]:
        return [a for a in self.audit_entries if a.get("event") == event]


@dataclass(frozen=True)
class TriageResult:
    """The classify_failure output, pre-serialization to FailureTriaged."""

    milestone: str
    phase: str
    primary_class: FailureClass
    secondary_classes: tuple[str, ...]
    confidence: float
    evidence: tuple[str, ...]
    recommendation: str
    anchor_seq: int
    anchor_type: str
    raw_reason: str = ""


# ---- recommendation lookup table ----


RECOMMENDATIONS: dict[FailureClass, str] = {
    FailureClass.COST_CEILING_BLOCKED: (
        "Inspect window spend via `sw budget show`. Widen the ceiling or wait "
        "for the rolling window to free up. Override only with --ignore-ceiling "
        "+ SW_ALLOW_CEILING_BYPASS=1 (audit-logged)."
    ),
    FailureClass.BUDGET_EXCEEDED: (
        "Per-run hard cap hit. Inspect retry storm in evidence chain. Lower "
        "model complexity, split the milestone, or raise max_total_budget_usd."
    ),
    FailureClass.MERGE_CONFLICT: (
        "Resolve conflicts in the milestone branch, then `sw resume`. If "
        "parallel-wave milestones touched the same files, consider serializing."
    ),
    FailureClass.PLUGIN_VETO: (
        "Check the plugin's veto reason. Fix the underlying condition or "
        "disable the plugin for this milestone via `--skip-plugin <name>`."
    ),
    FailureClass.POLICY_VIOLATION: (
        "Read violation detail in the audit trail. Fix the policy infraction "
        "or file an exception in policy.yaml. Don't bypass without review."
    ),
    FailureClass.COVERAGE_BELOW_THRESHOLD: (
        "Add targeted tests to the milestone's modules. If the threshold is "
        "unrealistic, adjust workflow.json — don't lower coverage to chase green."
    ),
    FailureClass.QUALITY_GATE_FAIL: (
        "Open the failing gate's detail (lint/sast/secret/dep_scan). Fix "
        "locally and `sw resume`. If recurring, consider threshold or "
        "false-positive suppression."
    ),
    FailureClass.CLAUDE_SUBPROCESS_TIMEOUT: (
        "Verify network/MCP server health. `sw resume`. If reproducible, "
        "raise runner.timeout_seconds for the phase or chunk the prompt."
    ),
    FailureClass.CLAUDE_SUBPROCESS_ERROR: (
        "Inspect .claude/.workflow.log stderr. Common: MCP crash, API auth, "
        "transient 5xx. Resume after fixing root cause."
    ),
    FailureClass.STRICT_MODE_NON_CONVERGE: (
        "Inspect missing_requirements / broken_features from the last iteration. "
        "Decompose the milestone further or relax spec scope."
    ),
    FailureClass.SPEC_FEATURE_GAP: (
        "List missing reqs / broken features via `sw triage --milestone <name>`. "
        "Add a targeted follow-up milestone."
    ),
    FailureClass.GAP_NON_CONVERGE: (
        "Inspect .claude/.gap-report.json. Critical gaps that survived multiple "
        "passes likely need human triage or strict-mode re-run."
    ),
    FailureClass.CI_FIX_FAIL: (
        "Inspect the failing CI step in .claude/.workflow.log. Re-run CI "
        "locally with the same workflow YAML."
    ),
    FailureClass.UNKNOWN: (
        "Read raw reason in evidence. If pattern recurs, add a rule to "
        "`failure_triage.RULES` (one-line PR)."
    ),
}


# ---- independence graph ----
# Maps a primary class to other classes it IMPLIES (which therefore
# must NOT appear as secondary even if their trigger fires). Designed
# to keep composite output deterministic.

IMPLIES: dict[FailureClass, frozenset[FailureClass]] = {
    # Policy violation at a QG checkpoint implies the QG fail.
    FailureClass.POLICY_VIOLATION: frozenset({FailureClass.QUALITY_GATE_FAIL}),
    # Strict-mode non-converge usually implies a spec gap (it's WHY
    # strict mode ran), so we don't double-tag.
    FailureClass.STRICT_MODE_NON_CONVERGE: frozenset({FailureClass.SPEC_FEATURE_GAP}),
    # Gap non-converge upstream of strict mode → don't double-tag.
    FailureClass.GAP_NON_CONVERGE: frozenset({FailureClass.STRICT_MODE_NON_CONVERGE}),
    # Subprocess errors at end of retry chain may also have caused
    # a budget exceeded — but cost ceiling/budget are user-config
    # decisions and we always surface them.
    FailureClass.CLAUDE_SUBPROCESS_TIMEOUT: frozenset(),
    FailureClass.CLAUDE_SUBPROCESS_ERROR: frozenset(),
}


# ---- rules ----


@dataclass(frozen=True)
class Rule:
    """A single classification rule.

    Rules are evaluated in REGISTRATION ORDER. The first rule whose
    predicate returns a RuleMatch wins `primary_class`. Subsequent
    rules' matches may become secondary classes per the independence
    graph.
    """

    id: str
    primary: FailureClass
    predicate: Callable[[BundleWindow], RuleMatch | None]


def _ev(event: dict, detail: str) -> EvidenceTriple:
    return EvidenceTriple(
        seq=int(event.get("seq", 0)),
        event_type=event.get("type", "unknown"),
        detail=detail,
    )


# --- rule_01: COST_CEILING_BLOCKED ---


def _rule_01(bundle: BundleWindow) -> RuleMatch | None:
    """CostCeilingBlocked event OR CEILING_BLOCK audit entry."""
    events = bundle.events_of("cost_ceiling_blocked")
    if events:
        ev = events[0]
        return RuleMatch(
            primary=FailureClass.COST_CEILING_BLOCKED,
            confidence=1.0,
            evidence=(
                _ev(ev, f"window={ev.get('window', '?')}:gate={ev.get('preflight_gate', '?')}"),
            ),
            trigger_seq=int(ev.get("seq", 0)),
        )
    audits = bundle.audit_of("CEILING_BLOCK")
    if audits:
        a = audits[0]
        data = a.get("data", {}) or {}
        return RuleMatch(
            primary=FailureClass.COST_CEILING_BLOCKED,
            confidence=1.0,
            evidence=(
                EvidenceTriple(
                    seq=int(a.get("seq", 0)),
                    event_type="audit.CEILING_BLOCK",
                    detail=f"window={data.get('window', '?')}",
                ),
            ),
            trigger_seq=int(a.get("seq", 0)),
        )
    return None


# --- rule_02: BUDGET_EXCEEDED ---


def _rule_02(bundle: BundleWindow) -> RuleMatch | None:
    """BudgetAlert with threshold=100."""
    for ev in bundle.events_of("budget_alert"):
        if int(ev.get("threshold", 0)) == 100:
            return RuleMatch(
                primary=FailureClass.BUDGET_EXCEEDED,
                confidence=1.0,
                evidence=(
                    _ev(
                        ev,
                        f"threshold=100:spent={ev.get('current_spent_usd', 0):.2f}",
                    ),
                ),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_03: MERGE_CONFLICT ---


def _rule_03(bundle: BundleWindow) -> RuleMatch | None:
    for ev in bundle.events_of("worktree_merged"):
        success = bool(ev.get("success", True))
        conflicts = int(ev.get("conflicts", 0))
        if not success or conflicts > 0:
            return RuleMatch(
                primary=FailureClass.MERGE_CONFLICT,
                confidence=1.0,
                evidence=(_ev(ev, f"success={success}:conflicts={conflicts}"),),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_04: PLUGIN_VETO ---


def _rule_04(bundle: BundleWindow) -> RuleMatch | None:
    anchor_phase = bundle.anchor.get("phase", "")
    for ev in bundle.events_of("plugin_vetoed"):
        ev_phase = ev.get("phase", "")
        if not anchor_phase or ev_phase == anchor_phase:
            return RuleMatch(
                primary=FailureClass.PLUGIN_VETO,
                confidence=1.0,
                evidence=(
                    _ev(
                        ev,
                        f"plugin={ev.get('plugin_name', '?')}:phase={ev_phase}",
                    ),
                ),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_05: POLICY_VIOLATION ---


def _rule_05(bundle: BundleWindow) -> RuleMatch | None:
    for a in bundle.audit_of("POLICY_VIOLATION"):
        data = a.get("data", {}) or {}
        checkpoint = data.get("checkpoint", "?")
        return RuleMatch(
            primary=FailureClass.POLICY_VIOLATION,
            confidence=1.0,
            evidence=(
                EvidenceTriple(
                    seq=int(a.get("seq", 0)),
                    event_type="audit.POLICY_VIOLATION",
                    detail=f"checkpoint={checkpoint}",
                ),
            ),
            trigger_seq=int(a.get("seq", 0)),
        )
    return None


# --- rule_06: COVERAGE_BELOW_THRESHOLD ---


def _rule_06(bundle: BundleWindow) -> RuleMatch | None:
    for ev in bundle.events_of("coverage_result"):
        if not bool(ev.get("passed", True)):
            return RuleMatch(
                primary=FailureClass.COVERAGE_BELOW_THRESHOLD,
                confidence=1.0,
                evidence=(
                    _ev(
                        ev,
                        f"pct={ev.get('coverage_pct', 0):.2f}:threshold={ev.get('threshold', 0):.2f}",
                    ),
                ),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_07: QUALITY_GATE_FAIL ---


def _rule_07(bundle: BundleWindow) -> RuleMatch | None:
    for ev in bundle.events_of("quality_gate_result"):
        if not bool(ev.get("passed", True)):
            return RuleMatch(
                primary=FailureClass.QUALITY_GATE_FAIL,
                confidence=1.0,
                evidence=(
                    _ev(
                        ev,
                        f"gate={ev.get('gate', '?')}:checkpoint={ev.get('checkpoint', '?')}",
                    ),
                ),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_08: CLAUDE_SUBPROCESS_TIMEOUT ---


def _rule_08(bundle: BundleWindow) -> RuleMatch | None:
    """Typed event preferred (verdict revision #5). Falls back to regex only
    if no ClaudeInvocationFailed exists in bundle."""
    for ev in bundle.events_of("claude_invocation_failed"):
        kind = ev.get("error_kind", "")
        if kind == "timeout":
            return RuleMatch(
                primary=FailureClass.CLAUDE_SUBPROCESS_TIMEOUT,
                confidence=1.0,
                evidence=(
                    _ev(
                        ev,
                        f"error_kind=timeout:attempts={ev.get('attempt', 0)}/{ev.get('max_attempts', 0)}",
                    ),
                ),
                trigger_seq=int(ev.get("seq", 0)),
            )
    # Legacy fallback: regex on anchor.reason. Lower confidence.
    reason = str(bundle.anchor.get("reason", ""))
    if re.search(r"timed out|timeout", reason, re.IGNORECASE):
        return RuleMatch(
            primary=FailureClass.CLAUDE_SUBPROCESS_TIMEOUT,
            confidence=0.7,
            evidence=(
                EvidenceTriple(
                    seq=int(bundle.anchor.get("seq", 0)),
                    event_type="legacy.reason_regex",
                    detail=f"pattern=timeout:match={reason[:60]!r}",
                ),
            ),
            trigger_seq=int(bundle.anchor.get("seq", 0)),
        )
    return None


# --- rule_09: CLAUDE_SUBPROCESS_ERROR ---


def _rule_09(bundle: BundleWindow) -> RuleMatch | None:
    for ev in bundle.events_of("claude_invocation_failed"):
        kind = ev.get("error_kind", "")
        if kind in {"is_error", "nonzero_exit", "mcp_crash", "auth"}:
            return RuleMatch(
                primary=FailureClass.CLAUDE_SUBPROCESS_ERROR,
                confidence=0.7,
                evidence=(
                    _ev(
                        ev,
                        f"error_kind={kind}:returncode={ev.get('returncode', 0)}",
                    ),
                ),
                trigger_seq=int(ev.get("seq", 0)),
            )
    reason = str(bundle.anchor.get("reason", ""))
    if re.search(r"returncode|non-zero exit|is_error", reason, re.IGNORECASE):
        return RuleMatch(
            primary=FailureClass.CLAUDE_SUBPROCESS_ERROR,
            confidence=0.4,
            evidence=(
                EvidenceTriple(
                    seq=int(bundle.anchor.get("seq", 0)),
                    event_type="legacy.reason_regex",
                    detail=f"pattern=error:match={reason[:60]!r}",
                ),
            ),
            trigger_seq=int(bundle.anchor.get("seq", 0)),
        )
    return None


# --- rule_10: STRICT_MODE_NON_CONVERGE ---


def _rule_10(bundle: BundleWindow) -> RuleMatch | None:
    for ev in bundle.events_of("strict_mode_iteration"):
        max_iter = int(ev.get("max_iterations", 0) or ev.get("iteration_budget", 0))
        iter_num = int(ev.get("iteration", 0))
        converged = bool(ev.get("converged", False))
        if max_iter > 0 and iter_num >= max_iter and not converged:
            return RuleMatch(
                primary=FailureClass.STRICT_MODE_NON_CONVERGE,
                confidence=1.0,
                evidence=(_ev(ev, f"iter={iter_num}/{max_iter}:converged=false"),),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_11: SPEC_FEATURE_GAP ---


def _rule_11(bundle: BundleWindow) -> RuleMatch | None:
    for ev in bundle.events_of("spec_compliance_completed"):
        if int(ev.get("missing", 0)) > 0:
            return RuleMatch(
                primary=FailureClass.SPEC_FEATURE_GAP,
                confidence=1.0,
                evidence=(_ev(ev, f"missing={ev.get('missing', 0)}"),),
                trigger_seq=int(ev.get("seq", 0)),
            )
    for ev in bundle.events_of("feature_verification_completed"):
        if int(ev.get("broken", 0)) > 0:
            return RuleMatch(
                primary=FailureClass.SPEC_FEATURE_GAP,
                confidence=1.0,
                evidence=(_ev(ev, f"broken={ev.get('broken', 0)}"),),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_12: GAP_NON_CONVERGE ---


def _rule_12(bundle: BundleWindow) -> RuleMatch | None:
    for ev in bundle.events_of("gap_report"):
        if ev.get("phase") == "review" and not bool(ev.get("converged", True)):
            return RuleMatch(
                primary=FailureClass.GAP_NON_CONVERGE,
                confidence=0.7,
                evidence=(
                    _ev(
                        ev,
                        f"phase=review:critical={ev.get('critical_gaps', 0)}",
                    ),
                ),
                trigger_seq=int(ev.get("seq", 0)),
            )
    return None


# --- rule_13: CI_FIX_FAIL ---


def _rule_13(bundle: BundleWindow) -> RuleMatch | None:
    reason = str(bundle.anchor.get("reason", ""))
    if "CI_FIX_FAILED" in reason or "ci_fix_failed" in reason:
        return RuleMatch(
            primary=FailureClass.CI_FIX_FAIL,
            confidence=1.0,
            evidence=(
                EvidenceTriple(
                    seq=int(bundle.anchor.get("seq", 0)),
                    event_type="anchor.reason",
                    detail="match=CI_FIX_FAILED",
                ),
            ),
            trigger_seq=int(bundle.anchor.get("seq", 0)),
        )
    state = bundle.state_snapshot or {}
    if state.get("current_step") == "ci_fix_failed":
        return RuleMatch(
            primary=FailureClass.CI_FIX_FAIL,
            confidence=1.0,
            evidence=(
                EvidenceTriple(
                    seq=int(bundle.anchor.get("seq", 0)),
                    event_type="state.json",
                    detail="current_step=ci_fix_failed",
                ),
            ),
            trigger_seq=int(bundle.anchor.get("seq", 0)),
        )
    return None


RULES: tuple[Rule, ...] = (
    Rule(id="rule_01", primary=FailureClass.COST_CEILING_BLOCKED, predicate=_rule_01),
    Rule(id="rule_02", primary=FailureClass.BUDGET_EXCEEDED, predicate=_rule_02),
    Rule(id="rule_03", primary=FailureClass.MERGE_CONFLICT, predicate=_rule_03),
    Rule(id="rule_04", primary=FailureClass.PLUGIN_VETO, predicate=_rule_04),
    Rule(id="rule_05", primary=FailureClass.POLICY_VIOLATION, predicate=_rule_05),
    Rule(id="rule_06", primary=FailureClass.COVERAGE_BELOW_THRESHOLD, predicate=_rule_06),
    Rule(id="rule_07", primary=FailureClass.QUALITY_GATE_FAIL, predicate=_rule_07),
    Rule(id="rule_08", primary=FailureClass.CLAUDE_SUBPROCESS_TIMEOUT, predicate=_rule_08),
    Rule(id="rule_09", primary=FailureClass.CLAUDE_SUBPROCESS_ERROR, predicate=_rule_09),
    Rule(id="rule_10", primary=FailureClass.STRICT_MODE_NON_CONVERGE, predicate=_rule_10),
    Rule(id="rule_11", primary=FailureClass.SPEC_FEATURE_GAP, predicate=_rule_11),
    Rule(id="rule_12", primary=FailureClass.GAP_NON_CONVERGE, predicate=_rule_12),
    Rule(id="rule_13", primary=FailureClass.CI_FIX_FAIL, predicate=_rule_13),
)


# ---- secondary tag detection ----


def _drift_correlated(bundle: BundleWindow) -> EvidenceTriple | None:
    """DRIFT_CORRELATED secondary — never primary, always advisory."""
    for ev in bundle.events_of("drift_detected"):
        if ev.get("severity") == "critical" and ev.get("metric") in {
            "cost_usd",
            "duration_ms",
        }:
            return _ev(ev, f"metric={ev.get('metric')}:severity=critical")
    return None


# ---- main classifier ----


def classify_failure(
    anchor: dict,
    bundle: BundleWindow,
) -> TriageResult:
    """Pure-function: anchor + bundle in, TriageResult out.

    Walks RULES in registration order. First match wins primary. Subsequent
    matches qualify as secondary iff:
    - trigger_seq > primary.trigger_seq  AND
    - candidate not in IMPLIES[primary]
    Pre-anchor seq order makes this deterministic regardless of dict order.
    """
    matches: list[tuple[Rule, RuleMatch]] = []
    for rule in RULES:
        m = rule.predicate(bundle)
        if m is not None:
            matches.append((rule, m))

    milestone = str(anchor.get("milestone", ""))
    phase = str(anchor.get("phase", ""))
    anchor_seq = int(anchor.get("seq", 0))
    anchor_type = str(anchor.get("type", ""))

    if not matches:
        # rule_99 fallback → UNKNOWN. Drift can still attach as a secondary
        # advisory tag (drift is always correlation, never cause — but
        # surfacing it tells the user "this anomalous run might have
        # contributed to the unclassifiable failure").
        raw = str(anchor.get("reason", ""))[:300]
        evidence_rendered = [
            EvidenceTriple(
                seq=anchor_seq,
                event_type=anchor_type,
                detail=f"reason={raw[:60]!r}",
            ).render()
        ]
        secondary: list[str] = []
        drift_evidence = _drift_correlated(bundle)
        if drift_evidence is not None:
            secondary.append(SECONDARY_TAG_DRIFT)
            evidence_rendered.append(drift_evidence.render())
        return TriageResult(
            milestone=milestone,
            phase=phase,
            primary_class=FailureClass.UNKNOWN,
            secondary_classes=tuple(secondary),
            confidence=0.4,
            evidence=tuple(evidence_rendered),
            recommendation=RECOMMENDATIONS[FailureClass.UNKNOWN],
            anchor_seq=anchor_seq,
            anchor_type=anchor_type,
            raw_reason=raw,
        )

    primary_rule, primary_match = matches[0]
    implied = IMPLIES.get(primary_match.primary, frozenset())

    secondary: list[str] = []
    for _rule, m in matches[1:]:
        if m.primary in implied:
            continue
        if m.trigger_seq <= primary_match.trigger_seq:
            continue
        secondary.append(m.primary.value)

    # DRIFT_CORRELATED tag (never primary).
    drift_evidence = _drift_correlated(bundle)
    if drift_evidence is not None:
        secondary.append(SECONDARY_TAG_DRIFT)

    evidence_rendered = [t.render() for t in primary_match.evidence]
    if drift_evidence is not None:
        evidence_rendered.append(drift_evidence.render())

    return TriageResult(
        milestone=milestone,
        phase=phase,
        primary_class=primary_match.primary,
        secondary_classes=tuple(secondary),
        confidence=primary_match.confidence,
        evidence=tuple(evidence_rendered),
        recommendation=RECOMMENDATIONS[primary_match.primary],
        anchor_seq=anchor_seq,
        anchor_type=anchor_type,
        raw_reason="",
    )


# ---- run-level entry point ----

ANCHOR_TYPES: frozenset[str] = frozenset(
    {
        "milestone_failed",
        "cost_ceiling_blocked",
    }
)


def classify_run(
    telemetry_path: Path,
    audit_path: Path | None = None,
    state_path: Path | None = None,
) -> list[TriageResult]:
    """Offline replay: walk telemetry.jsonl, find anchors, classify each.

    Reads files ONCE. Skips bad JSON lines. Auto-assigns synthetic `seq`
    if events don't have one (real telemetry doesn't currently emit seq;
    we use enumeration order as a proxy that's stable within a single file).
    """
    events = _read_jsonl(telemetry_path)
    audit_entries = _read_jsonl(audit_path) if audit_path else []
    state = _read_json(state_path) if state_path else None

    # Assign synthetic seq if absent.
    for i, ev in enumerate(events):
        ev.setdefault("seq", i)
    for i, a in enumerate(audit_entries):
        a.setdefault("seq", i)

    # Group events by run_id+milestone for bundle lookup.
    results: list[TriageResult] = []
    for anchor in events:
        if anchor.get("type") not in ANCHOR_TYPES:
            continue
        # ParallelWaveCompleted can have failed[] entries → multiple anchors.
        # Handled by anchor-type filter above; PWC is not an anchor type
        # because each failed milestone gets its own MilestoneFailed.
        bundle = _build_bundle(anchor, events, audit_entries, state)
        results.append(classify_failure(anchor, bundle))
    return results


def _build_bundle(
    anchor: dict,
    all_events: list[dict],
    all_audit: list[dict],
    state: dict | None,
) -> BundleWindow:
    run_id = anchor.get("run_id", "")
    milestone = anchor.get("milestone", "")
    anchor_seq = int(anchor.get("seq", 0))

    events = []
    for ev in all_events:
        if int(ev.get("seq", 0)) > anchor_seq:
            continue
        if ev.get("run_id", "") != run_id:
            continue
        ms = ev.get("milestone", "")
        # Some events (cost_ceiling_blocked at run_start) have no milestone;
        # include them when anchor has no milestone OR when they're flagged
        # to this anchor's milestone via blocked_milestone field.
        if ms and milestone and ms != milestone:
            blocked = ev.get("blocked_milestone", "")
            if blocked != milestone:
                continue
        events.append(ev)

    audit = []
    for a in all_audit:
        if int(a.get("seq", 0)) > anchor_seq:
            continue
        if a.get("run_id", "") != run_id:
            continue
        ms = a.get("milestone", "")
        if ms and milestone and ms != milestone:
            continue
        audit.append(a)

    return BundleWindow(
        anchor=anchor,
        events=events,
        audit_entries=audit,
        state_snapshot=state,
    )


def _read_jsonl(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _read_json(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---- helpers used by the CLI / hook ----


def to_event_dict(result: TriageResult, *, run_id: str = "") -> dict[str, Any]:
    """Render TriageResult as the FailureTriaged JSONL payload."""
    return {
        "type": "failure_triaged",
        "run_id": run_id,
        "milestone": result.milestone,
        "phase": result.phase,
        "primary_class": result.primary_class.value,
        "secondary_classes": list(result.secondary_classes),
        "confidence": result.confidence,
        "evidence": list(result.evidence),
        "recommendation": result.recommendation,
        "anchor_seq": result.anchor_seq,
        "anchor_type": result.anchor_type,
        "triage_version": 1,
        "raw_reason": result.raw_reason,
    }


def summarize(results: list[TriageResult]) -> dict[str, Any]:
    """Aggregate statistics for the CLI `--json` summary block."""
    if not results:
        return {
            "total_failures": 0,
            "unknown_count": 0,
            "unknown_pct": 0.0,
            "p50_confidence": 0.0,
        }
    unknown = sum(1 for r in results if r.primary_class == FailureClass.UNKNOWN)
    confs = sorted(r.confidence for r in results)
    p50 = confs[len(confs) // 2]
    return {
        "total_failures": len(results),
        "unknown_count": unknown,
        "unknown_pct": round(unknown / len(results), 4),
        "p50_confidence": p50,
    }
