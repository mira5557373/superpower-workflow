"""v1.2.0-real Task 7: unit tests for PhaseD (Push).

PhaseD is a verbatim lift of orchestrator.py:1403-1476. The critical
ordering invariant the adversarial review flagged is the order of
`_call_post_phase` vs SBOM/sign: post_phase fires BEFORE both
(matches original line 1441 vs 1443-1476).

Critical invariants:
- v1.3.4 #15 retry safety doesn't apply to PhaseD (no
  _check_phase_result — preserved verbatim).
- _call_post_phase BEFORE SBOM/sign blocks (Finding 1 verdict
  point 4).
- _call_pre_commit fires with empty changed-files list.
- SBOM + sign emit their own audit entries (SBOM_GENERATED /
  SBOM_FAILED / ARTIFACT_SIGNED / SIGNING_SKIPPED).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from superpower_workflow.phases import PhaseContext, PhaseD
from superpower_workflow.runner import ClaudeResult


def _mk_orch(
    *,
    primary_cost: float = 0.10,
    git_strategy: str = "milestone",
    sbom_tool: str = "",
    sign_artifacts: bool = False,
    sbom_ok: bool = True,
    sbom_path: str = "/tmp/sbom.json",
    sign_sig: str = "sig",
) -> MagicMock:
    orch = MagicMock()
    orch.cwd = "/tmp/cwd"
    orch.sys_prompt = "system"
    orch._state_dir = "/tmp/state"
    orch.state = MagicMock()
    orch.state.run_id = "01TESTRUN"
    orch.config = {
        "git_strategy": git_strategy,
        "security": {
            "sbom_tool": sbom_tool,
            "sbom_output": "/tmp/sbom.json",
            "sign_artifacts": sign_artifacts,
        },
    }
    orch._run_claude.return_value = ClaudeResult(
        is_error=False,
        cost_usd=primary_cost,
        duration_ms=1000,
        session_id="sess-D",
        text="ok",
        raw={
            "usage": {
                "input_tokens": 20,
                "output_tokens": 60,
                "cache_creation_input_tokens": 40,
                "cache_read_input_tokens": 160,
            }
        },
    )
    orch._sbom_ok = sbom_ok
    orch._sbom_path = sbom_path
    orch._sign_sig = sign_sig
    return orch


def _mk_ctx(**overrides) -> PhaseContext:
    defaults = {
        "milestone_name": "M1",
        "milestone_dict": {"name": "M1"},
        "spec": "spec.md",
        "sections": "",
        "model": "opus",
        "budgets": {"push": 3},
        "fallback_model": "haiku",
        "effort": {"push": "low"},
        "logger": MagicMock(),
    }
    defaults.update(overrides)
    return PhaseContext(**defaults)


def _phase_d_patches(orch):
    """Patches save_state at the source module AND generate_sbom +
    sign_artifact so PhaseD doesn't shell out."""
    sbom = MagicMock(return_value=(orch._sbom_ok, orch._sbom_path))
    sign = MagicMock(return_value=orch._sign_sig)
    return (
        patch.multiple(
            "superpower_workflow.security",
            generate_sbom=sbom,
            sign_artifact=sign,
        ),
        patch("superpower_workflow.state.save_state"),
        patch("superpower_workflow.phases.push.save_state"),
    )


# ---- happy path ----


class TestHappyPath:
    def test_result_shape(self):
        orch = _mk_orch()
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            result = PhaseD(orch).run(_mk_ctx())

        assert result.phase == "push"
        assert result.cost_usd == 0.10
        assert result.duration_ms == 1000
        assert result.session_id == "sess-D"
        assert result.tokens["cache_creation_input_tokens"] == 40
        assert result.tokens["cache_read_input_tokens"] == 160
        # 160/(20+40+160) = 0.7273
        assert abs(result.tokens["cache_hit_rate"] - 0.7273) < 1e-4
        assert result.extras == {}

    def test_events_in_order(self):
        orch = _mk_orch()
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            result = PhaseD(orch).run(_mk_ctx())
        assert result.events_emitted == ["PhaseStarted", "PhaseCompleted"]


