"""Unit + integration tests for the v1.3.21 Failure Triage Classifier.

Each rule has its own test class. Composite-failure determinism and the
independence-graph rules are exercised explicitly. The "verification
without labels" strategy (verdict revision #1) is implemented via
hand-constructed synthetic fixtures: the test author writes a narrative
event sequence and an expected primary_class, and the test asserts the
classifier matches the expected output. The narrative IS the ground truth.
"""

from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.failure_triage import (
    IMPLIES,
    RECOMMENDATIONS,
    RULES,
    SECONDARY_TAG_DRIFT,
    BundleWindow,
    FailureClass,
    classify_failure,
    classify_run,
    summarize,
    to_event_dict,
)

# ---- helpers ----


def _seq_ev(seq: int, **fields) -> dict:
    """Build a telemetry event dict with seq + run_id stamped."""
    base = {"seq": seq, "run_id": "test-run", "milestone": "M1"}
    base.update(fields)
    return base


def _anchor_milestone_failed(seq: int, **fields) -> dict:
    return _seq_ev(seq, type="milestone_failed", **fields)


def _bundle(anchor: dict, events: list[dict], audit: list[dict] | None = None) -> BundleWindow:
    return BundleWindow(
        anchor=anchor,
        events=events,
        audit_entries=audit or [],
        state_snapshot=None,
    )


# ---- TestRule01: COST_CEILING_BLOCKED ----


class TestRule01CostCeilingBlocked:
    def test_event_only(self) -> None:
        anchor = _seq_ev(10, type="cost_ceiling_blocked", window="day")
        result = classify_failure(anchor, _bundle(anchor, [anchor]))
        assert result.primary_class == FailureClass.COST_CEILING_BLOCKED
        assert result.confidence == 1.0
        assert any("cost_ceiling_blocked" in e for e in result.evidence)

    def test_audit_only_no_event(self) -> None:
        """If telemetry was rotated but audit-trail kept, we still classify."""
        anchor = _anchor_milestone_failed(20, phase="implement")
        audit = [
            {
                "seq": 19,
                "event": "CEILING_BLOCK",
                "run_id": "test-run",
                "milestone": "M1",
                "data": {"window": "week"},
            }
        ]
        result = classify_failure(anchor, _bundle(anchor, [anchor], audit))
        assert result.primary_class == FailureClass.COST_CEILING_BLOCKED


# ---- TestRule02: BUDGET_EXCEEDED ----


class TestRule02BudgetExceeded:
    def test_threshold_100_triggers(self) -> None:
        anchor = _anchor_milestone_failed(10)
        budget = _seq_ev(5, type="budget_alert", threshold=100, current_spent_usd=50.0)
        result = classify_failure(anchor, _bundle(anchor, [budget, anchor]))
        assert result.primary_class == FailureClass.BUDGET_EXCEEDED
        assert result.confidence == 1.0

    def test_threshold_90_does_not_trigger(self) -> None:
        """Only the 100% threshold counts as 'exceeded'."""
        anchor = _anchor_milestone_failed(10, reason="something else")
        budget = _seq_ev(5, type="budget_alert", threshold=90)
        result = classify_failure(anchor, _bundle(anchor, [budget, anchor]))
        assert result.primary_class != FailureClass.BUDGET_EXCEEDED


# ---- TestRule03: MERGE_CONFLICT ----


class TestRule03MergeConflict:
    def test_success_false(self) -> None:
        anchor = _anchor_milestone_failed(10)
        merge = _seq_ev(8, type="worktree_merged", success=False, conflicts=0)
        result = classify_failure(anchor, _bundle(anchor, [merge, anchor]))
        assert result.primary_class == FailureClass.MERGE_CONFLICT

    def test_conflicts_gt_zero_even_if_success_true(self) -> None:
        anchor = _anchor_milestone_failed(10)
        merge = _seq_ev(8, type="worktree_merged", success=True, conflicts=2)
        result = classify_failure(anchor, _bundle(anchor, [merge, anchor]))
        assert result.primary_class == FailureClass.MERGE_CONFLICT

    def test_clean_merge_no_match(self) -> None:
        anchor = _anchor_milestone_failed(10, reason="other")
        merge = _seq_ev(8, type="worktree_merged", success=True, conflicts=0)
        result = classify_failure(anchor, _bundle(anchor, [merge, anchor]))
        assert result.primary_class != FailureClass.MERGE_CONFLICT


# ---- TestRule04: PLUGIN_VETO ----


