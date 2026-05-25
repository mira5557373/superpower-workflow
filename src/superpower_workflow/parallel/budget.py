from __future__ import annotations

import threading


class ThreadSafeBudget:
    def __init__(self, limit: float) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        self._spent = 0.0

    def spend(self, amount: float) -> bool:
        if amount < 0:
            return False
        with self._lock:
            if self._spent + amount > self._limit:
                return False
            self._spent += amount
            return True

    @property
    def remaining(self) -> float:
        with self._lock:
            return self._limit - self._spent

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    @property
    def limit(self) -> float:
        return self._limit

    @property
    def is_exhausted(self) -> bool:
        with self._lock:
            return self._spent >= self._limit
