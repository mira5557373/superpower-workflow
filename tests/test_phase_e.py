"""v1.2.0-real Task 7: unit tests for PhaseE (CI fix loop).

PhaseE is a verbatim lift of orchestrator.py:1478-1532. Critical
ordering invariant from the adversarial review (Finding 1 verdict
point 3): at the moment of PhaseStarted emission,
`state.current_step` is "ci_wait", NOT "ci_fix". The two-step
transition `ci_wait → save → log → emit PhaseStarted → ci_fix → save`
is INTENTIONAL — telemetry consumers see "ci_wait" at PhaseStarted,
then "ci_fix" persists right after.

Critical invariants:
- Short-circuit to no-op when integrations.ci.enabled is False
  (driver always invokes; helper gates).
- PhaseE NEVER raises on ci_success=False — preserved verbatim.
- PhaseCompleted.cost_usd uses round(ci_cost, 2) — different from
  other phases (which use unrounded primary cost in the event).
- duration_ms=0, session_id="" since there's no single primary call.
- v1.3.4 #15 retry safety holds at the LOOP BOUNDARY only
  (mid-iteration crashes drop partial cost).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from superpower_workflow.phases import PhaseContext, PhaseE


def _mk_orch(
    *,
    ci_enabled: bool = True,
    ci_success: bool = True,
    ci_cost: float = 0.50,
    ci_tokens: dict | None = None,
) -> MagicMock:
    orch = MagicMock()
    orch.cwd = "/tmp/cwd"
    orch.sys_prompt = "system"
    orch._state_dir = "/tmp/state"
    orch.state = MagicMock()
    orch.state.run_id = "01TESTRUN"
    orch.config = {"model": "opus", "fallback_model": "haiku"}
    orch._integrations = {"ci": {"enabled": ci_enabled, "max_attempts": 3}}
    orch._ci_success = ci_success
    orch._ci_cost = ci_cost
    orch._ci_tokens = ci_tokens or {
        "input_tokens": 25,
        "output_tokens": 90,
        "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 200,
        "cache_hit_rate": 0.7273,
    }
    return orch


def _mk_ctx(**overrides) -> PhaseContext:
    defaults = {
        "milestone_name": "M1",
        "milestone_dict": {"name": "M1"},
        "spec": "spec.md",
        "sections": "",
        "model": "opus",
        "budgets": {},
        "fallback_model": "haiku",
        "logger": MagicMock(),
    }
    defaults.update(overrides)
    return PhaseContext(**defaults)


# ---- CI disabled short-circuit ----


class TestCiDisabled:
    def test_returns_noop_result_when_ci_disabled(self):
        orch = _mk_orch(ci_enabled=False)
        result = PhaseE(orch).run(_mk_ctx())

        assert result.phase == "ci_fix"
        assert result.cost_usd == 0.0
        assert result.duration_ms == 0
        assert result.session_id == ""
        assert result.events_emitted == []
        assert result.extras == {"ci_success": True, "ci_enabled": False}

    def test_no_side_effects_when_ci_disabled(self):
        orch = _mk_orch(ci_enabled=False)
        PhaseE(orch).run(_mk_ctx())
        # No state mutations, no telemetry, no audit, no ci_fix_loop call.
        orch._telemetry.emit.assert_not_called()
        orch._audit.append.assert_not_called()
        orch._accumulate_cost.assert_not_called()


# ---- ordering invariant: ci_wait at PhaseStarted, ci_fix right after ----


class TestStateTransitionOrdering:
    def test_phase_started_emits_at_ci_wait_state(self):
        """Finding 1 verdict point 3 — at the moment of PhaseStarted
        emission, state.current_step is "ci_wait", NOT "ci_fix".
        The two-step transition `ci_wait → log → emit PhaseStarted →
        ci_fix → save` is intentional.
        """
        orch = _mk_orch()
        # Record state.current_step at the moment of each save_state call.
        state_at_save: list[str] = []

        def record_save_state(claude_dir, state):
            state_at_save.append(state.current_step)

        # Record state.current_step at the moment of telemetry.emit.
        state_at_emit: list[tuple[str, str]] = []

        def record_emit(event):
            from superpower_workflow.telemetry import PhaseStarted

            if isinstance(event, PhaseStarted):
                state_at_emit.append((event.phase, orch.state.current_step))

        orch._telemetry.emit.side_effect = record_emit

        with (
            patch("superpower_workflow.state.save_state", side_effect=record_save_state),
            patch("superpower_workflow.phases.ci_fix.save_state", side_effect=record_save_state),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())

        # First save_state was for "ci_wait"; second for "ci_fix".
        assert state_at_save[0] == "ci_wait"
        assert state_at_save[1] == "ci_fix"
        # PhaseStarted emitted while state was still "ci_wait".
        assert len(state_at_emit) == 1
        assert state_at_emit[0] == ("ci_fix", "ci_wait"), (
            f"Expected PhaseStarted(phase='ci_fix') emitted at "
            f"state='ci_wait'; got {state_at_emit[0]}"
        )


# ---- ci_fix_loop integration ----


class TestCiFixLoop:
    def test_ci_loop_invoked_with_orchestrator_run_claude(self):
        orch = _mk_orch()
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ) as loop_mock,
        ):
            PhaseE(orch).run(_mk_ctx())
        kwargs = loop_mock.call_args.kwargs
        assert kwargs["cwd"] == "/tmp/cwd"
        assert kwargs["run_claude_fn"] is orch._run_claude
        assert kwargs["model"] == "opus"
        assert kwargs["fallback_model"] == "haiku"

    def test_ci_cost_aggregate_charged_once(self):
        """v1.3.4 #15 — loop boundary, single _accumulate_cost call
        with the aggregate. Per-iteration accumulation is INSIDE
        ci_fix_loop's local accumulator (raw += pattern)."""
        orch = _mk_orch(ci_cost=2.50)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 2.50, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        orch._accumulate_cost.assert_called_once()
        assert orch._accumulate_cost.call_args.args[1] == 2.50

    def test_phase_completed_uses_rounded_cost(self):
        """PhaseE's PhaseCompleted.cost_usd uses round(ci_cost, 2) —
        distinct from other phases which emit unrounded primary cost.
        Preserved verbatim from original line 1521.
        """
        from superpower_workflow.telemetry import PhaseCompleted

        orch = _mk_orch(ci_cost=2.555555)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 2.555555, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        emitted = [c.args[0] for c in orch._telemetry.emit.call_args_list]
        completed = [e for e in emitted if isinstance(e, PhaseCompleted)]
        assert len(completed) == 1
        # 2.555555 rounded to 2 dp = 2.56.
        assert completed[0].cost_usd == 2.56

    def test_phase_completed_has_zero_duration_and_empty_session(self):
        from superpower_workflow.telemetry import PhaseCompleted

        orch = _mk_orch()
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        completed = [
            c.args[0]
            for c in orch._telemetry.emit.call_args_list
            if isinstance(c.args[0], PhaseCompleted)
        ]
        assert completed[0].duration_ms == 0
        assert completed[0].session_id == ""

    def test_ci_tokens_splatted_into_phase_completed(self):
        from superpower_workflow.telemetry import PhaseCompleted

        orch = _mk_orch()
        tokens = {
            "input_tokens": 100,
            "output_tokens": 400,
            "cache_creation_input_tokens": 50,
            "cache_read_input_tokens": 250,
            "cache_hit_rate": 0.625,
        }
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        completed = [
            c.args[0]
            for c in orch._telemetry.emit.call_args_list
            if isinstance(c.args[0], PhaseCompleted)
        ]
        assert completed[0].input_tokens == 100
        assert completed[0].cache_hit_rate == 0.625


