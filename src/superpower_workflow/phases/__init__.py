"""Phase classes for the v1.2.0-real refactor.

Tasks 4-7 extract Phase A/B/C/D/E from Orchestrator._run_milestone into
PhaseA/PhaseB/PhaseTbV/PhaseC/PhaseD/PhaseE subclasses of PhaseBase.
Task 8 wires them into a thin _run_milestone driver. Task 9 retires the
old TrustButVerifyPipeline (the v1.2.0-lite extraction that shipped as
dead code per CHANGELOG line 1168; its design conflated PhaseTbV
stages with strict-mode which lives inside PhaseC).

This package's __init__ exports the three contracts (PhaseBase,
PhaseContext, PhaseResult) plus the six concrete phase classes
(PhaseA/B/TbV/C/D/E).
"""

from __future__ import annotations

from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.ci_fix import PhaseE
from superpower_workflow.phases.context import PhaseContext
from superpower_workflow.phases.implement import PhaseB
from superpower_workflow.phases.plan import PhaseA
from superpower_workflow.phases.push import PhaseD
from superpower_workflow.phases.result import PhaseResult
from superpower_workflow.phases.review import PhaseC
from superpower_workflow.phases.trust_but_verify import PhaseTbV

__all__ = [
    "PhaseA",
    "PhaseB",
    "PhaseBase",
    "PhaseC",
    "PhaseContext",
    "PhaseD",
    "PhaseE",
    "PhaseResult",
    "PhaseTbV",
]
