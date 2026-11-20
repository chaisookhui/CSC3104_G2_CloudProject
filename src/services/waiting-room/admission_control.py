"""Local rolling-load telemetry; admission is owned by the batch dispatcher."""

from __future__ import annotations

from collections import deque
from threading import Lock
import time
from typing import Callable, Deque, Dict, Union


Number = Union[int, float]


class AdmissionController:
    FULL = "full"
    THROTTLED = "throttled"

    def __init__(
        self,
        *,
        window_seconds: Number,
        low_threshold: int,
        high_threshold: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._validate_config(
            window_seconds=window_seconds,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
        )

        self.window_seconds = float(window_seconds)
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

        self._clock = clock
        self._request_times: Deque[float] = deque()
        self._state = self.FULL
        self._lock = Lock()

    @staticmethod
    def _validate_config(
        *,
        window_seconds: Number,
        low_threshold: int,
        high_threshold: int,
    ) -> None:
        if not isinstance(window_seconds, (int, float)) or window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0")

        if type(low_threshold) is not int or low_threshold < 0:
            raise ValueError("low_threshold must be a non-negative integer")

        if type(high_threshold) is not int or high_threshold <= low_threshold:
            raise ValueError("high_threshold must be greater than low_threshold")

    def record_request(self) -> Dict[str, object]:
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._request_times.append(now)
            self._update_state()
            return self._status_unlocked()

    def get_status(self) -> Dict[str, object]:
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._update_state()
            return self._status_unlocked()

    def _prune(self, now: float) -> None:
        request_cutoff = now - self.window_seconds
        while self._request_times and self._request_times[0] <= request_cutoff:
            self._request_times.popleft()

    def _update_state(self) -> None:
        load = len(self._request_times)

        if self._state == self.FULL and load > self.high_threshold:
            self._state = self.THROTTLED
        elif self._state == self.THROTTLED and load < self.low_threshold:
            self._state = self.FULL

    def _status_unlocked(self) -> Dict[str, object]:
        return {
            "admission_state": self._state,
            "requests_in_window": len(self._request_times),
            "window_seconds": self.window_seconds,
            "low_threshold": self.low_threshold,
            "high_threshold": self.high_threshold,
        }