# ---- ci_success branch ----


class TestSuccessBranch:
    def test_ci_success_extras(self):
        orch = _mk_orch(ci_success=True)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ),
        ):
            result = PhaseE(orch).run(_mk_ctx())
        assert result.extras == {"ci_success": True, "ci_enabled": True}

    def test_audit_records_success_bool(self):
        orch = _mk_orch(ci_success=True)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        audit_calls = [
            c for c in orch._audit.append.call_args_list if c.args[0] == "PHASE_COMPLETE"
        ]
        assert len(audit_calls) == 1
        assert audit_calls[0].kwargs["data"]["success"] is True


class TestFailureBranch:
    def test_ci_failure_does_not_raise(self):
        """PhaseE NEVER raises on ci_success=False — preserved verbatim."""
        orch = _mk_orch(ci_success=False)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(False, 0.5, orch._ci_tokens),
            ),
        ):
            result = PhaseE(orch).run(_mk_ctx())
        assert result.extras["ci_success"] is False

    def test_ci_failure_transitions_state_to_ci_fix_failed(self):
        orch = _mk_orch(ci_success=False)
        state_history: list[str] = []

        def record_save(claude_dir, state):
            state_history.append(state.current_step)

        with (
            patch("superpower_workflow.state.save_state", side_effect=record_save),
            patch("superpower_workflow.phases.ci_fix.save_state", side_effect=record_save),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(False, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        # ci_wait → ci_fix → ci_fix_failed
        assert state_history == ["ci_wait", "ci_fix", "ci_fix_failed"]

    def test_audit_records_failure_bool(self):
        orch = _mk_orch(ci_success=False)
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(False, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        audit_calls = [
            c for c in orch._audit.append.call_args_list if c.args[0] == "PHASE_COMPLETE"
        ]
        assert audit_calls[0].kwargs["data"]["success"] is False


# ---- no pre_phase / no post_phase / no check_phase_result ----


class TestNoHooks:
    def test_no_pre_phase_call(self):
        """PhaseE does NOT invoke _call_pre_phase — preserved verbatim
        from original."""
        orch = _mk_orch()
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        orch._call_pre_phase.assert_not_called()

    def test_no_post_phase_call(self):
        """PhaseE does NOT invoke _call_post_phase — preserved verbatim."""
        orch = _mk_orch()
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        orch._call_post_phase.assert_not_called()

    def test_no_check_phase_result(self):
        """PhaseE does NOT invoke _check_phase_result (the loop reports
        failure via the ci_success bool, not via _PhaseError)."""
        orch = _mk_orch()
        with (
            patch("superpower_workflow.state.save_state"),
            patch("superpower_workflow.phases.ci_fix.save_state"),
            patch(
                "superpower_workflow.phases.ci_fix.ci_fix_loop",
                return_value=(True, 0.5, orch._ci_tokens),
            ),
        ):
            PhaseE(orch).run(_mk_ctx())
        orch._check_phase_result.assert_not_called()
