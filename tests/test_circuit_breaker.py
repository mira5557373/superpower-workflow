"""Unit tests for the Classed Circuit Breaker (v1.3.26)."""

from __future__ import annotations

from superpower_workflow.circuit_breaker import (
    BreakerAction,
    BreakerConfig,
    BreakerWindowEntry,
    TripRule,
    evaluate,
    parse_config,
)


def _entry(
    *,
    milestone: str = "M1",
    primary_class: str = "policy_violation",
    confidence: float = 1.0,
    ts: str = "2026-06-02T00:00:00Z",
) -> BreakerWindowEntry:
    return BreakerWindowEntry(
        milestone_name=milestone,
        primary_class=primary_class,
        confidence=confidence,
        triage_event_id="ev-1",
        ts=ts,
    )


class TestEvaluateContinue:
    def test_disabled_always_continues(self) -> None:
        cfg = BreakerConfig(enabled=False)
        result = evaluate([], new_entry=_entry(), config=cfg)
        assert result.action == BreakerAction.CONTINUE

    def test_no_new_entry_continues(self) -> None:
        cfg = BreakerConfig()
        result = evaluate([_entry()], new_entry=None, config=cfg)
        assert result.action == BreakerAction.CONTINUE

    def test_single_failure_continues(self) -> None:
        cfg = BreakerConfig()
        result = evaluate([], new_entry=_entry(), config=cfg)
        assert result.action == BreakerAction.CONTINUE
        assert result.rule_matched == TripRule.NONE


class TestSameClassRule:
    def test_two_consecutive_deterministic_trips_observed(self) -> None:
        """Deterministic class threshold=2 → second same-class fails."""
        cfg = BreakerConfig()  # observation_only=True
        window = [_entry(milestone="M1", primary_class="policy_violation")]
        result = evaluate(window, new_entry=_entry(milestone="M2"), config=cfg)
        assert result.action == BreakerAction.TRIP_OBSERVED
        assert result.rule_matched == TripRule.SAME_CLASS_REPEAT
        assert result.primary_class == "policy_violation"

    def test_two_consecutive_deterministic_trips_enforced(self) -> None:
        cfg = BreakerConfig(observation_only=False)
        window = [_entry(milestone="M1", primary_class="policy_violation")]
        result = evaluate(window, new_entry=_entry(milestone="M2"), config=cfg)
        assert result.action == BreakerAction.TRIP_ENFORCED

    def test_transient_class_threshold_3(self) -> None:
        """claude_subprocess_timeout default threshold=3."""
        cfg = BreakerConfig()
        window = [
            _entry(milestone="M1", primary_class="claude_subprocess_timeout"),
            _entry(milestone="M2", primary_class="claude_subprocess_timeout"),
        ]
        # 3rd same-class → trips.
        result = evaluate(
            window,
            new_entry=_entry(milestone="M3", primary_class="claude_subprocess_timeout"),
            config=cfg,
        )
        assert result.action == BreakerAction.TRIP_OBSERVED

    def test_transient_class_second_does_not_trip(self) -> None:
        """Threshold=3 means 2 are not enough."""
        cfg = BreakerConfig()
        window = [_entry(milestone="M1", primary_class="claude_subprocess_timeout")]
        result = evaluate(
            window,
            new_entry=_entry(milestone="M2", primary_class="claude_subprocess_timeout"),
            config=cfg,
        )
        # 2 of 3 — not yet tripped.
        assert result.action == BreakerAction.CONTINUE

    def test_unknown_never_trips_same_class(self) -> None:
        """UNKNOWN class is explicitly excluded from same-class rule."""
        cfg = BreakerConfig()
        window = [_entry(primary_class="unknown")]
        result = evaluate(window, new_entry=_entry(primary_class="unknown"), config=cfg)
        # Even with 2 unknown, same-class rule doesn't apply. Diversity
        # may still fire at threshold=3, but with only 2 entries no trip.
        assert result.rule_matched != TripRule.SAME_CLASS_REPEAT

    def test_different_class_resets_consecutive(self) -> None:
        """Same-class chain broken by different-class failure."""
        cfg = BreakerConfig()
        window = [
            _entry(milestone="M1", primary_class="policy_violation"),
            _entry(milestone="M2", primary_class="merge_conflict"),
        ]
        # Now M3 policy_violation: not 2 consecutive same-class.
        result = evaluate(
            window,
            new_entry=_entry(milestone="M3", primary_class="policy_violation"),
            config=cfg,
        )
        assert result.rule_matched != TripRule.SAME_CLASS_REPEAT

    def test_low_confidence_does_not_advance_counter(self) -> None:
        """confidence < 0.7 breaks the same-class chain (verdict rev #4)."""
        cfg = BreakerConfig(confidence_floor=0.7)
        window = [
            _entry(milestone="M1", primary_class="policy_violation", confidence=0.4),
        ]
        result = evaluate(
            window,
            new_entry=_entry(milestone="M2", primary_class="policy_violation", confidence=1.0),
            config=cfg,
        )
        # Only 1 high-conf consecutive (the new entry) — below threshold=2.
        assert result.action == BreakerAction.CONTINUE