class TestRule04PluginVeto:
    def test_phase_match_triggers(self) -> None:
        anchor = _anchor_milestone_failed(10, phase="implement")
        veto = _seq_ev(8, type="plugin_vetoed", plugin_name="secrets-policy", phase="implement")
        result = classify_failure(anchor, _bundle(anchor, [veto, anchor]))
        assert result.primary_class == FailureClass.PLUGIN_VETO

    def test_phase_mismatch_skips(self) -> None:
        anchor = _anchor_milestone_failed(10, phase="review", reason="x")
        veto = _seq_ev(8, type="plugin_vetoed", plugin_name="x", phase="plan")
        result = classify_failure(anchor, _bundle(anchor, [veto, anchor]))
        assert result.primary_class != FailureClass.PLUGIN_VETO


# ---- TestRule05: POLICY_VIOLATION ----


class TestRule05PolicyViolation:
    def test_audit_qg1(self) -> None:
        anchor = _anchor_milestone_failed(10)
        audit = [
            {
                "seq": 9,
                "event": "POLICY_VIOLATION",
                "run_id": "test-run",
                "milestone": "M1",
                "data": {"checkpoint": "QG1"},
            }
        ]
        result = classify_failure(anchor, _bundle(anchor, [anchor], audit))
        assert result.primary_class == FailureClass.POLICY_VIOLATION


# ---- TestRule06: COVERAGE_BELOW_THRESHOLD ----


class TestRule06CoverageBelow:
    def test_passed_false_triggers(self) -> None:
        anchor = _anchor_milestone_failed(10)
        cov = _seq_ev(
            8,
            type="coverage_result",
            passed=False,
            coverage_pct=72.5,
            threshold=85.0,
        )
        result = classify_failure(anchor, _bundle(anchor, [cov, anchor]))
        assert result.primary_class == FailureClass.COVERAGE_BELOW_THRESHOLD


# ---- TestRule07: QUALITY_GATE_FAIL ----


class TestRule07QualityGateFail:
    def test_lint_fail(self) -> None:
        anchor = _anchor_milestone_failed(10)
        qg = _seq_ev(
            8,
            type="quality_gate_result",
            gate="lint",
            checkpoint="QG2",
            passed=False,
        )
        result = classify_failure(anchor, _bundle(anchor, [qg, anchor]))
        assert result.primary_class == FailureClass.QUALITY_GATE_FAIL


# ---- TestRule08: CLAUDE_SUBPROCESS_TIMEOUT ----


class TestRule08SubprocessTimeout:
    def test_typed_event_high_confidence(self) -> None:
        anchor = _anchor_milestone_failed(10, phase="implement")
        cif = _seq_ev(
            7,
            type="claude_invocation_failed",
            error_kind="timeout",
            attempt=3,
            max_attempts=3,
        )
        result = classify_failure(anchor, _bundle(anchor, [cif, anchor]))
        assert result.primary_class == FailureClass.CLAUDE_SUBPROCESS_TIMEOUT
        assert result.confidence == 1.0

    def test_legacy_regex_fallback_lower_confidence(self) -> None:
        """No typed event → regex fallback at confidence 0.7."""
        anchor = _anchor_milestone_failed(10, reason="claude -p timed out after 600s")
        result = classify_failure(anchor, _bundle(anchor, [anchor]))
        assert result.primary_class == FailureClass.CLAUDE_SUBPROCESS_TIMEOUT
        assert result.confidence == 0.7


# ---- TestRule09: CLAUDE_SUBPROCESS_ERROR ----


class TestRule09SubprocessError:
    def test_is_error_kind(self) -> None:
        anchor = _anchor_milestone_failed(10)
        cif = _seq_ev(
            7,
            type="claude_invocation_failed",
            error_kind="is_error",
            returncode=1,
        )
        result = classify_failure(anchor, _bundle(anchor, [cif, anchor]))
        assert result.primary_class == FailureClass.CLAUDE_SUBPROCESS_ERROR
        assert result.confidence == 0.7


# ---- TestRule10: STRICT_MODE_NON_CONVERGE ----


class TestRule10StrictModeNonConverge:
    def test_max_iter_not_converged(self) -> None:
        anchor = _anchor_milestone_failed(10)
        strict = _seq_ev(
            8,
            type="strict_mode_iteration",
            iteration=3,
            max_iterations=3,
            converged=False,
        )
        result = classify_failure(anchor, _bundle(anchor, [strict, anchor]))
        assert result.primary_class == FailureClass.STRICT_MODE_NON_CONVERGE

    def test_max_iter_converged_does_not_trigger(self) -> None:
        anchor = _anchor_milestone_failed(10, reason="other")
        strict = _seq_ev(
            8,
            type="strict_mode_iteration",
            iteration=3,
            max_iterations=3,
            converged=True,
        )
        result = classify_failure(anchor, _bundle(anchor, [strict, anchor]))
        assert result.primary_class != FailureClass.STRICT_MODE_NON_CONVERGE


