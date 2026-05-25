from __future__ import annotations

import threading

from superpower_workflow.parallel.budget import ThreadSafeBudget


class TestThreadSafeBudget:
    def test_initial_state(self):
        b = ThreadSafeBudget(100.0)
        assert b.remaining == 100.0
        assert b.spent == 0.0
        assert b.limit == 100.0

    def test_spend_success(self):
        b = ThreadSafeBudget(100.0)
        assert b.spend(25.0) is True
        assert b.spent == 25.0
        assert b.remaining == 75.0

    def test_spend_exact_limit(self):
        b = ThreadSafeBudget(50.0)
        assert b.spend(50.0) is True
        assert b.remaining == 0.0

    def test_spend_over_limit_rejected(self):
        b = ThreadSafeBudget(50.0)
        assert b.spend(60.0) is False
        assert b.spent == 0.0
        assert b.remaining == 50.0

    def test_cumulative_spend_hits_limit(self):
        b = ThreadSafeBudget(100.0)
        assert b.spend(40.0) is True
        assert b.spend(40.0) is True
        assert b.spend(25.0) is False
        assert b.spent == 80.0

    def test_is_exhausted(self):
        b = ThreadSafeBudget(10.0)
        assert b.is_exhausted is False
        b.spend(10.0)
        assert b.is_exhausted is True

    def test_thread_safety(self):
        b = ThreadSafeBudget(1000.0)

        def spend_loop():
            for _ in range(100):
                b.spend(1.0)

        threads = [threading.Thread(target=spend_loop) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert b.spent == 1000.0
        assert b.remaining == 0.0

    def test_thread_safety_rejects_over_limit(self):
        b = ThreadSafeBudget(500.0)
        accepted = {"count": 0}
        lock = threading.Lock()

        def spend_loop():
            for _ in range(100):
                if b.spend(1.0):
                    with lock:
                        accepted["count"] += 1

        threads = [threading.Thread(target=spend_loop) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert accepted["count"] == 500
        assert b.spent == 500.0

    def test_zero_budget(self):
        b = ThreadSafeBudget(0.0)
        assert b.is_exhausted is True
        assert b.spend(1.0) is False

    def test_negative_spend_rejected(self):
        b = ThreadSafeBudget(100.0)
        assert b.spend(-5.0) is False
        assert b.spent == 0.0
