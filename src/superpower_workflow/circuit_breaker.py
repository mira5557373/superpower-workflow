"""Classed Circuit Breaker v1.3.26 — class-aware run-level fail-fast.

Replaces the class-blind `consecutive_failures >= 3` counter with a
class-aware accumulator that consumes existing FailureTriaged events
from the v1.3.21 triage classifier. Two trip rules:

1. **same_class_repeat**: N back-to-back failures of the same FailureClass
   trip the breaker. N per-class; deterministic classes (policy,
   coverage, ceiling) default to 2; transient classes (timeout, error)
   default to 3.
2. **diversity_overflow**: legacy 3-in-5 safety net preserved — if any
   3 of the last 5 milestones failed regardless of class, trip.

Ships **observation_only by default**: rules accumulate "would-have-
tripped" telemetry against real runs before being promoted to enforced.
After enough real-run data validates the trip rules, a future release
flips the default to enforced.

Design provenance: 4-architect + 4-verdict workflow (wf7eg1t2g). Winner
scored 46/60. Six adversarial revisions baked in:

1. Per-FailureClass thresholds (deterministic=2, transient=3); table
   exposed in `circuit_breaker.same_class_thresholds`.
2. WorkflowState backward-compat (missing `breaker_window` → empty list).
3. v1 scope trimmed — `sw breaker` CLI + golden snapshot deferred to v1.1.
4. Low-confidence triage (< 0.7) does NOT advance same-class counter.
5. Layered explicitly with the milestone-level retry loop — breaker
   decides whether NEXT milestone runs; retry loop is unchanged.
6. observation_only flip plan: after N=10 same-class trips observed
   with zero retry-recovers in between, flip to enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ---- enums ----


class BreakerAction(StrEnum):
    CONTINUE = "continue"
    TRIP_OBSERVED = "trip_observed"  # observation_only=True
    TRIP_ENFORCED = "trip_enforced"  # observation_only=False


class TripRule(StrEnum):
    SAME_CLASS_REPEAT = "same_class_repeat"
    DIVERSITY_OVERFLOW = "diversity_overflow"
    NONE = "none"


# ---- data ----


@dataclass(frozen=True)
class BreakerWindowEntry:
    """One entry in the rolling failure window."""

    milestone_name: str
    primary_class: str  # FailureClass.value, or "" if no triage available
    confidence: float
    triage_event_id: str
    ts: str


@dataclass(frozen=True)
class BreakerConfig:
    """Configuration for the breaker. Built from workflow.json[circuit_breaker]."""

    enabled: bool = True
    observation_only: bool = True
    diversity_window: int = 5
    diversity_threshold: int = 3
    confidence_floor: float = 0.7
    # Per-FailureClass trip thresholds. Deterministic classes at 2,
    # transient classes at 3. Unmapped classes use
    # default_same_class_threshold.
    same_class_thresholds: dict[str, int] = field(
        default_factory=lambda: {
            # Deterministic — fix the underlying cause, don't retry
            "policy_violation": 2,
            "coverage_below_threshold": 2,
            "cost_ceiling_blocked": 2,
            "budget_exceeded": 2,
            "strict_mode_non_converge": 2,
            "merge_conflict": 2,
            "spec_feature_gap": 2,
            "quality_gate_fail": 2,
            "plugin_veto": 2,
            "ci_fix_fail": 2,
            # Transient — preserve legacy 3-strike behavior
            "claude_subprocess_timeout": 3,
            "claude_subprocess_error": 3,
            "gap_non_converge": 3,
            # UNKNOWN intentionally absent — never trips same-class rule
        }
    )
    default_same_class_threshold: int = 3


REMEDIATION_TABLE: dict[str, str] = {
    "policy_violation": "Fix policy infractions in code or update policy.yaml exceptions.",
    "coverage_below_threshold": "Add targeted tests; do not lower coverage threshold to chase green.",
    "cost_ceiling_blocked": "Inspect `sw budget show` — widen ceiling or wait for window to clear.",
    "budget_exceeded": "Per-run hard cap repeatedly hit — split milestones or raise budget.",
    "strict_mode_non_converge": (
        "Strict mode looped to max iter twice — decompose milestone or relax spec scope."
    ),
    "merge_conflict": "Resolve git conflicts; consider serializing parallel-wave milestones.",
    "spec_feature_gap": "Missing requirements documented; add follow-up milestone.",
    "quality_gate_fail": "Fix failing gate (lint/sast/secret/dep_scan) before continuing.",
    "plugin_veto": "Plugin repeatedly vetoed; fix underlying condition or skip-plugin.",
    "claude_subprocess_timeout": (
        "Verify network/MCP health. Raise runner.timeout for the phase or chunk the prompt."
    ),
    "claude_subprocess_error": (
        "Inspect .claude/.workflow.log stderr. Common: MCP crash, API auth, 5xx."
    ),
    "ci_fix_fail": "Re-run CI locally with same workflow YAML to isolate the failure.",
    "gap_non_converge": "Critical gaps survived multiple passes; needs human triage.",
}


@dataclass(frozen=True)
class Decision:
    """Output of `evaluate`. action determines what the orchestrator does."""

    action: BreakerAction
    rule_matched: TripRule
    primary_class: str | None
    window: list[BreakerWindowEntry]
    remediation_hint: str | None
    counter_snapshot: dict[str, int]


# ---- helpers ----


def parse_config(raw: dict | None) -> BreakerConfig:
    """Parse circuit_breaker block from workflow.json (no pydantic)."""
    if not raw:
        return BreakerConfig()
    return BreakerConfig(
        enabled=bool(raw.get("enabled", True)),
        observation_only=bool(raw.get("observation_only", True)),
        diversity_window=int(raw.get("diversity_window", 5)),
        diversity_threshold=int(raw.get("diversity_threshold", 3)),
        confidence_floor=float(raw.get("confidence_floor", 0.7)),
        same_class_thresholds=dict(
            raw.get("same_class_thresholds", BreakerConfig().same_class_thresholds)
        ),
        default_same_class_threshold=int(raw.get("default_same_class_threshold", 3)),
    )


def _count_consecutive_same_class(
    window: list[BreakerWindowEntry], target_class: str, confidence_floor: float
) -> int:
    """Walk back from the most-recent entry counting consecutive same-class
    failures whose confidence >= confidence_floor.

    UNKNOWN class is never counted (returns 0).
    """
    if not target_class or target_class == "unknown":
        return 0
    n = 0
    for entry in reversed(window):
        if entry.primary_class != target_class:
            break
        if entry.confidence < confidence_floor:
            # Don't advance counter, but also stop walking — a low-conf
            # failure breaks the consecutive chain.
            break
        n += 1
    return n


# ---- public evaluator ----


def evaluate(
    window: list[BreakerWindowEntry],
    *,
    new_entry: BreakerWindowEntry | None,
    config: BreakerConfig,
) -> Decision:
    """Pure-function decision.

    Caller appends `new_entry` to the window AFTER calling evaluate.
    `evaluate` itself does NOT mutate state — it computes the outcome
    of HYPOTHETICALLY adding the new entry, so the orchestrator can
    decide based on the result.

    Returns CONTINUE when:
    - `config.enabled` is False
    - new_entry is None (no failure)
    - neither trip rule matches

    Returns TRIP_OBSERVED when a rule matches AND observation_only=True.
    Returns TRIP_ENFORCED when a rule matches AND observation_only=False.
    """
    snapshot: dict[str, int] = {}
    for entry in window:
        snapshot[entry.primary_class] = snapshot.get(entry.primary_class, 0) + 1
    if new_entry is not None:
        snapshot[new_entry.primary_class] = snapshot.get(new_entry.primary_class, 0) + 1

    if not config.enabled or new_entry is None:
        return Decision(
            action=BreakerAction.CONTINUE,
            rule_matched=TripRule.NONE,
            primary_class=None,
            window=window,
            remediation_hint=None,
            counter_snapshot=snapshot,
        )

    # Same-class rule.
    hypothetical = list(window) + [new_entry]
    target_class = new_entry.primary_class
    same_class_count = _count_consecutive_same_class(
        hypothetical, target_class, config.confidence_floor
    )
    threshold = config.same_class_thresholds.get(target_class, config.default_same_class_threshold)
    if target_class and target_class != "unknown" and same_class_count >= threshold:
        action = (
            BreakerAction.TRIP_OBSERVED if config.observation_only else BreakerAction.TRIP_ENFORCED
        )
        return Decision(
            action=action,
            rule_matched=TripRule.SAME_CLASS_REPEAT,
            primary_class=target_class,
            window=hypothetical,
            remediation_hint=REMEDIATION_TABLE.get(target_class),
            counter_snapshot=snapshot,
        )

    # Diversity overflow (legacy 3-in-5). All entries in the window are
    # failures by definition; trip when window size hits threshold.
    diversity_slice = hypothetical[-config.diversity_window :]
    if len(diversity_slice) >= config.diversity_threshold:
        action = (
            BreakerAction.TRIP_OBSERVED
            if config.observation_only
            else BreakerAction.TRIP_ENFORCED
        )
        return Decision(
            action=action,
            rule_matched=TripRule.DIVERSITY_OVERFLOW,
            primary_class=target_class,
            window=hypothetical,
            remediation_hint=(
                "Multiple unrelated failures in last "
                f"{config.diversity_window} milestones — likely systemic. "
                "Inspect `sw triage --json` for the failure mix."
            ),
            counter_snapshot=snapshot,
        )

    return Decision(
        action=BreakerAction.CONTINUE,
        rule_matched=TripRule.NONE,
        primary_class=None,
        window=hypothetical,
        remediation_hint=None,
        counter_snapshot=snapshot,
    )


# Exit code for hard trip.
EXIT_CIRCUIT_BREAKER: int = 10