# ---- ordering invariant: post_phase BEFORE SBOM/sign ----


class TestPostPhaseOrdering:
    def test_post_phase_called_before_sbom(self):
        """Finding 1 verdict point 4 — the original orchestrator code
        at line 1441 calls _call_post_phase BEFORE the SBOM block at
        line 1443+. The initial v1.2.0-real plan had this wrong; this
        test pins the correct ordering.
        """
        orch = _mk_orch(sbom_tool="syft .")
        call_order: list[str] = []

        def record_post_phase(phase, ms, result):
            call_order.append(f"post_phase({phase})")

        sbom_mock = MagicMock(
            side_effect=lambda **kw: (call_order.append("sbom"), (True, "/tmp/sbom"))[1]
        )

        orch._call_post_phase.side_effect = record_post_phase

        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.push.save_state"),
            patch("superpower_workflow.security.generate_sbom", new=sbom_mock),
        ):
            PhaseD(orch).run(_mk_ctx())

        # post_phase first, then sbom.
        assert call_order == ["post_phase(push)", "sbom"]

    def test_post_phase_called_before_sign(self):
        """Same ordering invariant for sign_artifacts."""
        orch = _mk_orch(sign_artifacts=True)
        call_order: list[str] = []

        def record_post_phase(phase, ms, result):
            call_order.append(f"post_phase({phase})")

        def fake_sign(tag, cwd):
            call_order.append("sign")
            return "sig"

        orch._call_post_phase.side_effect = record_post_phase

        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.push.save_state"),
            patch("superpower_workflow.security.sign_artifact", side_effect=fake_sign),
        ):
            PhaseD(orch).run(_mk_ctx())

        assert call_order == ["post_phase(push)", "sign"]


# ---- branch resolution from git_strategy ----


class TestBranchResolution:
    def test_main_strategy_uses_main(self):
        from superpower_workflow.prompts import phase_d_prompt as real_prompt

        orch = _mk_orch(git_strategy="main")
        p1, p2, p3 = _phase_d_patches(orch)
        # Spy on phase_d_prompt to capture the branch arg.
        with (
            p1,
            p2,
            p3,
            patch(
                "superpower_workflow.phases.push.phase_d_prompt",
                side_effect=real_prompt,
            ) as prompt_mock,
        ):
            PhaseD(orch).run(_mk_ctx())
        # Second positional arg to phase_d_prompt is branch.
        args = prompt_mock.call_args.args
        assert args[1] == "main"

    def test_milestone_strategy_uses_milestone_branch(self):
        from superpower_workflow.prompts import phase_d_prompt as real_prompt

        orch = _mk_orch(git_strategy="milestone")
        p1, p2, p3 = _phase_d_patches(orch)
        with (
            p1,
            p2,
            p3,
            patch(
                "superpower_workflow.phases.push.phase_d_prompt",
                side_effect=real_prompt,
            ) as prompt_mock,
        ):
            PhaseD(orch).run(_mk_ctx())
        args = prompt_mock.call_args.args
        assert args[1] == "milestone/M1"


# ---- pre-commit hook ----


class TestPreCommit:
    def test_pre_commit_fires_with_empty_files_list(self):
        orch = _mk_orch()
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            PhaseD(orch).run(_mk_ctx())
        orch._call_pre_commit.assert_called_once_with({"name": "M1"}, [])


# ---- no _check_phase_result (preserved verbatim) ----


class TestNoCheckPhaseResult:
    def test_phase_d_does_not_call_check_phase_result(self):
        """The original orchestrator code does NOT check Phase D's
        result for errors. Preserved verbatim."""
        orch = _mk_orch()
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            PhaseD(orch).run(_mk_ctx())
        orch._check_phase_result.assert_not_called()


# ---- SBOM + sign side effects ----