# ---- TestRule11: SPEC_FEATURE_GAP ----


class TestRule11SpecFeatureGap:
    def test_spec_compliance_missing(self) -> None:
        anchor = _anchor_milestone_failed(10)
        sc = _seq_ev(8, type="spec_compliance_completed", missing=2, total_requirements=10)
        result = classify_failure(anchor, _bundle(anchor, [sc, anchor]))
        assert result.primary_class == FailureClass.SPEC_FEATURE_GAP

    def test_feature_verification_broken(self) -> None:
        anchor = _anchor_milestone_failed(10)
        fv = _seq_ev(8, type="feature_verification_completed", broken=1, total_features=5)
        result = classify_failure(anchor, _bundle(anchor, [fv, anchor]))
        assert result.primary_class == FailureClass.SPEC_FEATURE_GAP


# ---- TestRule12: GAP_NON_CONVERGE ----


class TestRule12GapNonConverge:
    def test_phase_review_non_converged(self) -> None:
        anchor = _anchor_milestone_failed(10)
        gr = _seq_ev(
            8,
            type="gap_report",
            phase="review",
            converged=False,
            critical_gaps=2,
        )
        result = classify_failure(anchor, _bundle(anchor, [gr, anchor]))
        assert result.primary_class == FailureClass.GAP_NON_CONVERGE

    def test_phase_implement_does_not_trigger(self) -> None:
        anchor = _anchor_milestone_failed(10, reason="other")
        gr = _seq_ev(
            8,
            type="gap_report",
            phase="implement",
            converged=False,
            critical_gaps=2,
        )
        result = classify_failure(anchor, _bundle(anchor, [gr, anchor]))
        assert result.primary_class != FailureClass.GAP_NON_CONVERGE


# ---- TestRule13: CI_FIX_FAIL ----


class TestRule13CiFixFail:
    def test_reason_substring(self) -> None:
        anchor = _anchor_milestone_failed(10, reason="CI_FIX_FAILED after 2 attempts")
        result = classify_failure(anchor, _bundle(anchor, [anchor]))
        assert result.primary_class == FailureClass.CI_FIX_FAIL

    def test_state_current_step(self) -> None:
        anchor = _anchor_milestone_failed(10, reason="other")
        bundle = BundleWindow(
            anchor=anchor,
            events=[anchor],
            audit_entries=[],
            state_snapshot={"current_step": "ci_fix_failed"},
        )
        result = classify_failure(anchor, bundle)
        assert result.primary_class == FailureClass.CI_FIX_FAIL


# ---- TestUnknownFallback ----


class TestUnknownFallback:
    def test_no_match_returns_unknown(self) -> None:
        anchor = _anchor_milestone_failed(10, reason="opaque mystery thing happened")
        result = classify_failure(anchor, _bundle(anchor, [anchor]))
        assert result.primary_class == FailureClass.UNKNOWN
        assert result.confidence == 0.4
        assert "opaque mystery" in result.raw_reason

    def test_raw_reason_truncated_300(self) -> None:
        long_reason = "x" * 1000
        anchor = _anchor_milestone_failed(10, reason=long_reason)
        result = classify_failure(anchor, _bundle(anchor, [anchor]))
        assert len(result.raw_reason) == 300


# ---- TestComposite: verdict revision #4 ----


