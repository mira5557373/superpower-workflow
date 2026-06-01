"""Tests for src/superpower_workflow/drift.py (v1.3.19 Drift Detector).

Pins the algorithm + safety gates + Verdict 1/2 fixes:

- Baseline floor (n>=15 default): no event below
- Model-swap auto-partitioning via bucket key (Verdict 1 fix #2)
- Batched JSONL read (Verdict 2 fix #1)
- Log-transform for cost/duration heavy tails
- Sigma floor (5% of mean) prevents zero-variance explosions
- Bounded metrics (cache_hit_rate, gap_attrition) clamp to [0,1]
- Direction-aware (cache_hit_rate UP = neutral, not alert)
- Two-tailed (gap_attrition: both directions are signal)
- Strict iterations: max-per-milestone, not per-event
- Gap attrition: last-per-milestone, not per-event
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from superpower_workflow.drift import (
    METRIC_BY_KEY,
    MetricBaseline,
    assess_all,
    bucket_key_for_milestone,
    bucket_key_for_phase,
    classify_drift,
    compute_baseline,
    dedup_key,
    load_samples_batched,
    split_bucket_phase,
)


def _write_telemetry(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events))


# ============================ bucket keys ============================


class TestBucketKeys:
    def test_phase_only(self):
        assert bucket_key_for_phase("plan") == "plan"

    def test_phase_with_model(self):
        # Verdict 1 fix #2 — model_id partitions baselines so a swap
        # doesn't fire spurious drift on the legitimate cost shift.
        assert bucket_key_for_phase("plan", "opus") == "plan|opus"
        assert bucket_key_for_phase("plan", "sonnet") == "plan|sonnet"

    def test_milestone_global(self):
        assert bucket_key_for_milestone() == "__global__"
        assert bucket_key_for_milestone("opus") == "__global__|opus"

    def test_split_round_trip(self):
        bucket = bucket_key_for_phase("implement", "sonnet")
        phase, model = split_bucket_phase(bucket)
        assert phase == "implement"
        assert model == "sonnet"

    def test_split_no_model(self):
        phase, model = split_bucket_phase("plan")
        assert phase == "plan"
        assert model is None


# ============================ load_samples_batched ====================


class TestLoadSamplesBatched:
    def test_missing_telemetry_returns_empty(self, tmp_path):
        samples = load_samples_batched(tmp_path / "missing.jsonl")
        assert samples == {}

    def test_single_read_returns_all_metrics(self, tmp_path):
        """Verdict 2 fix #1 — one JSONL pass returns all (metric, bucket)
        samples, not N reads per metric."""
        tel = tmp_path / "tel.jsonl"
        events = [
            {
                "type": "phase_completed",
                "phase": "plan",
                "cost_usd": 1.0,
                "duration_ms": 1000,
                "cache_hit_rate": 0.7,
            },
            {
                "type": "phase_completed",
                "phase": "plan",
                "cost_usd": 2.0,
                "duration_ms": 2000,
                "cache_hit_rate": 0.8,
            },
            {
                "type": "phase_completed",
                "phase": "implement",
                "cost_usd": 5.0,
                "duration_ms": 5000,
                "cache_hit_rate": 0.6,
            },
        ]
        _write_telemetry(tel, events)
        samples = load_samples_batched(tel)
        # 3 per-phase metrics × 2 buckets (plan, implement) = 6 keys
        # cost_usd in plan + implement, etc.
        assert ("cost_usd", "plan") in samples
        assert samples[("cost_usd", "plan")] == [1.0, 2.0]
        assert samples[("cost_usd", "implement")] == [5.0]
        assert samples[("duration_ms", "plan")] == [1000.0, 2000.0]
        assert samples[("cache_hit_rate", "implement")] == [0.6]

    def test_exclude_run_id(self):
        """The in-flight run's samples must NOT contaminate its own
        baseline (GATE-3 self-exclusion)."""
        # Inline write so each test has its own scope.
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tel = Path(d) / "tel.jsonl"
            events = [
                {"type": "phase_completed", "phase": "plan", "cost_usd": 1.0, "run_id": "RUN_A"},
                {"type": "phase_completed", "phase": "plan", "cost_usd": 2.0, "run_id": "RUN_A"},
                {
                    "type": "phase_completed",
                    "phase": "plan",
                    "cost_usd": 99.0,
                    "run_id": "RUN_CURRENT",
                },
            ]
            _write_telemetry(tel, events)
            samples = load_samples_batched(tel, exclude_run_id="RUN_CURRENT")
            assert samples[("cost_usd", "plan")] == [1.0, 2.0]

    def test_model_id_partition_per_phase(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        events = [
            {"type": "phase_completed", "phase": "plan", "cost_usd": 1.0},
            {"type": "phase_completed", "phase": "plan", "cost_usd": 2.0},
        ]
        _write_telemetry(tel, events)
        samples = load_samples_batched(tel, model_id_for_phase="opus")
        # All samples bucketed under "plan|opus"
        assert ("cost_usd", "plan|opus") in samples
        assert ("cost_usd", "plan") not in samples

    def test_sample_cap_keeps_most_recent(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        events = [
            {"type": "phase_completed", "phase": "plan", "cost_usd": float(i)} for i in range(1, 21)
        ]
        _write_telemetry(tel, events)
        samples = load_samples_batched(tel, sample_cap=5)
        # Most-recent 5 = 16..20
        assert samples[("cost_usd", "plan")] == [16.0, 17.0, 18.0, 19.0, 20.0]

    def test_filters_non_finite_and_negative(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        events = [
            {"type": "phase_completed", "phase": "plan", "cost_usd": -1.0},  # negative
            {"type": "phase_completed", "phase": "plan", "cost_usd": None},  # null
            {"type": "phase_completed", "phase": "plan", "cost_usd": 5.0},  # good
            {"type": "phase_completed", "phase": "plan", "cost_usd": "not a number"},  # bad type
        ]
        _write_telemetry(tel, events)
        samples = load_samples_batched(tel)
        assert samples.get(("cost_usd", "plan"), []) == [5.0]

    def test_bounded_metric_clamped_to_unit_interval(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        events = [
            {"type": "phase_completed", "phase": "plan", "cache_hit_rate": -0.5},  # out of bounds
            {"type": "phase_completed", "phase": "plan", "cache_hit_rate": 1.5},  # out of bounds
            {"type": "phase_completed", "phase": "plan", "cache_hit_rate": 0.7},  # good
        ]
        _write_telemetry(tel, events)
        samples = load_samples_batched(tel)
        assert samples.get(("cache_hit_rate", "plan"), []) == [0.7]

    def test_strict_iterations_aggregates_max_per_milestone(self, tmp_path):
        """StrictModeIteration fires N times per milestone (one per
        iter). Drift should use MAX, not append every iteration."""
        tel = tmp_path / "tel.jsonl"
        events = [
            {
                "type": "strict_mode_iteration",
                "iteration": 1,
                "milestone": "M1",
                "run_id": "RUN1",
            },
            {
                "type": "strict_mode_iteration",
                "iteration": 2,
                "milestone": "M1",
                "run_id": "RUN1",
            },
            {
                "type": "strict_mode_iteration",
                "iteration": 3,
                "milestone": "M1",
                "run_id": "RUN1",
            },
            {
                "type": "strict_mode_iteration",
                "iteration": 1,
                "milestone": "M2",
                "run_id": "RUN1",
            },
        ]
        _write_telemetry(tel, events)
        samples = load_samples_batched(tel)
        # M1 max = 3, M2 max = 1 → two samples in the global bucket
        assert sorted(samples[("strict_iterations", "__global__")]) == [1.0, 3.0]

    def test_gap_attrition_takes_last_per_milestone(self, tmp_path):
        """Multiple GapCurationCompleted per milestone (one per phase)
        — drift uses LAST per milestone."""
        tel = tmp_path / "tel.jsonl"
        events = [
            {
                "type": "gap_curation_completed",
                "attrition_pct": 0.2,
                "milestone": "M1",
                "run_id": "R1",
            },
            {
                "type": "gap_curation_completed",
                "attrition_pct": 0.5,
                "milestone": "M1",
                "run_id": "R1",
            },
            {
                "type": "gap_curation_completed",
                "attrition_pct": 0.3,
                "milestone": "M2",
                "run_id": "R1",
            },
        ]
        _write_telemetry(tel, events)
        samples = load_samples_batched(tel)
        assert sorted(samples[("gap_attrition_pct", "__global__")]) == [0.3, 0.5]


# ============================ compute_baseline =======================


class TestComputeBaseline:
    def test_empty_samples_returns_zero(self):
        b = compute_baseline([], METRIC_BY_KEY["cost_usd"])
        assert b.n == 0
        assert b.mean == 0.0
        assert b.stdev == 0.0

    def test_uses_log_for_cost(self):
        b = compute_baseline([1.0, 2.0, 4.0, 8.0, 16.0], METRIC_BY_KEY["cost_usd"])
        assert b.use_log is True
        # log1p means mean is log-space, not arithmetic-space.
        expected_log_mean = statistics_fmean([math.log1p(x) for x in [1.0, 2.0, 4.0, 8.0, 16.0]])
        assert abs(b.mean - expected_log_mean) < 1e-6

    def test_no_log_for_cache_hit_rate(self):
        b = compute_baseline([0.5, 0.6, 0.7, 0.8], METRIC_BY_KEY["cache_hit_rate"])
        assert b.use_log is False
        assert abs(b.mean - 0.65) < 1e-6

    def test_sigma_floor_at_5pct_of_mean(self):
        """A zero-variance series (all 5.0) gets a stdev floor of
        5% of mean (0.25), preventing div-by-zero in z-score."""
        b = compute_baseline([5.0] * 20, METRIC_BY_KEY["cache_hit_rate"])
        assert b.stdev >= 0.25  # 5% of 5.0


# helper for above (so we don't import statistics into the test top-level)
def statistics_fmean(xs):
    return sum(xs) / len(xs)


# ============================ classify_drift =========================


class TestClassifyDrift:
    def test_high_z_score_critical(self):
        """cost_usd higher than baseline + |z| ≥ 4σ → critical."""
        spec = METRIC_BY_KEY["cost_usd"]
        baseline = MetricBaseline(
            metric="cost_usd",
            bucket="plan|opus",
            n=20,
            mean=math.log1p(2.0),  # log-space mean of $2
            stdev=0.1,
            use_log=True,
        )
        # Compute the observation that yields z=5 in log space.
        log_val = baseline.mean + 5.0 * baseline.stdev
        value = math.expm1(log_val)
        a = classify_drift(value=value, baseline=baseline, spec=spec)
        assert a.severity == "critical"
        assert a.direction == "high"

    def test_cache_hit_rate_low_is_bad(self):
        """cache_hit_rate dropping below baseline is an alert."""
        spec = METRIC_BY_KEY["cache_hit_rate"]
        baseline = MetricBaseline(
            metric="cache_hit_rate",
            bucket="implement",
            n=20,
            mean=0.7,
            stdev=0.05,
            use_log=False,
        )
        a = classify_drift(value=0.3, baseline=baseline, spec=spec)
        assert a.severity == "critical"
        assert a.direction == "low"

    def test_cache_hit_rate_high_is_neutral(self):
        """Higher-than-baseline cache_hit_rate is GOOD → no alert."""
        spec = METRIC_BY_KEY["cache_hit_rate"]
        baseline = MetricBaseline(
            metric="cache_hit_rate", bucket="implement", n=20, mean=0.7, stdev=0.05
        )
        a = classify_drift(value=0.95, baseline=baseline, spec=spec)
        assert a.severity == "ok"
        assert a.direction == "neutral"

    def test_z_score_below_info_returns_ok(self):
        spec = METRIC_BY_KEY["cost_usd"]
        baseline = MetricBaseline(
            metric="cost_usd",
            bucket="plan",
            n=20,
            mean=math.log1p(2.0),
            stdev=0.1,
            use_log=True,
        )
        # Within 1 sigma.
        log_val = baseline.mean + 0.5 * baseline.stdev
        a = classify_drift(value=math.expm1(log_val), baseline=baseline, spec=spec)
        assert a.severity == "ok"

    def test_gap_attrition_two_tailed(self):
        """Both unusually low AND unusually high attrition is signal."""
        spec = METRIC_BY_KEY["gap_attrition_pct"]
        baseline = MetricBaseline(
            metric="gap_attrition_pct", bucket="__global__", n=20, mean=0.5, stdev=0.05
        )
        # Low side
        a_low = classify_drift(value=0.20, baseline=baseline, spec=spec)
        assert a_low.severity in ("warn", "critical")
        assert a_low.direction == "low"
        # High side
        a_high = classify_drift(value=0.80, baseline=baseline, spec=spec)
        assert a_high.severity in ("warn", "critical")
        assert a_high.direction == "high"


# ============================ assess_all (integration) ===============


class TestAssessAll:
    def test_below_floor_suppressed(self, tmp_path):
        """Verdict 2 fix — emit nothing when baseline.n < baseline_floor."""
        tel = tmp_path / "tel.jsonl"
        # 5 samples but floor is 15.
        events = [
            {"type": "phase_completed", "phase": "plan", "cost_usd": float(i)} for i in range(1, 6)
        ]
        _write_telemetry(tel, events)
        results = assess_all(
            telemetry_path=tel,
            pending_observations=[("cost_usd", "plan", 100.0)],
            baseline_floor=15,
        )
        assert len(results) == 1
        assert results[0].severity == "ok"
        assert results[0].suppressed_reason == "baseline_floor_n=5"

    def test_above_floor_classifies(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        # 20 stable samples of $2 (log-mean ≈ log1p(2) = 1.0986)
        events = [{"type": "phase_completed", "phase": "plan", "cost_usd": 2.0} for _ in range(20)]
        _write_telemetry(tel, events)
        # Observe a $50 phase — way outside baseline.
        results = assess_all(
            telemetry_path=tel,
            pending_observations=[("cost_usd", "plan", 50.0)],
            baseline_floor=15,
        )
        assert results[0].severity in ("warn", "critical")
        assert results[0].direction == "high"

    def test_batched_single_read(self, tmp_path):
        """Multiple pending observations from one hook call share a
        single JSONL read (Verdict 2 fix #1)."""
        tel = tmp_path / "tel.jsonl"
        # Add small natural variance so sigma_floor doesn't dominate
        # — real baselines never have zero variance.
        events = [
            {
                "type": "phase_completed",
                "phase": "plan",
                "cost_usd": 2.0 + (i % 3) * 0.3,  # 2.0, 2.3, 2.6, 2.0, ...
                "duration_ms": 1000 + (i % 5) * 50,  # 1000..1200
                "cache_hit_rate": 0.65 + (i % 4) * 0.02,  # 0.65..0.71
            }
            for i in range(20)
        ]
        _write_telemetry(tel, events)
        results = assess_all(
            telemetry_path=tel,
            pending_observations=[
                ("cost_usd", "plan", 2.3),  # squarely in band
                ("duration_ms", "plan", 1100),
                ("cache_hit_rate", "plan", 0.68),
            ],
            baseline_floor=15,
        )
        assert len(results) == 3
        # All within natural variance → no drift event.
        for r in results:
            assert r.severity == "ok", (
                f"Expected ok for in-band observation; got "
                f"{r.metric}={r.severity} (z={r.z_score:.2f})"
            )

    def test_model_swap_partitions_baseline_via_bucket_key(self, tmp_path):
        """Verdict 1 fix #2 — bucket key includes model_id, so a fresh
        observation under model 'sonnet' lands in bucket 'plan|sonnet'
        which is separate from 'plan|opus' baseline samples.

        The current impl tags samples on load with whichever model is
        passed — so historical-event model attribution requires
        PhaseCompleted to carry `model` (future enhancement). For v1,
        model_id_for_phase scopes BOTH historical and current to the
        same bucket, which means a deliberate switch resets baselines
        via different model_id_for_phase values across runs.
        """
        tel = tmp_path / "tel.jsonl"
        # 20 events historically — all loaded under same bucket as
        # whatever model_id we pass on load.
        events = [{"type": "phase_completed", "phase": "plan", "cost_usd": 5.0} for _ in range(20)]
        _write_telemetry(tel, events)

        # Run 1: opus model — observations bucket as plan|opus.
        opus_results = assess_all(
            telemetry_path=tel,
            pending_observations=[("cost_usd", "plan|opus", 5.0)],
            baseline_floor=15,
            model_id_for_phase="opus",
        )
        # Baseline matches → ok.
        assert opus_results[0].severity == "ok"
        assert opus_results[0].baseline_n == 20

        # Run 2: sonnet model with NO sonnet history yet — the same
        # historical events get tagged plan|sonnet, baseline n=20
        # (best-effort). To get the desired "fresh baseline on swap"
        # behaviour the caller would need to write events with model
        # attribution, OR clear telemetry between runs. v1 limitation
        # is documented; the bucket key affords the partition.
        sonnet_results = assess_all(
            telemetry_path=tel,
            pending_observations=[("cost_usd", "plan|sonnet", 1.0)],
            baseline_floor=15,
            model_id_for_phase="sonnet",
        )
        # Bucket key is correctly partitioned.
        assert sonnet_results[0].bucket == "plan|sonnet"


# ============================ dedup_key ==============================


class TestDedupKey:
    def test_includes_metric_bucket_severity_direction(self):
        k = dedup_key("cost_usd", "plan|opus", "warn", "high")
        assert k == "cost_usd|plan|opus|warn|high"

    def test_different_severity_different_key(self):
        warn = dedup_key("cost_usd", "plan", "warn", "high")
        crit = dedup_key("cost_usd", "plan", "critical", "high")
        assert warn != crit
