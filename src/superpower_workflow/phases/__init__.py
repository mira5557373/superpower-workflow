"""Phase classes for the v1.2.0-real refactor.

Tasks 4-7 extract Phase A/B/C/D/E from Orchestrator._run_milestone into
PhaseA/PhaseB/PhaseTbV/PhaseC/PhaseD/PhaseE subclasses of PhaseBase.
Task 8 wires them into a thin _run_milestone driver. Task 9 retires the
unused TrustButVerifyPipeline (or wires it).

This package's __init__ exports the three contracts (PhaseBase,
PhaseContext, PhaseResult) so callers can import from
`superpower_workflow.phases` without reaching into submodules. The
concrete phase classes are added in Tasks 4-7.
"""

from __future__ import annotations

from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.context import PhaseContext
from superpower_workflow.phases.plan import PhaseA
from superpower_workflow.phases.result import PhaseResult

__all__ = [
    "PhaseA",
    "PhaseBase",
    "PhaseContext",
    "PhaseResult",
]
