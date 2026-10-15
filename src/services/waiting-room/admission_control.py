# command to run venv -- .\venv\Scripts\Activate.ps1
# measures recent req load -- decides how many users to be released

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
        max_admissions_per_second: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._validate_config(
            window_seconds=window_seconds,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
            max_admissions_per_second=max_admissions_per_second,
        )

        self.window_seconds = float(window_seconds)
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self.max_admissions_per_second = max_admissions_per_second

        self._clock = clock
        self._request_times: Deque[float] = deque()
        self._admission_times: Deque[float] = deque()
        self._state = self.FULL
        self._lock = Lock()

    @staticmethod
    def _validate_config(
        *,
        window_seconds: Number,
        low_threshold: int,
        high_threshold: int,
        max_admissions_per_second: int,
    ) -> None:
        if not isinstance(window_seconds, (int, float)) or window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0")

        if type(low_threshold) is not int or low_threshold < 0:
            raise ValueError("low_threshold must be a non-negative integer")

        if type(high_threshold) is not int or high_threshold <= low_threshold:
            raise ValueError("high_threshold must be greater than low_threshold")

        if (
            type(max_admissions_per_second) is not int
            or max_admissions_per_second <= 0
        ):
            raise ValueError("max_admissions_per_second must be a positive integer")

    def record_request(self) -> Dict[str, object]:
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._request_times.append(now)
            self._update_state()
            return self._status_unlocked()

    def reserve_permits(self, requested: int = 1) -> int:
        if type(requested) is not int or requested < 0:
            raise ValueError("requested must be a non-negative integer")
        if requested == 0:
            return 0

        now = self._clock()
        with self._lock:
            self._prune(now)
            self._update_state()

            if self._state == self.FULL:
                granted = requested
            else:
                remaining = max(
                    0,
                    self.max_admissions_per_second - len(self._admission_times),
                )
                granted = min(requested, remaining)

            for _ in range(granted):
                self._admission_times.append(now)

            return granted

    def try_admit(self) -> bool:
        return self.reserve_permits(1) == 1

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

        admission_cutoff = now - 1.0
        while self._admission_times and self._admission_times[0] <= admission_cutoff:
            self._admission_times.popleft()

    def _update_state(self) -> None:
        load = len(self._request_times)

        if self._state == self.FULL and load > self.high_threshold:
            self._state = self.THROTTLED
        elif self._state == self.THROTTLED and load < self.low_threshold:
            self._state = self.FULL

    def _status_unlocked(self) -> Dict[str, object]:
        if self._state == self.FULL:
            remaining_permits = None
        else:
            remaining_permits = max(
                0,
                self.max_admissions_per_second - len(self._admission_times),
            )

        return {
            "admission_state": self._state,
            "requests_in_window": len(self._request_times),
            "window_seconds": self.window_seconds,
            "low_threshold": self.low_threshold,
            "high_threshold": self.high_threshold,
            "max_admissions_per_second": self.max_admissions_per_second,
            "admissions_in_last_second": len(self._admission_times),
            "remaining_permits_this_second": remaining_permits,
        }