class TestSbomAndSign:
    def test_sbom_skipped_when_no_tool_configured(self):
        orch = _mk_orch(sbom_tool="")
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            PhaseD(orch).run(_mk_ctx())
        # No audit entry for SBOM_GENERATED / SBOM_FAILED when sbom_tool is empty.
        audit_kinds = [c.args[0] for c in orch._audit.append.call_args_list]
        assert "SBOM_GENERATED" not in audit_kinds
        assert "SBOM_FAILED" not in audit_kinds

    def test_sbom_success_appends_audit(self):
        orch = _mk_orch(sbom_tool="syft .", sbom_ok=True)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.push.save_state"),
            patch(
                "superpower_workflow.security.generate_sbom",
                return_value=(True, "/tmp/sbom.json"),
            ),
        ):
            PhaseD(orch).run(_mk_ctx())
        audit_kinds = [c.args[0] for c in orch._audit.append.call_args_list]
        assert "SBOM_GENERATED" in audit_kinds

    def test_sbom_failure_no_audit_just_log(self):
        orch = _mk_orch(sbom_tool="syft .")
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.push.save_state"),
            patch(
                "superpower_workflow.security.generate_sbom",
                return_value=(False, None),
            ),
        ):
            PhaseD(orch).run(_mk_ctx())
        audit_kinds = [c.args[0] for c in orch._audit.append.call_args_list]
        assert "SBOM_GENERATED" not in audit_kinds
        # No SBOM_FAILED audit either — only a log.

    def test_sign_success_appends_audit(self):
        orch = _mk_orch(sign_artifacts=True)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.push.save_state"),
            patch(
                "superpower_workflow.security.sign_artifact",
                return_value="sig123",
            ),
        ):
            PhaseD(orch).run(_mk_ctx())
        audit_kinds = [c.args[0] for c in orch._audit.append.call_args_list]
        assert "ARTIFACT_SIGNED" in audit_kinds

    def test_sign_skipped_no_audit_just_log(self):
        orch = _mk_orch(sign_artifacts=True)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.push.save_state"),
            patch("superpower_workflow.security.sign_artifact", return_value=""),
        ):
            PhaseD(orch).run(_mk_ctx())
        audit_kinds = [c.args[0] for c in orch._audit.append.call_args_list]
        assert "ARTIFACT_SIGNED" not in audit_kinds

    def test_sign_block_skipped_when_flag_false(self):
        orch = _mk_orch(sign_artifacts=False)
        sign_mock = MagicMock(return_value="sig")
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.push.save_state"),
            patch("superpower_workflow.security.sign_artifact", new=sign_mock),
        ):
            PhaseD(orch).run(_mk_ctx())
        # sign_artifact never invoked.
        sign_mock.assert_not_called()


# ---- delegations ----


class TestDelegation:
    def test_primary_charge_via_accumulate_cost(self):
        orch = _mk_orch(primary_cost=2.5)
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            PhaseD(orch).run(_mk_ctx())
        orch._accumulate_cost.assert_called_once()
        assert orch._accumulate_cost.call_args.args[1] == 2.5

    def test_phase_completed_uses_primary_cost(self):
        from superpower_workflow.telemetry import PhaseCompleted

        orch = _mk_orch(primary_cost=1.5)
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            PhaseD(orch).run(_mk_ctx())
        emitted = [c.args[0] for c in orch._telemetry.emit.call_args_list]
        completed = [e for e in emitted if isinstance(e, PhaseCompleted)]
        assert len(completed) == 1
        assert completed[0].cost_usd == 1.5

    def test_post_phase_receives_primary_cost(self):
        orch = _mk_orch(primary_cost=2.0)
        p1, p2, p3 = _phase_d_patches(orch)
        with p1, p2, p3:
            PhaseD(orch).run(_mk_ctx())
        args, _ = orch._call_post_phase.call_args
        assert args[0] == "push"
        assert args[2] == {"cost": 2.0}