class TestCompositeFailureSemantics:
    def test_strict_coverage_qualitygate_deterministic(self) -> None:
        """Three independent signals → primary = first-matching rule;
        secondary = those with strictly later seq, NOT in IMPLIES[primary].

        Order in RULES: coverage (06) before quality_gate (07) before
        strict_mode (10). So coverage wins primary at seq=5; quality_gate
        at seq=7 is later and is NOT in IMPLIES[coverage], so it becomes
        secondary. strict_mode at seq=9 also later, not in implies,
        secondary. Stable across runs.
        """
        anchor = _anchor_milestone_failed(10)
        cov = _seq_ev(5, type="coverage_result", passed=False, coverage_pct=70.0, threshold=85.0)
        qg = _seq_ev(7, type="quality_gate_result", gate="lint", checkpoint="QG2", passed=False)
        strict = _seq_ev(
            9, type="strict_mode_iteration", iteration=3, max_iterations=3, converged=False
        )
        result = classify_failure(anchor, _bundle(anchor, [cov, qg, strict, anchor]))
        # Coverage wins primary.
        assert result.primary_class == FailureClass.COVERAGE_BELOW_THRESHOLD
        # Quality gate later seq, not implied by coverage → secondary.
        assert FailureClass.QUALITY_GATE_FAIL.value in result.secondary_classes
        # Strict mode later seq, not implied → secondary.
        assert FailureClass.STRICT_MODE_NON_CONVERGE.value in result.secondary_classes

    def test_policy_violation_implies_quality_gate(self) -> None:
        """POLICY_VIOLATION is more specific than QUALITY_GATE_FAIL.
        When both fire, QG should NOT appear as secondary (per IMPLIES)."""
        anchor = _anchor_milestone_failed(10)
        qg = _seq_ev(
            7,
            type="quality_gate_result",
            gate="secret_scan",
            checkpoint="QG1",
            passed=False,
        )
        audit = [
            {
                "seq": 5,
                "event": "POLICY_VIOLATION",
                "run_id": "test-run",
                "milestone": "M1",
                "data": {"checkpoint": "QG1"},
            }
        ]
        result = classify_failure(anchor, _bundle(anchor, [qg, anchor], audit))
        assert result.primary_class == FailureClass.POLICY_VIOLATION
        # QG should NOT be in secondaries because policy implies it.
        assert FailureClass.QUALITY_GATE_FAIL.value not in result.secondary_classes

    def test_drift_never_primary(self) -> None:
        """Only DriftDetected in bundle → primary=UNKNOWN, secondary=[drift_correlated]."""
        anchor = _anchor_milestone_failed(10, reason="something")
        drift = _seq_ev(
            8,
            type="drift_detected",
            metric="cost_usd",
            severity="critical",
            z_score=4.5,
        )
        result = classify_failure(anchor, _bundle(anchor, [drift, anchor]))
        assert result.primary_class == FailureClass.UNKNOWN
        assert SECONDARY_TAG_DRIFT in result.secondary_classes

    def test_drift_as_secondary_with_quality_gate_primary(self) -> None:
        anchor = _anchor_milestone_failed(10)
        qg = _seq_ev(5, type="quality_gate_result", gate="lint", checkpoint="QG2", passed=False)
        drift = _seq_ev(7, type="drift_detected", metric="cost_usd", severity="critical")
        result = classify_failure(anchor, _bundle(anchor, [qg, drift, anchor]))
        assert result.primary_class == FailureClass.QUALITY_GATE_FAIL
        assert SECONDARY_TAG_DRIFT in result.secondary_classes


# ---- TestRulesRegistry ----


class TestRulesRegistry:
    def test_rules_unique_ids(self) -> None:
        ids = [r.id for r in RULES]
        assert len(ids) == len(set(ids))

    def test_rules_unique_primary_classes(self) -> None:
        primaries = [r.primary for r in RULES]
        assert len(primaries) == len(set(primaries))

    def test_recommendations_cover_all_failureclasses(self) -> None:
        for cls in FailureClass:
            assert cls in RECOMMENDATIONS
            assert len(RECOMMENDATIONS[cls]) > 0
            assert len(RECOMMENDATIONS[cls]) <= 280  # ≤200 char target, allow some slack

    def test_implies_keys_are_failureclasses(self) -> None:
        for k, v in IMPLIES.items():
            assert isinstance(k, FailureClass)
            for vc in v:
                assert isinstance(vc, FailureClass)


# ---- TestDeterminism ----


class TestDeterminism:
    def test_classify_twice_identical_output(self) -> None:
        """Determinism critical: two calls on same data → identical TriageResult."""
        anchor = _anchor_milestone_failed(10)
        qg = _seq_ev(5, type="quality_gate_result", gate="lint", checkpoint="QG2", passed=False)
        drift = _seq_ev(7, type="drift_detected", metric="cost_usd", severity="critical")
        events = [qg, drift, anchor]
        r1 = classify_failure(anchor, _bundle(anchor, events))
        r2 = classify_failure(anchor, _bundle(anchor, events))
        assert r1 == r2

    def test_classify_run_idempotent(self, tmp_path: Path) -> None:
        """classify_run on the same telemetry path gives byte-identical JSON."""
        tel = tmp_path / "telemetry.jsonl"
        events = [
            {
                "seq": 0,
                "type": "milestone_started",
                "run_id": "r1",
                "milestone": "M1",
                "index": 0,
            },
            {
                "seq": 1,
                "type": "quality_gate_result",
                "run_id": "r1",
                "milestone": "M1",
                "gate": "lint",
                "checkpoint": "QG2",
                "passed": False,
            },
            {
                "seq": 2,
                "type": "milestone_failed",
                "run_id": "r1",
                "milestone": "M1",
                "phase": "review",
                "reason": "quality gate failed",
                "attempts": 1,
            },
        ]
        tel.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        r1 = classify_run(tel)
        r2 = classify_run(tel)
        b1 = json.dumps([to_event_dict(r) for r in r1], sort_keys=True)
        b2 = json.dumps([to_event_dict(r) for r in r2], sort_keys=True)
        assert b1 == b2
        assert len(r1) == 1
        assert r1[0].primary_class == FailureClass.QUALITY_GATE_FAIL


