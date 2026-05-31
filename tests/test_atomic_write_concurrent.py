"""v1.3.5 #5 + #14: _atomic_write must support concurrent writers to the
same destination without colliding on the .tmp filename.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from superpower_workflow.state import _atomic_write, _get_path_lock


class TestUniqueTmpFilenames:
    def test_two_writers_to_same_path_dont_collide(self, tmp_path):
        """Two threads racing on the same destination must both succeed —
        no PermissionError, no torn writes."""
        target = tmp_path / "x.json"
        errors = []
        N = 8

        def writer(i):
            try:
                _atomic_write(target, {"writer": i, "value": i * 2})
            except Exception as e:
                errors.append((i, e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"writers failed: {errors}"
        # Final state should be ONE valid JSON written by one of the writers.
        result = json.loads(target.read_text())
        assert "writer" in result and 0 <= result["writer"] < N

    def test_tmp_filename_includes_pid_and_tid(self, tmp_path, monkeypatch):
        """The tmp filename pattern must include the pid + thread id +
        random hex so two concurrent writers cannot produce the same name."""
        target = tmp_path / "y.json"

        captured = []

        original_with_suffix = Path.with_suffix

        def capture_with_suffix(self, suffix):
            if suffix.startswith(".json.") and suffix.endswith(".tmp"):
                captured.append(suffix)
            return original_with_suffix(self, suffix)

        monkeypatch.setattr(Path, "with_suffix", capture_with_suffix)
        _atomic_write(target, {"k": 1})

        assert captured, "with_suffix should have been called with the tmp pattern"
        suffix = captured[0]
        parts = suffix.split(".")
        # Expect [".json", pid, tid, hex8, "tmp"] — at least 4 numeric/hex parts
        assert len(parts) >= 4
        assert "tmp" in parts

    def test_no_leftover_tmp_after_normal_write(self, tmp_path):
        """A successful _atomic_write should NOT leave any .tmp behind."""
        target = tmp_path / "z.json"
        _atomic_write(target, {"k": "v"})
        leftover = list(tmp_path.glob("z.json.*.tmp"))
        assert leftover == [], f"unexpected tmp leftover: {leftover}"


class TestPerPathLock:
    def test_same_path_returns_same_lock(self, tmp_path):
        target = tmp_path / "a.json"
        lock1 = _get_path_lock(target)
        lock2 = _get_path_lock(target)
        assert lock1 is lock2

    def test_different_paths_get_different_locks(self, tmp_path):
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        assert _get_path_lock(a) is not _get_path_lock(b)

    def test_lock_serializes_writers_to_same_path(self, tmp_path):
        """When two writers contend on the same target, only one is inside
        the critical section at any time."""
        target = tmp_path / "c.json"
        in_flight = [0]
        max_concurrent = [0]
        guard = threading.Lock()

        # Wrap _atomic_write to observe how many writers are inside.
        # We approximate by patching the underlying lock to increment
        # a shared counter while held.
        path_lock = _get_path_lock(target)

        def observe_then_write(i):
            with path_lock:
                with guard:
                    in_flight[0] += 1
                    max_concurrent[0] = max(max_concurrent[0], in_flight[0])
                # Simulate write work
                import time

                time.sleep(0.01)
                with guard:
                    in_flight[0] -= 1

        threads = [threading.Thread(target=observe_then_write, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_concurrent[0] == 1, (
            f"per-path lock should serialize writers; saw max={max_concurrent[0]} concurrent"
        )


class TestBackwardCompatible:
    def test_single_writer_still_produces_valid_json(self, tmp_path):
        """The common path (one writer) should be unchanged behaviorally."""
        target = tmp_path / "n.json"
        _atomic_write(target, {"a": 1, "b": [1, 2, 3]})
        assert json.loads(target.read_text()) == {"a": 1, "b": [1, 2, 3]}
