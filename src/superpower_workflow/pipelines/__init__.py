"""Extracted pipeline components (v1.2.0 lite refactor).

The full Phase A/B/C/D class refactor (T2.0.1) is deferred to v1.2.1; that
needs ~50 integration test migrations and real-soak regression validation
that wasn't safe to land overnight. This package extracts the trust-but-verify
pipeline as a reusable component without changing orchestrator behavior — the
orchestrator continues to call its existing `_run_spec_compliance` /
`_run_feature_verification` / `_run_gap_curator` / `_run_strict_mode_loop`
methods.

The pipeline class here is a NEW dependency-injectable API that future Phase
classes (v1.2.1+) will use. Behavior is identical to the orchestrator's
current implementation when called with the same arguments.
"""

from __future__ import annotations

from superpower_workflow.pipelines.trust_but_verify import (
    PipelineContext,
    TrustButVerifyPipeline,
    TrustButVerifyResult,
)

__all__ = ["PipelineContext", "TrustButVerifyPipeline", "TrustButVerifyResult"]
