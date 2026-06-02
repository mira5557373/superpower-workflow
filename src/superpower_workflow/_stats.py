"""Shared statistical helpers for drift + calibration (v1.3.24).

Both `drift.py` and `calibration.py` compute baselines + bands in log1p
space (heavy-tailed cost/duration distributions). Extracting the math
here keeps both modules in sync — a future divergence is caught by
cross-module tests (verdict revision #2 from v1.3.24 design).
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def log1p_ewma(values: Sequence[float], alpha: float = 0.3) -> float:
    """Exponentially-weighted moving average in log1p space.

    Returns `expm1(ewma(log1p(values)))` so the output is back in the
    original units. Equal-weight fallback for n=0 returns 0.0.

    `alpha` is the weight on the newest sample (0 < alpha <= 1).
    """
    if not values:
        return 0.0
    if alpha <= 0 or alpha > 1:
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    avg = math.log1p(max(0.0, values[0]))
    for v in values[1:]:
        avg = alpha * math.log1p(max(0.0, v)) + (1 - alpha) * avg
    return math.expm1(avg)


def log1p_percentiles(values: Sequence[float], qs: Sequence[float]) -> dict[float, float]:
    """Percentiles computed in log1p space, returned in original units.

    Handles empty/degenerate inputs by returning zeros. Uses linear
    interpolation between samples (numpy's default).
    """
    out: dict[float, float] = {}
    if not values:
        return {q: 0.0 for q in qs}
    logged = sorted(math.log1p(max(0.0, v)) for v in values)
    n = len(logged)
    for q in qs:
        if not 0.0 <= q <= 1.0:
            raise ValueError(f"quantile must be in [0, 1], got {q}")
        if n == 1:
            out[q] = math.expm1(logged[0])
            continue
        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        interp = logged[lo] + frac * (logged[hi] - logged[lo])
        out[q] = math.expm1(interp)
    return out


def small_n_widen(band_low: float, band_high: float, n: int, p50: float) -> tuple[float, float]:
    """Bessel-style widening for small-sample bands.

    At n < 20, p10/p90 percentiles understate true uncertainty because
    we're seeing only a few draws. Widen the band around the median by
    a factor that decreases monotonically with n and asymptotes to 1.0
    at n=20.

    n=5  → factor ~1.4
    n=10 → factor ~1.15
    n=20 → factor 1.0 (no widening)
    """
    if n >= 20:
        return band_low, band_high
    if n < 1:
        return band_low, band_high
    # Smoothly decreasing widening factor.
    factor = 1.0 + 2.0 / (n + 4.0)  # n=5 -> 1.222; n=10 -> 1.143; n=20 -> 1.083
    # Cap at +50% widening at very low n.
    factor = min(factor, 1.5)
    delta_low = (p50 - band_low) * factor
    delta_high = (band_high - p50) * factor
    return max(0.0, p50 - delta_low), p50 + delta_high
