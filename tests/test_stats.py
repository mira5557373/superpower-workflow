"""Unit tests for _stats.py — shared statistical helpers (v1.3.24)."""

from __future__ import annotations

import pytest

from superpower_workflow._stats import (
    log1p_ewma,
    log1p_percentiles,
    small_n_widen,
)


class TestLog1pEwma:
    def test_empty_returns_zero(self) -> None:
        assert log1p_ewma([]) == 0.0

    def test_single_value_returns_value(self) -> None:
        # EWMA of [5.0] with alpha=0.3 returns expm1(log1p(5.0)) = 5.0.
        assert abs(log1p_ewma([5.0]) - 5.0) < 1e-9

    def test_handles_zero_and_positive(self) -> None:
        # [0, 0, 1.0] should yield a small positive value (no overflow).
        result = log1p_ewma([0.0, 0.0, 1.0])
        assert 0 < result < 1.0

    def test_clamps_negative_to_zero(self) -> None:
        # Defensive: log1p of negative is undefined; our impl clamps at 0.
        assert log1p_ewma([-0.5, 1.0])  # no exception

    def test_alpha_validation(self) -> None:
        with pytest.raises(ValueError):
            log1p_ewma([1.0], alpha=0)
        with pytest.raises(ValueError):
            log1p_ewma([1.0], alpha=1.5)


class TestLog1pPercentiles:
    def test_empty_returns_zeros(self) -> None:
        out = log1p_percentiles([], [0.1, 0.5, 0.9])
        assert out == {0.1: 0.0, 0.5: 0.0, 0.9: 0.0}

    def test_match_hand_computed(self) -> None:
        """Reference values for [0.1, 0.2, 0.5, 1.0, 5.0] computed by hand
        in log1p space (numpy-style linear interpolation)."""
        values = [0.1, 0.2, 0.5, 1.0, 5.0]
        out = log1p_percentiles(values, [0.5])
        # p50 of 5 sorted log1p samples = the 3rd element exactly.
        # log1p(0.5) = 0.4055; expm1(0.4055) = 0.5
        assert abs(out[0.5] - 0.5) < 1e-6

    def test_single_value(self) -> None:
        out = log1p_percentiles([2.0], [0.1, 0.9])
        # With one sample, every percentile is that value.
        assert out[0.1] == pytest.approx(2.0)
        assert out[0.9] == pytest.approx(2.0)

    def test_quantile_bounds(self) -> None:
        with pytest.raises(ValueError):
            log1p_percentiles([1.0, 2.0], [1.5])
        with pytest.raises(ValueError):
            log1p_percentiles([1.0, 2.0], [-0.1])


class TestSmallNWiden:
    def test_n_ge_20_no_widening(self) -> None:
        assert small_n_widen(0.5, 1.5, n=20, p50=1.0) == (0.5, 1.5)
        assert small_n_widen(0.5, 1.5, n=100, p50=1.0) == (0.5, 1.5)

    def test_widening_decreases_with_n(self) -> None:
        """At fixed bands, widening factor decreases as n grows."""
        b5 = small_n_widen(0.5, 1.5, n=5, p50=1.0)
        b10 = small_n_widen(0.5, 1.5, n=10, p50=1.0)
        b20 = small_n_widen(0.5, 1.5, n=20, p50=1.0)
        # n=5 widens more than n=10.
        assert b5[1] > b10[1]
        # n=10 widens more than n=20.
        assert b10[1] > b20[1]

    def test_preserves_p50_is_center(self) -> None:
        """The median is the fixed point — widening only stretches sides."""
        low, high = small_n_widen(0.8, 1.2, n=5, p50=1.0)
        # Symmetry preserved around p50.
        assert abs((1.0 - low) - (high - 1.0)) < 0.01

    def test_does_not_go_below_zero(self) -> None:
        low, _ = small_n_widen(0.1, 1.0, n=3, p50=0.5)
        assert low >= 0.0
