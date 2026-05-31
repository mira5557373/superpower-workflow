"""v1.3.4 #9: HeartbeatThread refreshes lock heartbeat independent of
phase-loop progress, closing the window where a long-running Phase B
(>HEARTBEAT_STALE_SECONDS) lets another orchestrator decide the first
is hung and force-clean the lock.
"""

from __future__ import annotations

import time

from superpower_workflow.state import (
    HEARTBEAT_STALE_SECONDS,
    HeartbeatThread,
    _read_lock_meta,
    acquire_lock,
    release_lock,
)


class TestHeartbeatThreadRefreshes:
    def test_thread_refreshes_heartbeat_periodically(self, tmp_path):
        """Background thread bumps the heartbeat timestamp without any
        explicit caller invocation."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        assert acquire_lock(claude_dir) is True

        try:
            t0 = _read_lock_meta(claude_dir)["heartbeat"]
            hb = HeartbeatThread(claude_dir, interval=0.05)
            hb.start()
            time.sleep(0.2)  # Allow ~4 ticks
            hb.stop()
            t1 = _read_lock_meta(claude_dir)["heartbeat"]
            assert t1 > t0, "HeartbeatThread must refresh the heartbeat timestamp"
        finally:
            release_lock(claude_dir)

    def test_stop_is_idempotent(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        assert acquire_lock(claude_dir) is True
        try:
            hb = HeartbeatThread(claude_dir, interval=0.05)
            hb.start()
            hb.stop()
            # Second stop must not raise.
            hb.stop()
        finally:
            release_lock(claude_dir)

    def test_start_is_idempotent(self, tmp_path):
        """Calling start() twice should not spawn two threads."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        assert acquire_lock(claude_dir) is True
        try:
            hb = HeartbeatThread(claude_dir, interval=0.05)
            hb.start()
            first_thread = hb._thread
            hb.start()  # No-op
            assert hb._thread is first_thread
            hb.stop()
        finally:
            release_lock(claude_dir)

    def test_thread_survives_transient_io_error(self, tmp_path, monkeypatch):
        """If update_lock_heartbeat raises, the thread should keep ticking
        rather than crash silently."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        assert acquire_lock(claude_dir) is True
        try:
            # Make the first call raise; subsequent calls succeed.
            from superpower_workflow import state as state_mod

            calls = {"n": 0}
            real = state_mod.update_lock_heartbeat

            def flaky(cd):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("transient")
                return real(cd)

            monkeypatch.setattr(state_mod, "update_lock_heartbeat", flaky)

            hb = HeartbeatThread(claude_dir, interval=0.05)
            hb.start()
            time.sleep(0.25)
            hb.stop()
            assert calls["n"] > 1, "thread must have continued past the raise"
        finally:
            release_lock(claude_dir)

    def test_thread_is_daemon(self, tmp_path):
        """The heartbeat thread must be daemon so it doesn't block
        interpreter exit on uncaught exceptions."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        assert acquire_lock(claude_dir) is True
        try:
            hb = HeartbeatThread(claude_dir, interval=0.05)
            hb.start()
            assert hb._thread.daemon is True
            hb.stop()
        finally:
            release_lock(claude_dir)


class TestHeartbeatDefeatsStaleness:
    """v1.3.4 #9: with the background thread running, a "long" simulated
    Phase B doesn't trip the stale-heartbeat check that would otherwise
    let a second orchestrator steal the lock."""

    def test_heartbeat_thread_keeps_lock_fresh_under_simulated_long_phase(
        self, tmp_path, monkeypatch
    ):
        # Shrink the staleness window for the test so we don't sleep 10 min.
        monkeypatch.setattr("superpower_workflow.state.HEARTBEAT_STALE_SECONDS", 0.2)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        assert acquire_lock(claude_dir) is True
        try:
            from superpower_workflow.state import _is_lock_stale

            hb = HeartbeatThread(claude_dir, interval=0.05)
            hb.start()
            # Simulate a long Phase B by sleeping past the staleness window.
            time.sleep(0.5)
            meta = _read_lock_meta(claude_dir)
            stale, reason = _is_lock_stale(meta)
            hb.stop()
            assert not stale, (
                f"heartbeat thread failed to keep lock fresh; got stale={stale} reason={reason}"
            )
        finally:
            release_lock(claude_dir)


class TestConstants:
    def test_heartbeat_stale_seconds_unchanged_default(self):
        """v1.3.4 keeps the staleness window at 600s — the heartbeat thread
        fixes the bug at the producer side, no need to widen the consumer
        side. If someone widens this, it's belt-and-suspenders, not the
        primary fix."""
        assert HEARTBEAT_STALE_SECONDS >= 60
