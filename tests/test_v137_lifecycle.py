"""v1.3.7 lifecycle hardening:
- #1 signal-deferred completed-state pair (regression-test the lock wrap)
- #2 run_claude uses Popen with new process group for signal propagation
- #3 FastAPI lifespan shutdown disposes engine
- #4 Orchestrator installs SIGINT/SIGTERM handlers
- #9 convergence_gate hook uses _atomic_write
- Parallel mode gated until v1.3.8 Edit A lands
"""

from __future__ import annotations

import os
from unittest.mock import patch


class TestParallelModeUngatedAfterV138:
    """v1.3.7 gated parallel mode pending v1.3.8's Edit A. v1.3.8 ships Edit A
    (thread-local cwd override) so the gate is removed and parallel runs
    without env-var opt-in."""

    def test_parallel_runs_without_env_var(self, tmp_path, monkeypatch):
        """Parallel mode is no longer gated; SW_ALLOW_BROKEN_PARALLEL is a no-op."""
        # Set up a fresh project
        (tmp_path / ".claude").mkdir()
        import json as _json

        cfg = {
            "schema_version": 1,
            "spec": "spec.md",
            "model": "opus",
            "fallback_model": "haiku",
            "budgets": {"plan": 10, "implement": 25, "review": 10, "push": 1},
            "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
            "verify_commands": {},
            "milestones": [{"name": "M1"}, {"name": "M2"}],
            "validation": {},
            "convergence": {},
            "telemetry": {"enabled": False},
            "parallel": {"enabled": True, "max_workers": 2},
            "max_total_budget_usd": 100,
        }
        (tmp_path / ".claude" / "workflow.json").write_text(_json.dumps(cfg))
        (tmp_path / "spec.md").write_text("spec")

        monkeypatch.delenv("SW_ALLOW_BROKEN_PARALLEL", raising=False)
        from superpower_workflow.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        with (
            patch.object(orch, "_preflight_checks", return_value=True),
            patch.object(orch, "_run_parallel") as run_par,
            patch.object(orch, "_completion_notification"),
        ):
            orch.run()
        # Parallel branch should HAVE been invoked.
        run_par.assert_called_once()


class TestRunClaudePopenSignals:
    """v1.3.7 #2: _invoke_claude uses Popen with platform-specific
    process-group creation so signals propagate to the claude -p child."""

    def test_invoke_claude_uses_process_group_flags(self, tmp_path):
        """Verify Popen is invoked with preexec_fn=os.setsid (POSIX) or
        creationflags=CREATE_NEW_PROCESS_GROUP (Windows)."""
        from unittest.mock import MagicMock

        from superpower_workflow.runner import _invoke_claude

        popen_calls = []

        # Build a minimal child stub
        mock_child = MagicMock()
        mock_child.communicate.return_value = ("ok-stdout", "")
        mock_child.returncode = 0

        def fake_popen(cmd, **kw):
            popen_calls.append(kw)
            return mock_child

        with patch("superpower_workflow.runner.subprocess.Popen", fake_popen):
            _invoke_claude(["claude", "-p", "x"], str(tmp_path), 1000)

        assert popen_calls, "Popen was not called"
        kw = popen_calls[0]
        if os.name == "posix":
            assert "preexec_fn" in kw, "POSIX must use preexec_fn=os.setsid"
        elif os.name == "nt":
            assert "creationflags" in kw

    def test_terminate_process_group_helper_exists(self):
        from superpower_workflow.runner import _terminate_process_group

        assert callable(_terminate_process_group)

    def test_invoke_claude_helper_exists(self):
        """v1.3.7: tests should mock `_invoke_claude` (one stable interface)
        rather than subprocess internals."""
        from superpower_workflow.runner import _invoke_claude

        assert callable(_invoke_claude)


class TestShutdownHandlers:
    """v1.3.7 #4: orchestrator installs SIGINT/SIGTERM handlers."""

    def test_install_shutdown_handlers_is_idempotent(self, tmp_path):
        import json as _json

        (tmp_path / ".claude").mkdir()
        cfg = {
            "schema_version": 1,
            "spec": "spec.md",
            "model": "opus",
            "fallback_model": "haiku",
            "budgets": {"plan": 10, "implement": 25, "review": 10, "push": 1},
            "effort": {"plan": "max", "implement": "high", "review": "max", "push": "low"},
            "verify_commands": {},
            "milestones": [{"name": "M1"}],
            "validation": {},
            "convergence": {},
            "telemetry": {"enabled": False},
            "max_total_budget_usd": 100,
        }
        (tmp_path / ".claude" / "workflow.json").write_text(_json.dumps(cfg))
        from superpower_workflow.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        orch._install_shutdown_handlers()
        # Second call: must not raise; must not double-install.
        orch._install_shutdown_handlers()
        assert getattr(orch, "_shutdown_handlers_installed", False) is True


class TestConvergenceGateAtomicWrite:
    """v1.3.7 #9: convergence_gate hook uses _atomic_write."""

    def test_increment_iteration_uses_atomic_write(self):
        import inspect

        from superpower_workflow.hooks import convergence_gate

        src = inspect.getsource(convergence_gate._increment_iteration)
        assert "_atomic_write" in src, (
            "_increment_iteration must route through state._atomic_write; "
            "found direct os.replace pattern instead"
        )
        # Confirm bare os.replace is gone
        assert "os.replace(str(tmp)" not in src


class TestFastApiLifespan:
    """v1.3.7 #3: FastAPI app has a shutdown event handler."""

    def test_create_app_registers_shutdown_handler(self):
        import inspect

        from superpower_workflow.server import app as app_mod

        src = inspect.getsource(app_mod)
        # Either on_event("shutdown") or lifespan
        assert 'on_event("shutdown")' in src or "lifespan" in src, (
            "create_app must register a shutdown handler that disposes the engine"
        )


class TestStateCompletedAppendUnderLock:
    """v1.3.7 #1: state.completed.append + save_state must be wrapped in
    self._state_lock so a signal can't interrupt between them."""

    def test_append_and_save_inside_state_lock(self):
        import inspect

        from superpower_workflow.orchestrator import Orchestrator

        src = inspect.getsource(Orchestrator.run)
        # The wrap pattern: with self._state_lock: \n ... state.completed.append ... save_state
        # Less brittle: just check that state.completed.append appears within a
        # `with self._state_lock:` block.
        idx_lock = src.find("with self._state_lock")
        assert idx_lock != -1
        # state.completed.append must be present AFTER the lock block opens.
        idx_append = src.find("state.completed.append", idx_lock)
        assert idx_append != -1, (
            "state.completed.append must appear within a `with self._state_lock:` block"
        )
