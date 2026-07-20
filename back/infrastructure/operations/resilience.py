"""线程安全的 closed/open/half-open 三态熔断器。"""

from __future__ import annotations

from enum import Enum
from threading import Lock
from time import monotonic
from typing import Callable


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """依赖处于熔断状态。"""


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_timeout <= 0:
            raise ValueError("熔断阈值和恢复时间必须为正数")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._lock = Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._refresh_state()
            return self._state

    def acquire(self) -> None:
        """取得一次调用许可；半开态只允许一个探测请求。"""

        with self._lock:
            self._refresh_state()
            if self._state is CircuitState.OPEN:
                raise CircuitOpenError("circuit is open")
            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_in_flight:
                    raise CircuitOpenError("half-open probe already in flight")
                self._half_open_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = None
            self._half_open_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._half_open_in_flight = False
            self._failures += 1
            if (
                self._state is CircuitState.HALF_OPEN
                or self._failures >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()

    def _refresh_state(self) -> None:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_in_flight = False