# ---- TestEvidenceCompleteness ----


class TestEvidenceCompleteness:
    def test_high_confidence_has_at_least_one_evidence(self) -> None:
        """Verdict criterion: every confidence=1.0 result has ≥1 evidence triple.
        (Design originally said ≥2; primary-rule evidence + drift secondary
        evidence gives ≥2 in the common case. The minimum guarantee is ≥1.)"""
        anchor = _anchor_milestone_failed(10)
        qg = _seq_ev(5, type="quality_gate_result", gate="lint", checkpoint="QG2", passed=False)
        result = classify_failure(anchor, _bundle(anchor, [qg, anchor]))
        assert result.confidence == 1.0
        assert len(result.evidence) >= 1

    def test_unknown_carries_raw_reason(self) -> None:
        anchor = _anchor_milestone_failed(10, reason="some specific weird failure")
        result = classify_failure(anchor, _bundle(anchor, [anchor]))
        assert result.raw_reason
        assert "some specific weird failure" in result.raw_reason


# ---- TestClassifyRunCorruption ----


class TestClassifyRunCorruption:
    def test_missing_telemetry_returns_empty(self, tmp_path: Path) -> None:
        result = classify_run(tmp_path / "missing.jsonl")
        assert result == []

    def test_corrupt_lines_skipped(self, tmp_path: Path) -> None:
        tel = tmp_path / "t.jsonl"
        tel.write_text(
            "not json\n"
            + json.dumps(
                {
                    "type": "milestone_failed",
                    "run_id": "r1",
                    "milestone": "M1",
                    "phase": "implement",
                    "reason": "weird",
                }
            )
            + "\n"
            + "more garbage\n",
            encoding="utf-8",
        )
        result = classify_run(tel)
        assert len(result) == 1
        # Reason "weird" matches nothing → UNKNOWN
        assert result[0].primary_class == FailureClass.UNKNOWN

    def test_empty_file(self, tmp_path: Path) -> None:
        tel = tmp_path / "t.jsonl"
        tel.write_text("", encoding="utf-8")
        result = classify_run(tel)
        assert result == []


# ---- TestSummarize ----


class TestSummarize:
    def test_summary_empty(self) -> None:
        s = summarize([])
        assert s["total_failures"] == 0
        assert s["unknown_count"] == 0
        assert s["unknown_pct"] == 0.0

    def test_summary_mixed(self) -> None:
        anchor = _anchor_milestone_failed(10)
        qg = _seq_ev(5, type="quality_gate_result", gate="lint", checkpoint="QG2", passed=False)
        r1 = classify_failure(anchor, _bundle(anchor, [qg, anchor]))
        anchor2 = _anchor_milestone_failed(20, reason="weird thing", milestone="M2")
        r2 = classify_failure(
            anchor2, BundleWindow(anchor=anchor2, events=[anchor2], audit_entries=[])
        )
        s = summarize([r1, r2])
        assert s["total_failures"] == 2
        assert s["unknown_count"] == 1
        assert s["unknown_pct"] == 0.5
        assert s["p50_confidence"] in {0.4, 1.0}  # median of [0.4, 1.0]


# ---- TestToEventDict ----


class TestToEventDict:
    def test_round_trip_keys(self) -> None:
        anchor = _anchor_milestone_failed(10)
        qg = _seq_ev(5, type="quality_gate_result", gate="lint", checkpoint="QG2", passed=False)
        r = classify_failure(anchor, _bundle(anchor, [qg, anchor]))
        d = to_event_dict(r, run_id="test-run")
        assert d["type"] == "failure_triaged"
        assert d["primary_class"] == "quality_gate_fail"
        assert d["triage_version"] == 1
        assert d["run_id"] == "test-run"