class TestDiversityRule:
    def test_three_in_five_window_trips(self) -> None:
        """Legacy 3-in-5: any 3 failures in last 5 milestones."""
        cfg = BreakerConfig()
        # Use 3 different classes so same-class doesn't fire first.
        window = [
            _entry(milestone="M1", primary_class="merge_conflict"),
            _entry(milestone="M2", primary_class="ci_fix_fail"),
        ]
        # 3rd failure (different class again) — diversity threshold=3 hits.
        result = evaluate(
            window,
            new_entry=_entry(milestone="M3", primary_class="gap_non_converge"),
            config=cfg,
        )
        assert result.action == BreakerAction.TRIP_OBSERVED
        assert result.rule_matched == TripRule.DIVERSITY_OVERFLOW

    def test_two_failures_does_not_trip_diversity(self) -> None:
        cfg = BreakerConfig()
        window = [_entry(milestone="M1", primary_class="merge_conflict")]
        result = evaluate(
            window,
            new_entry=_entry(milestone="M2", primary_class="ci_fix_fail"),
            config=cfg,
        )
        assert result.action == BreakerAction.CONTINUE


class TestParseConfig:
    def test_empty_defaults(self) -> None:
        cfg = parse_config(None)
        assert cfg.enabled is True
        assert cfg.observation_only is True
        assert cfg.diversity_window == 5
        assert cfg.diversity_threshold == 3
        assert cfg.confidence_floor == 0.7

    def test_observation_only_off(self) -> None:
        cfg = parse_config({"observation_only": False})
        assert cfg.observation_only is False

    def test_custom_thresholds(self) -> None:
        cfg = parse_config({"same_class_thresholds": {"policy_violation": 5}})
        assert cfg.same_class_thresholds["policy_violation"] == 5

    def test_disabled(self) -> None:
        cfg = parse_config({"enabled": False})
        assert not cfg.enabled


class TestCounterSnapshot:
    def test_snapshot_reflects_window_state(self) -> None:
        cfg = BreakerConfig()
        window = [
            _entry(primary_class="policy_violation"),
            _entry(primary_class="policy_violation"),
            _entry(primary_class="merge_conflict"),
        ]
        result = evaluate(window, new_entry=_entry(primary_class="ci_fix_fail"), config=cfg)
        assert result.counter_snapshot["policy_violation"] == 2
        assert result.counter_snapshot["merge_conflict"] == 1
        assert result.counter_snapshot["ci_fix_fail"] == 1


class TestRemediationHint:
    def test_remediation_populated_on_known_class(self) -> None:
        cfg = BreakerConfig()
        result = evaluate(
            [_entry(primary_class="cost_ceiling_blocked")],
            new_entry=_entry(primary_class="cost_ceiling_blocked"),
            config=cfg,
        )
        assert result.action == BreakerAction.TRIP_OBSERVED
        assert result.remediation_hint is not None
        assert "ceiling" in result.remediation_hint.lower()
